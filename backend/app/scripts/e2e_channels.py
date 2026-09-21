"""Сквозная проверка сбора из публичных каналов.

Гоняет цепочку целиком на настоящей базе: канал -> raw_messages -> скоринг ->
лид в ленте. Временные данные (тестовый канал и ключевик) убираются за собой.

Запуск: docker compose run --rm api python -m app.scripts.e2e_channels
"""

from __future__ import annotations

import asyncio

import aiohttp
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import Keyword, Lead, LeadEvent, RawMessage, Source
from app.services import tgweb
from app.services.matcher import matcher
from app.workers import channels, scorer

TEST_CHANNEL = "telegram"
TEST_KEYWORD = "bots?"  # без обратных слэшей: их съедает передача через шелл


def say(step: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'OK  ' if ok else 'ПРОВАЛ'}] {step}{(' — ' + detail) if detail else ''}")
    return ok


async def cleanup() -> None:
    chat_id = tgweb.channel_chat_id(TEST_CHANNEL)
    async with SessionLocal() as session:
        raw_ids = (
            await session.execute(select(RawMessage.id).where(RawMessage.tg_chat_id == chat_id))
        ).scalars().all()
        if raw_ids:
            lead_ids = (
                await session.execute(select(Lead.id).where(Lead.raw_message_id.in_(raw_ids)))
            ).scalars().all()
            if lead_ids:
                await session.execute(delete(LeadEvent).where(LeadEvent.lead_id.in_(lead_ids)))
                await session.execute(delete(Lead).where(Lead.id.in_(lead_ids)))
            await session.execute(delete(RawMessage).where(RawMessage.id.in_(raw_ids)))
        await session.execute(delete(Source).where(Source.tg_chat_id == chat_id))
        await session.execute(delete(Keyword).where(Keyword.pattern == TEST_KEYWORD))
        await session.commit()


async def main() -> int:
    await cleanup()
    results: list[bool] = []

    # 1. канал читается без аккаунта
    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as http:
        posts = await tgweb.fetch_channel(http, TEST_CHANNEL)
    results.append(say("канал читается без аккаунта", bool(posts), f"постов: {len(posts)}"))
    if not posts:
        return 1

    # Временный ключевик: боевой набор рассчитан на русские заказы, а тестовый
    # канал англоязычный. Шаблон нарочно вычурный, чтобы не совпасть с рабочим.
    async with SessionLocal() as session:
        await session.execute(
            pg_insert(Keyword)
            .values(pattern=TEST_KEYWORD, is_regex=True, weight=25, enabled=True)
            .on_conflict_do_nothing(index_elements=[Keyword.pattern])
        )
        await session.execute(
            pg_insert(Source)
            .values(
                kind=channels.CHANNEL_KIND,
                username=TEST_CHANNEL,
                title=TEST_CHANNEL,
                tg_chat_id=tgweb.channel_chat_id(TEST_CHANNEL),
                enabled=True,
            )
            .on_conflict_do_nothing(index_elements=[Source.tg_chat_id])
        )
        await session.commit()

    await matcher.refresh(force=True)

    # диагностика: видно, на каком звене рвётся цепочка
    found_channels = await channels.load_channels()
    print(f"       каналов в сборе: {found_channels}")
    print(f"       шаблонов в матчере: {len(matcher._compiled)}")
    probe = await matcher.match(posts[0].text)
    print(f"       пробный матч по первому посту: {probe}")
    print(f"       длина первого поста: {len(posts[0].text)}")

    # 2. обход кладёт посты в очередь
    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as http:
        added = await channels.poll_once(http)
    results.append(say("посты попали в очередь на скоринг", added > 0, f"добавлено: {added}"))

    # 3. повторный обход не плодит дубликаты
    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as http:
        again = await channels.poll_once(http)
    results.append(say("повтор не создаёт дубликатов", again == 0, f"добавлено повторно: {again}"))

    # 4. скорер разбирает очередь (бесплатный режим)
    processed = await scorer.tick()
    results.append(say("скорер обработал очередь", processed > 0, f"обработано: {processed}"))

    # 5. лиды появились и привязаны к каналу
    chat_id = tgweb.channel_chat_id(TEST_CHANNEL)
    async with SessionLocal() as session:
        leads = await session.scalar(
            select(func.count())
            .select_from(Lead)
            .join(RawMessage, Lead.raw_message_id == RawMessage.id)
            .where(RawMessage.tg_chat_id == chat_id)
        )
        sample = (
            await session.execute(
                select(Lead.score, Lead.why, RawMessage.link, RawMessage.chat_title)
                .join(RawMessage, Lead.raw_message_id == RawMessage.id)
                .where(RawMessage.tg_chat_id == chat_id)
                .limit(1)
            )
        ).first()

    results.append(say("лиды созданы", bool(leads), f"лидов: {leads}"))
    if sample:
        print(f"       пример: score={sample[0]} канал={sample[3]} ссылка={sample[2]}")
        print(f"       обоснование: {sample[1][:80]}")

    await cleanup()
    async with SessionLocal() as session:
        left = await session.scalar(
            select(func.count()).select_from(RawMessage).where(RawMessage.tg_chat_id == chat_id)
        )
    results.append(say("тестовые данные убраны", left == 0, f"осталось: {left}"))

    print()
    print("ИТОГ:", "всё сошлось" if all(results) else "ЕСТЬ ПРОВАЛЫ")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
