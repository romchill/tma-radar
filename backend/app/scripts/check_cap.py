"""Проверка дневного лимита: он должен резать пуши, а не ленту.

Раньше лимит выкидывал лишние лиды в trash, выбирая «самого слабого» за
сутки. Без ключа Anthropic почти все заказы получают ровно 60 баллов, так
что самым слабым каждый раз оказывался просто самый ранний: шестнадцатый
заказ за сутки молча убивал первый, уже улетевший владельцу пушем. Реальный
заказ на 100 000-200 000 ₽ так и пропал из ленты.

Теперь лимит считает отправленные уведомления. Лента не трогается.

Всё делается в транзакции с откатом: база не меняется, пуши не уходят.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Lead, LeadStatus, RawMessage, RawStatus
from app.services.settings_store import set_internal
from app.workers.scorer import day_start, pushes_left, utcnow

CAP = 3
MARK = "проверка лимита"


async def make_lead(session, score: int, notified: bool) -> Lead:
    raw = RawMessage(
        source_id=None,
        chat_title=MARK,
        text=f"тестовый заказ {score}",
        status=RawStatus.PENDING,
        posted_at=utcnow(),
    )
    session.add(raw)
    await session.flush()

    lead = Lead(
        raw_message_id=raw.id,
        score=score,
        status=LeadStatus.NEW,
        summary=MARK,
        notified_at=utcnow() if notified else None,
    )
    session.add(lead)
    await session.flush()
    return lead


async def main() -> None:
    checks: list[tuple[str, bool]] = []

    async with SessionLocal() as session:
        # сегодняшние настоящие лиды тоже считаются, поэтому начинаем с чистого
        # листа: убираем их отметки об отправке внутри транзакции
        await session.execute(
            Lead.__table__.update()
            .where(Lead.notified_at >= day_start())
            .values(notified_at=None)
        )
        await set_internal(session, "daily_lead_cap", CAP)

        left = await pushes_left(session)
        print(f"лимит {CAP}, сегодня ещё ничего не отправляли -> осталось {left}")
        checks.append(("лимит виден целиком", left == CAP))

        leads = []
        for i, score in enumerate((60, 60, 60), start=1):
            leads.append(await make_lead(session, score, notified=True))
            left = await pushes_left(session)
            print(f"   отправлен пуш {i} -> осталось {left}")
            checks.append((f"после {i} пушей осталось {CAP - i}", left == CAP - i))

        # четвёртый заказ: пуша не будет, но в ленте он остаться обязан
        extra = await make_lead(session, 84, notified=False)
        left = await pushes_left(session)
        print(f"\nприходит заказ на 84 балла сверх лимита -> осталось {left}, "
              f"статус={extra.status}")
        checks.append(("лимит закрыт", left == 0))
        checks.append(("заказ сверх лимита остался в ленте", extra.status == LeadStatus.NEW))

        in_feed = await session.scalar(
            select(Lead.id).where(Lead.summary == MARK, Lead.status == LeadStatus.TRASH).limit(1)
        )
        checks.append(("лимит никого не выкинул в мусор", in_feed is None))

        await set_internal(session, "daily_lead_cap", 0)
        checks.append(("0 = без лимита", await pushes_left(session) is None))

        await session.rollback()

        leftover = await session.scalar(select(Lead.id).where(Lead.summary == MARK).limit(1))
        checks.append(("база не изменилась", leftover is None))

    print()
    for name, ok in checks:
        print(("  [ok]   " if ok else "  [FAIL] ") + name)
    print("\nвсё верно" if all(ok for _, ok in checks) else "\nесть провалы")


if __name__ == "__main__":
    asyncio.run(main())
