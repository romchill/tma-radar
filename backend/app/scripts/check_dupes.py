"""Проверка склейки дублей: один заказ — одно уведомление.

Каналы @freelance_zakazy и @it_zakazy перепечатывают Kwork, поэтому один и
тот же заказ приходит дважды: напрямую с биржи и постом в канале. Это два
одинаковых уведомления владельцу и потраченный впустую слот из дневного
лимита в 15 пушей.

Важно не переусердствовать: разные заказы склеивать нельзя ни при каких
обстоятельствах — потерянный заказ хуже лишнего уведомления. Поэтому
сравниваются ссылки на заказ, а не тексты, и посты канала без ссылки на
биржу остаются каждый сам по себе.

Всё делается в транзакции с откатом: база не меняется, пуши не уходят.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Lead, LeadStatus, RawMessage, RawStatus
from app.workers.scorer import find_same_order, utcnow

MARK = "проверка дублей"


async def make_raw(session, link: str, text: str) -> RawMessage:
    raw = RawMessage(
        chat_title=MARK,
        text=text,
        status=RawStatus.PENDING,
        posted_at=utcnow(),
        link=link,
    )
    session.add(raw)
    await session.flush()
    return raw


async def make_lead(session, raw: RawMessage) -> Lead:
    lead = Lead(raw_message_id=raw.id, score=70, status=LeadStatus.NEW, summary=MARK)
    session.add(lead)
    await session.flush()
    return lead


async def main() -> None:
    checks: list[tuple[str, bool]] = []

    async with SessionLocal() as session:
        # первый заказ пришёл с Kwork и стал лидом
        kwork = await make_raw(session, "https://kwork.ru/projects/999001", "нужен телеграм бот")
        first = await make_lead(session, kwork)

        # тот же заказ перепечатал канал — ссылка после очистки та же
        repost = await make_raw(
            session, "https://kwork.ru/projects/999001", "📌 Нужен телеграм бот"
        )
        twin = await find_same_order(session, repost)
        ok = twin == first.id
        checks.append(("перепечатка узнаётся по ссылке", ok))
        print(f"  перепечатка -> лид {twin} (первый был {first.id})")

        # другой заказ на той же бирже склеивать нельзя
        other = await make_raw(session, "https://kwork.ru/projects/999002", "нужен бот")
        twin = await find_same_order(session, other)
        checks.append(("другой заказ не склеивается", twin is None))

        # сам с собой лид не склеивается
        twin = await find_same_order(session, kwork)
        checks.append(("заказ не считает дублем сам себя", twin is None))

        # реферальный хвост не мешает узнать тот же заказ
        with_ref = await make_raw(
            session, "https://kwork.ru/projects/999001?ref=15678240", "тот же заказ"
        )
        twin = await find_same_order(session, with_ref)
        checks.append(("реферальный хвост не мешает склейке", twin == first.id))

        # посты канала без ссылки на биржу — каждый сам по себе
        post_a = await make_raw(session, "https://t.me/some_channel/1", "нужен бот")
        await make_lead(session, post_a)
        post_b = await make_raw(session, "https://t.me/some_channel/2", "нужен бот")
        twin = await find_same_order(session, post_b)
        checks.append(("посты канала не склеиваются между собой", twin is None))

        # заказ, который ещё никто не ловил
        fresh = await make_raw(session, "https://kwork.ru/projects/999003", "нужен бот")
        twin = await find_same_order(session, fresh)
        checks.append(("новый заказ проходит свободно", twin is None))

        await session.rollback()

        left = await session.scalar(select(Lead.id).where(Lead.summary == MARK).limit(1))
        checks.append(("база не изменилась", left is None))

    print()
    for name, ok in checks:
        print(("  [ok]   " if ok else "  [FAIL] ") + name)
    print("\nвсё верно" if all(ok for _, ok in checks) else "\nесть провалы")


if __name__ == "__main__":
    asyncio.run(main())
