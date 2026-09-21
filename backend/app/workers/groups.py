"""Сбор лидов из групп через собственного бота.

Зачем: в каналах лежит перепечатка бирж — контакт там один на весь канал
(админ), написать человеку нельзя. Живые заказчики сидят в чатах, а чаты
веб-версией не отдаются: проверено, `t.me/s/<группа>` возвращает ноль постов.

Юзербот читал бы чаты, но для него нужен api_id с my.telegram.org, который
недоступен. Остаётся Bot API: бот, добавленный в группу, с выключенным
privacy-режимом видит все сообщения. И главное — у автора сообщения есть
настоящий @username, то есть лид получается писабельным.

Ограничение: бота в чужой чат может добавить только тот, кому это позволено
настройками группы. Поэтому источник работает для чатов, куда владелец имеет
доступ, а не для любого публичного чата.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal
from app.logging_conf import setup_logging
from app.models import RawMessage, Source
from app.services.matcher import matcher

log = setup_logging("groups")

router = Router(name="groups")

GROUP_KIND = "tg_group"
MIN_TEXT_LEN = 15
MAX_TEXT_LEN = 8000


async def register_group(chat_id: int, title: str | None, username: str | None) -> None:
    async with SessionLocal() as session:
        await session.execute(
            pg_insert(Source)
            .values(
                kind=GROUP_KIND,
                tg_chat_id=chat_id,
                title=(title or str(chat_id))[:256],
                username=username,
                enabled=True,
            )
            .on_conflict_do_update(
                index_elements=[Source.tg_chat_id],
                set_={"title": (title or str(chat_id))[:256], "enabled": True},
            )
        )
        await session.commit()


@router.my_chat_member()
async def on_membership_change(event: ChatMemberUpdated) -> None:
    """Бота добавили в группу или убрали из неё."""
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    status = event.new_chat_member.status

    if status in ("member", "administrator"):
        await register_group(chat.id, chat.title, chat.username)
        log.info("бот добавлен в группу %s (%s)", chat.title, chat.id)

        if settings.admin_id_list:
            try:
                await event.bot.send_message(
                    settings.admin_id_list[0],
                    f"Слушаю чат «{chat.title}».\n\n"
                    "Если сообщения из него не появятся — у бота включён "
                    "privacy-режим. Выключается в @BotFather: /mybots → бот → "
                    "Bot Settings → Group Privacy → Turn off.",
                )
            except Exception as exc:
                log.warning("не смог сообщить о новой группе: %s", exc)

    elif status in ("left", "kicked"):
        async with SessionLocal() as session:
            source = (
                await session.execute(
                    select(Source).where(
                        Source.tg_chat_id == chat.id, Source.kind == GROUP_KIND
                    )
                )
            ).scalar_one_or_none()
            if source is not None:
                source.enabled = False
                await session.commit()
        log.info("бота убрали из группы %s", chat.id)


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message) -> None:
    """Каждое сообщение чата: прогоняем через тот же фильтр, что и каналы."""
    text = (message.text or message.caption or "").strip()
    if len(text) < MIN_TEXT_LEN:
        return

    author = message.from_user
    if author is None or author.is_bot:
        return
    # свои же сообщения в лиды не превращаем
    if author.id in settings.admin_id_list:
        return

    try:
        if await matcher.stop_hit(text):
            return
        hits = await matcher.match(text)
        if not hits:
            return

        async with SessionLocal() as session:
            source = (
                await session.execute(
                    select(Source).where(
                        Source.tg_chat_id == message.chat.id,
                        Source.kind == GROUP_KIND,
                        Source.enabled.is_(True),
                    )
                )
            ).scalar_one_or_none()

            if source is None:
                # бота добавили до запуска радара — регистрируем на лету
                await register_group(message.chat.id, message.chat.title, message.chat.username)
                source = (
                    await session.execute(
                        select(Source).where(Source.tg_chat_id == message.chat.id)
                    )
                ).scalar_one()

            link = None
            if message.chat.username:
                link = f"https://t.me/{message.chat.username}/{message.message_id}"
            else:
                internal = str(message.chat.id).replace("-100", "", 1)
                link = f"https://t.me/c/{internal}/{message.message_id}"

            await session.execute(
                pg_insert(RawMessage)
                .values(
                    source_id=source.id,
                    tg_chat_id=message.chat.id,
                    tg_message_id=message.message_id,
                    chat_title=(message.chat.title or "")[:256] or None,
                    author_id=author.id,
                    # вот ради чего всё: у сообщения из чата есть живой контакт
                    author_username=author.username,
                    contact_url=(
                        f"https://t.me/{author.username}" if author.username else None
                    ),
                    author_name=" ".join(
                        x for x in (author.first_name, author.last_name) if x
                    )[:256] or None,
                    text=text[:MAX_TEXT_LEN],
                    link=link,
                    matched=hits,
                    posted_at=message.date,
                )
                .on_conflict_do_nothing(constraint="uq_raw_chat_message")
            )
            await session.commit()

        log.info(
            "поймал в чате %s: @%s | %s",
            message.chat.title,
            author.username or author.id,
            text[:60].replace("\n", " "),
        )
    except Exception:
        log.exception("ошибка обработки сообщения из группы")
