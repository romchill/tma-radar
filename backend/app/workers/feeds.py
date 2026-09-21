"""Сборщик RSS-лент бирж (kind='rss').

Устроен так же, как сборщик каналов: забрал, отфильтровал ключевиками,
положил в ту же очередь. Отличие одно — источник первичный. Канал в
телеграме перепечатывает биржу с задержкой и теряет часть полей, а лента
отдаёт заказ сразу, с заголовком, описанием и ссылкой на страницу заказа.

Контакта у таких заказов нет: откликаются на самой бирже. Поэтому
contact_url не заполняется, и в приложении лид честно помечен как «прямого
контакта нет».
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal
from app.logging_conf import setup_logging
from app.models import RawMessage, Source
from app.services import feeds
from app.services.matcher import matcher
from app.workers import pulse

log = setup_logging("feeds")

MIN_TEXT_LEN = 15
MAX_TEXT_LEN = 8000
FEED_KIND = "rss"


async def load_feeds() -> list[tuple[int, str, str | None]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Source.id, Source.url, Source.title).where(
                    Source.enabled.is_(True),
                    Source.kind == FEED_KIND,
                    Source.url.is_not(None),
                )
            )
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def is_fresh(posted_at) -> bool:
    """Заказ старше 12 часов на бирже уже разобрали — в ленте ему не место."""
    if posted_at is None:
        return True  # даты нет — не наказываем, пусть решает фильтр
    return datetime.now(timezone.utc) - posted_at <= timedelta(
        hours=settings.max_post_age_hours
    )


async def remember_last_post(source_id: int, items: list[feeds.FeedItem]) -> None:
    dates = [i.posted_at for i in items if i.posted_at]
    if not dates:
        return
    async with SessionLocal() as session:
        source = await session.get(Source, source_id)
        if source is not None:
            source.last_post_at = max(dates)
            await session.commit()


async def store(source_id: int, title: str | None, item: feeds.FeedItem) -> bool:
    """Кладёт заказ в очередь на скоринг. False — не подошёл или уже есть."""
    if len(item.text) < MIN_TEXT_LEN:
        return False

    if not is_fresh(item.posted_at):
        return False

    blocked = await matcher.stop_hit(item.text)
    if blocked:
        log.debug("отбросил по стоп-слову %r: %s", blocked, item.text[:60])
        return False

    hits = await matcher.match(item.text)
    if not hits:
        return False

    name = title or "биржа"
    async with SessionLocal() as session:
        result = await session.execute(
            pg_insert(RawMessage)
            .values(
                source_id=source_id,
                tg_chat_id=feeds.feed_chat_id(item.feed_url),
                tg_message_id=item.item_id,
                chat_title=name[:256],
                author_id=None,
                author_username=None,
                # отклик только на самой бирже, писать напрямую некому
                contact_url=None,
                author_name=name[:256],
                text=item.text[:MAX_TEXT_LEN],
                link=item.link,
                matched=hits,
                posted_at=item.posted_at,
            )
            .on_conflict_do_nothing(constraint="uq_raw_chat_message")
        )
        await session.commit()

    return bool(result.rowcount)


async def poll_once(session: aiohttp.ClientSession) -> int:
    sources = await load_feeds()
    if not sources:
        return 0

    added = 0
    for source_id, url, title in sources:
        try:
            items = await feeds.fetch(session, url)
        except Exception as exc:
            log.warning("лента %s недоступна: %s", url, exc)
            continue

        if not items:
            log.warning("лента %s не разобралась или пуста", url)
            continue

        await remember_last_post(source_id, items)

        for item in items:
            if await store(source_id, title, item):
                added += 1

        await asyncio.sleep(settings.channel_fetch_delay_sec)

    return added


async def run() -> None:
    log.info("сборщик лент запущен, опрос раз в %s с", settings.channel_poll_interval_sec)

    async with aiohttp.ClientSession(timeout=feeds.TIMEOUT) as session:
        while True:
            try:
                await matcher.refresh()
                added = await poll_once(session)
                if added:
                    log.info("новых заказов в очередь: %d", added)
                    pulse.ping()
            except Exception:
                log.exception("сбой обхода лент")

            await pulse.sleep_until_next_tick(settings.channel_poll_interval_sec)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
