"""Скорер: забирает pending-сообщения, гоняет через LLM, заводит лидов.

Очередь — сама таблица raw_messages. Батч захватывается атомарно
(UPDATE ... FOR UPDATE SKIP LOCKED), поэтому воркер можно масштабировать
простым `docker compose up --scale scorer=3`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.logging_conf import setup_logging
from app.models import Contact, Lead, LeadEvent, LeadStatus, RawMessage, RawStatus
from app.services import llm, notify
from app.services.budget import parse_budget
from app.services.matcher import matcher
from app.services.settings_store import get_setting, set_internal
from app.workers import pulse

log = setup_logging("scorer")

STALE_PROCESSING_MIN = 15


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def day_start() -> datetime:
    return utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


async def reset_stale(session: AsyncSession) -> int:
    """Возвращает в очередь то, что зависло после падения воркера."""
    cutoff = utcnow() - timedelta(minutes=STALE_PROCESSING_MIN)
    res = await session.execute(
        update(RawMessage)
        .where(RawMessage.status == RawStatus.PROCESSING, RawMessage.created_at < cutoff)
        .values(status=RawStatus.PENDING)
    )
    await session.commit()
    return res.rowcount or 0


async def claim_batch(session: AsyncSession, limit: int) -> list[RawMessage]:
    ids = (
        select(RawMessage.id)
        .where(RawMessage.status == RawStatus.PENDING)
        .order_by(RawMessage.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    res = await session.execute(
        update(RawMessage)
        .where(RawMessage.id.in_(ids))
        .values(status=RawStatus.PROCESSING)
        .returning(RawMessage)
        .execution_options(synchronize_session=False)
    )
    rows = list(res.scalars().unique().all())
    await session.commit()
    return rows


async def is_on_cooldown(session: AsyncSession, author_id: int | None) -> bool:
    if not author_id:
        return False
    contact = await session.get(Contact, author_id)
    if contact is None:
        return False
    if contact.blocked:
        return True
    if contact.last_lead_at is None:
        return False
    return utcnow() - contact.last_lead_at < timedelta(days=settings.contact_cooldown_days)


async def pushes_left(session: AsyncSession) -> int | None:
    """Сколько пушей ещё можно отправить сегодня. None = лимита нет.

    Лимит считает ОТПРАВЛЕННЫЕ уведомления, а не размер ленты. Раньше он
    работал наоборот: лишние лиды улетали в trash, причём вытеснялся «самый
    слабый за сутки» — а без ключа Anthropic почти все заказы получают ровно
    60 баллов, так что самым слабым каждый раз оказывался просто самый
    ранний. Шестнадцатый заказ за сутки молча убивал первый, уже улетевший
    владельцу пушем, и настоящие заказы на 100-200 тысяч пропадали из ленты.

    Теперь ничего не выбрасывается: в ленте лежит всё, что прошло порог, а
    ограничен только поток сообщений в телеграм.
    """
    cap = int(await get_setting(session, "daily_lead_cap", settings.daily_lead_cap))
    if cap <= 0:  # 0 = без лимита
        return None

    sent_today = await session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.notified_at >= day_start())
    )
    return max(0, cap - (sent_today or 0))


async def warn_cap_reached(session: AsyncSession, cap: int) -> None:
    """Один раз за сутки предупреждает, что пуши на сегодня кончились."""
    today = day_start().date().isoformat()
    if await get_setting(session, "cap_notice_day", "") == today:
        return
    await set_internal(session, "cap_notice_day", today)
    await notify.notify_text(
        f"На сегодня лимит {cap} уведомлений исчерпан. "
        f"Новые заказы продолжают падать в ленту приложения — загляни туда."
    )


async def upsert_contact(session: AsyncSession, raw: RawMessage) -> int | None:
    if not raw.author_id:
        return None
    await session.execute(
        pg_insert(Contact)
        .values(
            tg_user_id=raw.author_id,
            username=raw.author_username,
            name=raw.author_name,
            leads_count=1,
            last_lead_at=utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[Contact.tg_user_id],
            set_={
                "username": raw.author_username,
                "name": raw.author_name,
                "leads_count": Contact.leads_count + 1,
                "last_lead_at": utcnow(),
            },
        )
    )
    return raw.author_id


MAX_HEURISTIC_SCORE = 84
# Часть баллов за ключевики упирается в этот потолок, остальное добирается
# бюджетом. Без такого разделения сумма весов упиралась в общий максимум и
# заказ на 5 000 ₽ вставал в ленте выше заказа на 60 000 ₽.
MAX_KEYWORD_SCORE = 60

# Разбор бюджета живёт в app/services/budget.py.


async def heuristic_assess(raw: RawMessage) -> llm.Assessment:
    """Бесплатный режим: оценка по весам ключевиков плюс размер бюджета.

    Шумнее LLM — отличить заказчика от такого же исполнителя по одним словам
    нельзя, — но лента наполняется и денег не стоит. Потолок ниже порога
    горячего пуша: будить ночью по догадке регулярки неправильно.
    """
    weight = await matcher.weight(raw.text)
    budget_text, budget_bonus = parse_budget(raw.text)

    keyword_score = min(MAX_KEYWORD_SCORE, 35 + weight)
    score = min(MAX_HEURISTIC_SCORE, keyword_score + budget_bonus)
    hits = ", ".join(raw.matched or [])
    why = f"без ключа Anthropic: оценка по ключевикам ({hits[:100]})"
    if budget_bonus:
        why += f"; бюджет {budget_text} даёт +{budget_bonus}"

    return llm.Assessment(
        is_lead=True,
        score=score,
        niche="",
        summary=raw.text[:200],
        pain="",
        budget_hint=budget_text,
        urgency="medium" if score >= 70 else "low",
        why=why,
    )


async def process(session: AsyncSession, raw: RawMessage) -> None:
    if await is_on_cooldown(session, raw.author_id):
        raw.status = RawStatus.DUPLICATE
        raw.processed_at = utcnow()
        await session.commit()
        log.info("#%s пропуск: автор на кулдауне", raw.id)
        return

    threshold = int(await get_setting(session, "score_threshold", settings.score_threshold))
    hot = int(await get_setting(session, "score_hot", settings.score_hot))

    if llm.available():
        system = await get_setting(session, "scorer_system", None)
        result = await llm.assess(
            raw.text,
            chat_title=raw.chat_title,
            author_name=raw.author_name,
            system=system,
        )
    else:
        result = await heuristic_assess(raw)

    if not result.is_lead:
        raw.status = RawStatus.REJECTED
        raw.processed_at = utcnow()
        await session.commit()
        log.info("#%s не лид (%s)", raw.id, result.why[:60])
        return

    contact_id = await upsert_contact(session, raw)

    lead = Lead(
        raw_message_id=raw.id,
        contact_id=contact_id,
        score=result.score,
        niche=result.niche,
        budget_hint=result.budget_hint,
        urgency=result.urgency,
        pain=result.pain,
        summary=result.summary,
        why=result.why,
        status=LeadStatus.NEW if result.score >= threshold else LeadStatus.TRASH,
    )
    session.add(lead)
    raw.status = RawStatus.SCORED
    raw.processed_at = utcnow()
    await session.flush()

    session.add(LeadEvent(lead_id=lead.id, kind="created", payload={"score": result.score}))
    await session.commit()

    log.info("#%s -> лид %s score=%s %s", raw.id, lead.id, lead.score, lead.niche)

    if lead.status != LeadStatus.NEW:
        return

    # Шлём КАЖДЫЙ лид, попавший в ленту, а не только высокобалльный: заказ
    # живёт часы, копить его в приложении, куда владелец заглядывает раз в
    # день, бессмысленно. Порог `score_hot` теперь влияет только на пометку
    # «горячий» в самом сообщении.
    left = await pushes_left(session)
    if left == 0:
        cap = int(await get_setting(session, "daily_lead_cap", settings.daily_lead_cap))
        log.info("лид %s не отправлен: лимит %s уведомлений на сегодня исчерпан", lead.id, cap)
        await warn_cap_reached(session, cap)
        await session.commit()
        return

    base = await get_setting(session, "webapp_url", "")
    if await notify.notify_lead(lead, raw, base, hot=lead.score >= hot):
        lead.notified_at = utcnow()
        await session.commit()


async def tick() -> int:
    async with SessionLocal() as session:
        batch = await claim_batch(session, settings.scorer_batch)
        if not batch:
            return 0

        for raw in batch:
            try:
                await process(session, raw)
            except Exception as exc:
                await session.rollback()
                log.exception("ошибка скоринга #%s", raw.id)
                await session.execute(
                    update(RawMessage)
                    .where(RawMessage.id == raw.id)
                    .values(
                        status=RawStatus.ERROR,
                        error=str(exc)[:2000],
                        processed_at=utcnow(),
                    )
                )
                await session.commit()

        return len(batch)


async def run() -> None:
    if llm.available():
        log.info(
            "скорер запущен: модель=%s порог=%s горячий=%s",
            settings.model_scorer, settings.score_threshold, settings.score_hot,
        )
    else:
        log.warning(
            "скорер запущен БЕЗ ключа Anthropic: оценка по ключевикам, "
            "черновики сообщений недоступны. Порог=%s",
            settings.score_threshold,
        )

    async with SessionLocal() as session:
        restored = await reset_stale(session)
        if restored:
            log.info("вернул в очередь зависших: %d", restored)

    while True:
        try:
            done = await tick()
        except Exception:
            log.exception("сбой цикла скорера")
            done = 0
        if not done:
            # Очередь пуста — цикл закончен, остальным можно ходить в базу.
            pulse.cycle_done()
            # Спим до сигнала сборщиков, а не будим базу по таймеру. На
            # бесплатном хостинге она считает время работы и засыпает только
            # после 5 минут покоя — опрос «нет ли работы» раз в 5 секунд
            # не давал ей заснуть вообще.
            await pulse.wait(settings.scorer_interval_sec)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
