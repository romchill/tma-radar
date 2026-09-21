"""Сборщик: юзербот слушает чаты и складывает подходящие сообщения в raw_messages.

ВАЖНО: аккаунт только ЧИТАЕТ. Никаких рассылок, инвайтов и автоответов —
именно за них Telegram выдаёт бан. Писать людям ты будешь руками
со своего основного аккаунта из мини-аппа.

Сессия создаётся один раз интерактивно:
    docker compose run --rm collector python -m app.scripts.login
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User

from app.config import settings
from app.services import tgsession
from app.db import SessionLocal
from app.logging_conf import setup_logging
from app.models import RawMessage, Source
from app.services.matcher import matcher

log = setup_logging("collector")

SOURCES_REFRESH_SEC = 60
DIALOG_SYNC_SEC = 900
MIN_TEXT_LEN = 15
MAX_TEXT_LEN = 8000


class Collector:
    def __init__(self) -> None:
        self.client = TelegramClient(
            tgsession.build(),
            settings.tg_api_id,
            settings.tg_api_hash,
            # человекоподобные параметры снижают шанс лишнего внимания
            device_model="Desktop",
            system_version="Windows 10",
        )
        self.enabled_chats: dict[int, int] = {}  # tg_chat_id -> source_id
        self.me_id: int | None = None

    # ---------------------------------------------------------------- sources

    async def load_sources(self) -> None:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(Source.tg_chat_id, Source.id).where(
                        Source.enabled.is_(True),
                        Source.kind == "tg_chat",
                        Source.tg_chat_id.is_not(None),
                    )
                )
            ).all()
        self.enabled_chats = {chat_id: source_id for chat_id, source_id in rows}
        log.info("активных чатов-источников: %d", len(self.enabled_chats))

    async def sync_dialogs(self) -> None:
        """Подтягивает список групп/каналов аккаунта в таблицу sources,
        чтобы их можно было включать/выключать из мини-аппа."""
        found = 0
        async for dialog in self.client.iter_dialogs(limit=500):
            entity = dialog.entity
            if isinstance(entity, User):
                continue
            if not isinstance(entity, (Chat, Channel)):
                continue
            # каналы-вещалки без комментариев обычно бесполезны, но пусть будут выключены
            broadcast = bool(getattr(entity, "broadcast", False))

            async with SessionLocal() as session:
                stmt = (
                    pg_insert(Source)
                    .values(
                        kind="tg_chat",
                        tg_chat_id=dialog.id,
                        username=getattr(entity, "username", None),
                        title=(dialog.name or "")[:256],
                        enabled=settings.autoenable_new_sources and not broadcast,
                    )
                    .on_conflict_do_update(
                        index_elements=[Source.tg_chat_id],
                        set_={
                            "title": (dialog.name or "")[:256],
                            "username": getattr(entity, "username", None),
                        },
                    )
                )
                await session.execute(stmt)
                await session.commit()
            found += 1

        log.info("синхронизировано диалогов: %d", found)
        await self.load_sources()

    # ---------------------------------------------------------------- capture

    @staticmethod
    def _build_link(chat, message_id: int) -> str | None:
        username = getattr(chat, "username", None)
        if username:
            return f"https://t.me/{username}/{message_id}"
        chat_id = getattr(chat, "id", None)
        if chat_id:
            return f"https://t.me/c/{chat_id}/{message_id}"
        return None

    async def handle(self, event: events.NewMessage.Event) -> None:
        try:
            if event.out:
                return

            chat_id = event.chat_id
            source_id = self.enabled_chats.get(chat_id)
            if source_id is None:
                return

            text = (event.raw_text or "").strip()
            if len(text) < MIN_TEXT_LEN:
                return

            hits = await matcher.match(text)
            if not hits:
                return

            sender = await event.get_sender()
            if isinstance(sender, User) and (sender.bot or sender.id == self.me_id):
                return

            chat = await event.get_chat()
            author_name = None
            author_username = None
            author_id = None
            if isinstance(sender, User):
                author_id = sender.id
                author_username = sender.username
                author_name = " ".join(
                    x for x in (sender.first_name, sender.last_name) if x
                ) or None

            posted_at = event.message.date
            if posted_at and posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)

            async with SessionLocal() as session:
                stmt = (
                    pg_insert(RawMessage)
                    .values(
                        source_id=source_id,
                        tg_chat_id=chat_id,
                        tg_message_id=event.message.id,
                        chat_title=(getattr(chat, "title", None) or "")[:256] or None,
                        author_id=author_id,
                        author_username=author_username,
                        author_name=(author_name or "")[:256] or None,
                        text=text[:MAX_TEXT_LEN],
                        link=self._build_link(chat, event.message.id),
                        matched=hits,
                        posted_at=posted_at,
                    )
                    .on_conflict_do_nothing(constraint="uq_raw_chat_message")
                )
                await session.execute(stmt)
                await session.commit()

            log.info(
                "поймал: %s | %s | %s",
                (getattr(chat, "title", "?") or "?")[:30],
                ", ".join(hits[:3]),
                text[:70].replace("\n", " "),
            )
        except Exception:
            log.exception("ошибка обработки сообщения")

    # ---------------------------------------------------------------- loops

    async def refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(SOURCES_REFRESH_SEC)
            with contextlib.suppress(Exception):
                await self.load_sources()
                await matcher.refresh(force=True)

    async def dialog_loop(self) -> None:
        while True:
            await asyncio.sleep(DIALOG_SYNC_SEC)
            with contextlib.suppress(Exception):
                await self.sync_dialogs()

    async def run(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            log.error(
                "Сессия юзербота не создана. Выполни один раз:\n"
                "    docker compose run --rm collector python -m app.scripts.login"
            )
            raise SystemExit(1)

        me = await self.client.get_me()
        self.me_id = me.id
        log.info("юзербот запущен как @%s (id=%s)", me.username, me.id)

        await matcher.refresh(force=True)
        await self.sync_dialogs()

        self.client.add_event_handler(self.handle, events.NewMessage(incoming=True))

        asyncio.create_task(self.refresh_loop())
        asyncio.create_task(self.dialog_loop())

        await self.client.run_until_disconnected()


def main() -> None:
    asyncio.run(Collector().run())


if __name__ == "__main__":
    main()
