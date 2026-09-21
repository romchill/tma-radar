"""Сборщик заказов со стен групп ВКонтакте.

Главное отличие от телеграм-каналов: у поста на стене есть автор-человек,
и ему можно написать бесплатно. Поэтому именно отсюда приходят лиды,
пригодные для прямого обращения.

Посты от имени самой группы (from_id < 0) собираются тоже, но контакта не
получают — это то же, что пост админа в канале.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal
from app.logging_conf import setup_logging
from app.models import RawMessage, Source
from app.services import vk
from app.services.matcher import matcher
from app.workers import pulse

log = setup_logging("vk")

VK_KIND = "vk_group"
MIN_TEXT_LEN = 15
MAX_TEXT_LEN = 8000


def vk_chat_id(group: str) -> int:
    """Синтетический id группы для ограничения уникальности raw_messages.

    Диапазон 8*10^14 — свой, чтобы не столкнуться ни с телеграм-чатами
    (отрицательные), ни с синтетическими id каналов (9*10^14).
    """
    digest = hashlib.sha1(group.lower().encode()).hexdigest()[:12]
    return 8 * 10**14 + int(digest, 16) % 10**11


async def load_groups() -> list[tuple[int, str, str | None]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Source.id, Source.username, Source.title).where(
                    Source.enabled.is_(True),
                    Source.kind == VK_KIND,
                    Source.username.is_not(None),
                )
            )
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def is_fresh(posted_at) -> bool:
    if posted_at is None:
        return True
    return datetime.now(timezone.utc) - posted_at <= timedelta(hours=settings.max_post_age_hours)


async def remember_last_post(source_id: int, posts: list[vk.VkPost]) -> None:
    dates = [p.posted_at for p in posts if p.posted_at]
    if not dates:
        return
    async with SessionLocal() as session:
        source = await session.get(Source, source_id)
        if source is not None:
            source.last_post_at = max(dates)
            await session.commit()


async def store(source_id: int, title: str | None, post: vk.VkPost) -> bool:
    if len(post.text) < MIN_TEXT_LEN:
        return False

    if not is_fresh(post.posted_at):
        return False

    if await matcher.stop_hit(post.text):
        return False
    hits = await matcher.match(post.text)
    if not hits:
        return False

    async with SessionLocal() as session:
        result = await session.execute(
            pg_insert(RawMessage)
            .values(
                source_id=source_id,
                tg_chat_id=vk_chat_id(post.group),
                tg_message_id=post.post_id,
                chat_title=(title or post.group)[:256],
                author_id=post.author_id if post.by_user else None,
                author_username=post.author_screen,
                author_name=(post.author_name or title or post.group)[:256],
                contact_url=post.contact_url,
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
    groups = await load_groups()
    if not groups:
        return 0

    added = 0
    for source_id, username, title in groups:
        posts = await vk.fetch_wall(session, username)
        if not posts:
            continue

        await remember_last_post(source_id, posts)

        await vk.resolve_authors(session, posts)

        for post in posts:
            try:
                if await store(source_id, title, post):
                    added += 1
                    log.info(
                        "поймал: %s | %s | %s",
                        username,
                        post.contact_url or "без контакта",
                        post.text[:60].replace("\n", " "),
                    )
            except Exception:
                log.exception("не сохранил пост %s_%s", username, post.post_id)

    return added


async def run() -> None:
    if not vk.available():
        log.info("источник ВК выключен: не задан VK_SERVICE_TOKEN")
        # не крутим пустой цикл: воркер перезапустит задачу, если ключ появится
        while not vk.available():
            await asyncio.sleep(300)

    log.info("сборщик ВК запущен, опрос раз в %d с", settings.vk_poll_interval_sec)
    await matcher.refresh(force=True)

    async with aiohttp.ClientSession(timeout=vk.TIMEOUT) as session:
        while True:
            try:
                await matcher.refresh()
                added = await poll_once(session)
                if added:
                    log.info("новых постов в очередь: %d", added)
                    # будим скорера сразу, а не ждём его собственного интервала
                    pulse.ping()
            except Exception:
                log.exception("сбой обхода групп ВК")

            await asyncio.sleep(settings.vk_poll_interval_sec)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
