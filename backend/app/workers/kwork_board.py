"""Сборщик биржи заказов Kwork (kind='kwork').

Kwork — первоисточник для половины телеграм-каналов, которыми радар
пользовался раньше: они просто перепечатывают его с задержкой и теряют
бюджет со сроком. Здесь заказ берётся сразу и целиком.

Откликаться нужно на самой бирже, прямого контакта у заказа нет — поэтому
contact_url не заполняется, и в карточке честно написано, что писать некому,
а идти надо по ссылке.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal
from app.logging_conf import setup_logging
from app.models import RawMessage, Source
from app.services import kwork
from app.services.matcher import matcher
from app.workers import pulse

log = setup_logging("kwork")

MIN_TEXT_LEN = 15
MAX_TEXT_LEN = 8000
KWORK_KIND = "kwork"

# синтетический id «чата» — как у каналов и лент, чтобы дедупликация
# по (chat_id, message_id) работала одинаково для всех источников
KWORK_CHAT_ID = 7 * 10**14


def category_of(url: str | None) -> str | None:
    """Категория из адреса вида https://kwork.ru/projects?c=11."""
    if not url:
        return None
    values = parse_qs(urlsplit(url).query).get("c")
    return values[0] if values else None


async def load_boards() -> list[tuple[int, str, str | None]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Source.id, Source.url, Source.title).where(
                    Source.enabled.is_(True),
                    Source.kind == KWORK_KIND,
                )
            )
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def is_fresh(posted_at) -> bool:
    if posted_at is None:
        return True
    return datetime.now(timezone.utc) - posted_at <= timedelta(
        hours=settings.max_post_age_hours
    )


async def remember_last_post(source_id: int, projects: list[kwork.KworkProject]) -> None:
    dates = [p.posted_at for p in projects if p.posted_at]
    if not dates:
        return
    async with SessionLocal() as session:
        source = await session.get(Source, source_id)
        if source is not None:
            source.last_post_at = max(dates)
            await session.commit()


async def store(source_id: int, title: str | None, project: kwork.KworkProject) -> bool:
    if len(project.text) < MIN_TEXT_LEN:
        return False

    if not is_fresh(project.posted_at):
        return False

    blocked = await matcher.stop_hit(project.text)
    if blocked:
        log.debug("отбросил по стоп-слову %r: %s", blocked, project.text[:60])
        return False

    hits = await matcher.match(project.text)
    if not hits:
        return False

    name = title or "Kwork"
    async with SessionLocal() as session:
        result = await session.execute(
            pg_insert(RawMessage)
            .values(
                source_id=source_id,
                tg_chat_id=KWORK_CHAT_ID,
                tg_message_id=project.id,
                chat_title=name[:256],
                author_id=None,
                author_username=None,
                # отклик только через биржу
                contact_url=None,
                author_name=name[:256],
                text=project.text[:MAX_TEXT_LEN],
                link=project.link,
                matched=hits,
                posted_at=project.posted_at,
            )
            .on_conflict_do_nothing(constraint="uq_raw_chat_message")
        )
        await session.commit()

    return bool(result.rowcount)


async def poll_once(session: aiohttp.ClientSession) -> int:
    boards = await load_boards()
    if not boards:
        return 0

    added = 0
    for source_id, url, title in boards:
        try:
            projects = await kwork.fetch_category(session, category_of(url))
        except Exception as exc:
            log.warning("биржа %s недоступна: %s", url, exc)
            continue

        if not projects:
            log.warning("биржа %s ничего не отдала — возможно, сменилась разметка", url)
            continue

        await remember_last_post(source_id, projects)

        for project in projects:
            if await store(source_id, title, project):
                added += 1

        await asyncio.sleep(settings.channel_fetch_delay_sec)

    return added


async def run() -> None:
    log.info("сборщик Kwork запущен, опрос раз в %s с", settings.channel_poll_interval_sec)

    async with aiohttp.ClientSession(timeout=kwork.TIMEOUT) as session:
        while True:
            try:
                await matcher.refresh()
                added = await poll_once(session)
                if added:
                    log.info("новых заказов в очередь: %d", added)
                    pulse.ping()
            except Exception:
                log.exception("сбой обхода Kwork")

            await asyncio.sleep(settings.channel_poll_interval_sec)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
