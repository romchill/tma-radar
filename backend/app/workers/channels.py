"""Сборщик публичных каналов — замена юзерботу.

Обходит каналы из таблицы sources (kind='tg_channel'), читает их веб-версию
и складывает подходящие посты в raw_messages. Дальше всё как обычно: тот же
предфильтр по ключевикам, тот же скорер, та же лента.

Аккаунт, номер и api_id не нужны — поэтому этот путь работает там, где
my.telegram.org недоступен.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal
from app.logging_conf import setup_logging
from app.models import RawMessage, Source
from app.services import tgweb
from app.services.matcher import matcher
from app.workers import pulse

log = setup_logging("channels")

MIN_TEXT_LEN = 15
MAX_TEXT_LEN = 8000
CHANNEL_KIND = "tg_channel"


async def load_channels() -> list[tuple[int, str, str | None]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Source.id, Source.username, Source.title).where(
                    Source.enabled.is_(True),
                    Source.kind == CHANNEL_KIND,
                    Source.username.is_not(None),
                )
            )
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def channel_own_contacts(posts: list[tgweb.ChannelPost]) -> set[str]:
    """Контакты, принадлежащие самому каналу, а не клиентам.

    Каналы-перепечатки бирж ставят в каждый пост один и тот же @username —
    это админ или бот канала. Показать его как контакт лида значит предложить
    написать не тому человеку, поэтому такие контакты вырезаем.
    """
    counts = Counter(post.contact for post in posts if post.contact)
    threshold = max(2, len(posts) // 3)
    return {name for name, seen in counts.items() if seen >= threshold}


def is_fresh(posted_at) -> bool:
    """Заказ старше 12 часов на бирже уже разобрали — в ленте ему не место."""
    if posted_at is None:
        return True  # даты нет — не наказываем, пусть решает фильтр
    age = datetime.now(timezone.utc) - posted_at
    return age <= timedelta(hours=settings.max_post_age_hours)


async def remember_last_post(source_id: int, posts: list[tgweb.ChannelPost]) -> None:
    """Запоминает дату свежайшего поста — по ней видно, что источник умер."""
    dates = [p.posted_at for p in posts if p.posted_at]
    if not dates:
        return
    async with SessionLocal() as session:
        source = await session.get(Source, source_id)
        if source is not None:
            source.last_post_at = max(dates)
            await session.commit()


async def store(
    source_id: int,
    title: str | None,
    post: tgweb.ChannelPost,
    own_contacts: set[str] | None = None,
) -> bool:
    """Кладёт пост в очередь на скоринг. False — не подошёл или уже есть."""
    if len(post.text) < MIN_TEXT_LEN:
        return False

    if not is_fresh(post.posted_at):
        return False

    blocked = await matcher.stop_hit(post.text)
    if blocked:
        log.debug("отбросил по стоп-слову %r: %s", blocked, post.text[:60])
        return False

    hits = await matcher.match(post.text)
    if not hits:
        return False

    contact = post.contact
    if contact and own_contacts and contact in own_contacts:
        contact = None

    async with SessionLocal() as session:
        result = await session.execute(
            pg_insert(RawMessage)
            .values(
                source_id=source_id,
                tg_chat_id=tgweb.channel_chat_id(post.channel),
                tg_message_id=post.post_id,
                chat_title=(title or post.channel)[:256],
                # у поста в канале нет автора: писать будем тому, кто указан
                # в самом тексте, а «именем» показываем канал
                author_id=None,
                author_username=contact,
                contact_url=f"https://t.me/{contact}" if contact else None,
                author_name=(title or post.channel)[:256],
                text=post.text[:MAX_TEXT_LEN],
                link=post.link,
                matched=hits,
                posted_at=post.posted_at,
            )
            .on_conflict_do_nothing(constraint="uq_raw_chat_message")
        )
        await session.commit()

    return bool(result.rowcount)


async def poll_once(session: aiohttp.ClientSession) -> int:
    channels = await load_channels()
    if not channels:
        return 0

    added = 0
    for index, (source_id, username, title) in enumerate(channels):
        if index:
            # не долбим t.me подряд: канал раз в несколько секунд
            await asyncio.sleep(settings.channel_fetch_delay_sec)

        posts = await tgweb.fetch_channel(session, username)
        await remember_last_post(source_id, posts)
        own = channel_own_contacts(posts)
        if own:
            log.debug("контакты канала %s (не клиентские): %s", username, own)

        for post in posts:
            try:
                if await store(source_id, title, post, own):
                    added += 1
                    log.info(
                        "поймал: %s | %s",
                        username,
                        post.text[:70].replace("\n", " "),
                    )
            except Exception:
                log.exception("не сохранил пост %s/%s", username, post.post_id)

    return added


async def run() -> None:
    log.info("сборщик каналов запущен, опрос раз в %d с", settings.channel_poll_interval_sec)
    await matcher.refresh(force=True)

    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as session:
        while True:
            try:
                await matcher.refresh()
                added = await poll_once(session)
                if added:
                    log.info("новых постов в очередь: %d", added)
                    # будим скорера сразу, а не ждём его собственного интервала
                    pulse.ping()
            except Exception:
                log.exception("сбой обхода каналов")

            await pulse.sleep_until_next_tick(settings.channel_poll_interval_sec)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
