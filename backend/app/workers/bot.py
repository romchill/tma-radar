"""Бот: точка входа в мини-апп + напоминалка по отложенным лидам.

Пушами о горячих лидах занимается скорер (app/services/notify.py),
здесь — команды и фолоуапы.
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
import aiohttp
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal
from app.logging_conf import setup_logging
from app.models import Lead, LeadEvent, LeadStatus, RawMessage, RawStatus, Source
from app.services import notify, tgweb
from app.workers import channels, groups
from app.workers import pulse
from app.services.settings_store import get_setting, set_setting

log = setup_logging("bot")

dp = Dispatcher()
# сколько ждать, если цикл так и не случился (новых постов не было)
FOLLOWUP_INTERVAL_SEC = settings.followup_interval_sec


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_id_list)


async def webapp_base() -> str | None:
    """Текущий публичный адрес мини-аппа. Лежит в БД, а не в .env:
    бесплатный туннель выдаёт новый адрес примерно раз в час."""
    async with SessionLocal() as session:
        return await get_setting(session, "webapp_url", "")


def app_button(base: str | None) -> InlineKeyboardMarkup | None:
    """Inline-кнопка запуска мини-аппа.

    Ссылку на адрес в текст класть нельзя: по обычной ссылке Telegram открывает
    встроенный браузер, а не мини-апп, и приложение остаётся без подписи входа
    (initData пустой). Открывать можно только кнопкой с web_app.
    """
    url = notify.webapp_url(base)
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📡 Открыть радар", web_app=WebAppInfo(url=url))]
        ]
    )


def main_keyboard(base: str | None) -> ReplyKeyboardMarkup | None:
    url = notify.webapp_url(base)
    if not url:
        return None
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📡 Радар", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
    )


async def apply_menu_button(base: str | None) -> None:
    url = notify.webapp_url(base)
    if not url:
        return
    for admin_id in settings.admin_id_list:
        try:
            await notify.bot().set_chat_menu_button(
                chat_id=admin_id,
                menu_button=MenuButtonWebApp(text="Радар", web_app=WebAppInfo(url=url)),
            )
        except Exception as exc:
            log.warning("не выставил menu button для %s: %s", admin_id, exc)


@dp.message(CommandStart())
async def start(message: Message) -> None:
    if not is_admin(message):
        return

    base = await webapp_base()
    keyboard = main_keyboard(base)
    # До первого /start Telegram не даёт выставить кнопку меню («user not found»),
    # поэтому ставим её здесь, а не только на старте воркера.
    await apply_menu_button(base)
    lines = [
        "Радар на связи.",
        "",
        "Горячие лиды прилетают сюда сами.",
        "/stats — сводка, /queue — состояние очереди.",
    ]
    if keyboard is None:
        lines += [
            "",
            "Приложение пока некуда открывать: публичного адреса нет.",
            "Подними туннель и пришли адрес командой:",
            "/url https://что-то.lhr.life",
        ]
    await message.answer("\n".join(lines), reply_markup=keyboard)

    launcher = app_button(base)
    if launcher is not None:
        await message.answer(
            "Открывать приложение нужно этой кнопкой: по обычной ссылке Telegram "
            "запускает встроенный браузер и не передаёт подпись входа.",
            reply_markup=launcher,
        )


@dp.message(Command("url"))
async def set_url(message: Message, command: CommandObject) -> None:
    """Запоминает адрес туннеля — чтобы не править .env и не перезапускать контейнер."""
    if not is_admin(message):
        return

    raw = (command.args or "").strip()
    if not raw:
        current = await webapp_base()
        await message.answer(
            f"Сейчас адрес: {current}"
            if current
            else "Адрес не задан.\n/url https://...pinggy.link"
        )
        return

    normalized = notify.normalize_base(raw)
    if normalized is None:
        await message.answer("Адрес должен начинаться с https:// — другие Telegram не открывает.")
        return

    async with SessionLocal() as session:
        await set_setting(session, "webapp_url", normalized)
        await session.commit()

    await apply_menu_button(normalized)
    await message.answer("Адрес сохранён.", reply_markup=app_button(normalized))


CHANNEL_RE = re.compile(r"(?:https?://)?(?:t\.me/|@)?([A-Za-z][A-Za-z0-9_]{4,31})/?$")


@dp.message(Command("add"))
async def add_channel(message: Message, command: CommandObject) -> None:
    """Добавляет публичный канал в сбор, сразу проверяя, что он читается."""
    if not is_admin(message):
        return

    raw = (command.args or "").strip()
    match = CHANNEL_RE.match(raw)
    if not match:
        await message.answer(
            "Пришли адрес канала: /add @название или /add https://t.me/название"
        )
        return

    username = match.group(1)
    await message.answer(f"Проверяю @{username}…")

    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as http:
        posts = await tgweb.fetch_channel(http, username)

    if not posts:
        await message.answer(
            f"@{username} прочитать не получилось.\n\n"
            "Так бывает, если это группа, а не канал, если канал закрытый "
            "или если в названии опечатка. Открой https://t.me/s/"
            f"{username} в браузере — если там пусто, читать нечего."
        )
        return

    async with SessionLocal() as session:
        await session.execute(
            pg_insert(Source)
            .values(
                kind=channels.CHANNEL_KIND,
                username=username,
                title=username,
                tg_chat_id=tgweb.channel_chat_id(username),
                url=f"https://t.me/{username}",
                enabled=True,
            )
            .on_conflict_do_update(
                index_elements=[Source.tg_chat_id],
                set_={"enabled": True, "username": username},
            )
        )
        await session.commit()

    await message.answer(
        f"@{username} добавлен, видно {len(posts)} последних постов.\n"
        "Радар проверяет каналы раз в 5 минут."
    )


@dp.message(Command("list"))
async def list_channels(message: Message) -> None:
    if not is_admin(message):
        return

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Source.username, Source.enabled, func.count(Lead.id))
                .outerjoin(RawMessage, RawMessage.source_id == Source.id)
                .outerjoin(Lead, Lead.raw_message_id == RawMessage.id)
                .where(Source.kind == channels.CHANNEL_KIND)
                .group_by(Source.username, Source.enabled)
                .order_by(func.count(Lead.id).desc())
            )
        ).all()

    if not rows:
        await message.answer("Каналов пока нет. Добавь: /add @название_канала")
        return

    lines = ["<b>Каналы</b>"]
    for username, enabled, leads in rows:
        mark = "" if enabled else " (выключен)"
        lines.append(f"@{username} — лидов: {leads}{mark}")
    lines.append("\nУбрать: /del @название")
    await message.answer("\n".join(lines))


@dp.message(Command("del"))
async def del_channel(message: Message, command: CommandObject) -> None:
    if not is_admin(message):
        return

    match = CHANNEL_RE.match((command.args or "").strip())
    if not match:
        await message.answer("Пришли так: /del @название_канала")
        return

    username = match.group(1)
    async with SessionLocal() as session:
        result = await session.execute(
            delete(Source).where(
                Source.kind == channels.CHANNEL_KIND, Source.username == username
            )
        )
        await session.commit()

    await message.answer(
        f"@{username} убран из сбора." if result.rowcount else f"@{username} и не был добавлен."
    )


@dp.message(Command("stats"))
async def stats(message: Message) -> None:
    if not is_admin(message):
        return
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Lead.status, func.count()).group_by(Lead.status))
        ).all()
        avg = await session.scalar(
            select(func.avg(Lead.score)).where(Lead.status != LeadStatus.TRASH)
        )

    counts = dict(rows)
    lines = ["<b>Воронка</b>"]
    titles = {
        LeadStatus.NEW: "новые",
        LeadStatus.CONTACTED: "написал",
        LeadStatus.DIALOG: "диалог",
        LeadStatus.OFFER: "оффер",
        LeadStatus.DEAL: "сделка",
        LeadStatus.LOST: "слив",
        LeadStatus.TRASH: "мусор",
    }
    for status, title in titles.items():
        lines.append(f"{title}: <b>{counts.get(status, 0)}</b>")
    lines.append(f"\nсредний score: <b>{round(float(avg or 0), 1)}</b>")
    await message.answer("\n".join(lines))


@dp.message(Command("queue"))
async def queue(message: Message) -> None:
    if not is_admin(message):
        return
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(RawMessage.status, func.count()).group_by(RawMessage.status)
            )
        ).all()
    counts = dict(rows)
    await message.answer(
        "<b>Очередь</b>\n"
        f"ждут скоринга: <b>{counts.get(RawStatus.PENDING, 0)}</b>\n"
        f"в работе: <b>{counts.get(RawStatus.PROCESSING, 0)}</b>\n"
        f"оценено: <b>{counts.get(RawStatus.SCORED, 0)}</b>\n"
        f"отсеяно: <b>{counts.get(RawStatus.REJECTED, 0)}</b>\n"
        f"дубли: <b>{counts.get(RawStatus.DUPLICATE, 0)}</b>\n"
        f"ошибки: <b>{counts.get(RawStatus.ERROR, 0)}</b>"
    )


@dp.message(F.web_app_data)
async def from_webapp(message: Message) -> None:
    """Мини-апп может слать сюда данные через Telegram.WebApp.sendData."""
    if not is_admin(message):
        return
    log.info("данные из мини-аппа: %s", message.web_app_data.data[:200])


async def followup_loop() -> None:
    """Напоминает о лидах, у которых наступил срок.

    Ходит в базу не по своему таймеру, а следом за циклом сбора и оценки:
    бесплатная база засыпает после 5 минут покоя, и каждый лишний заход
    в стороне от общего окна стоит ещё пяти минут её работы.
    """
    while True:
        await pulse.wait_cycle(FOLLOWUP_INTERVAL_SEC)
        try:
            base = await webapp_base()
            async with SessionLocal() as session:
                due = (
                    (
                        await session.execute(
                            select(Lead).where(
                                Lead.next_followup_at.is_not(None),
                                Lead.next_followup_at <= utcnow(),
                                Lead.status.in_(LeadStatus.PIPELINE),
                            )
                        )
                    )
                    .unique()
                    .scalars()
                    .all()
                )

                for lead in due:
                    who = lead.raw.author_username or lead.raw.author_name or "контакт"
                    await notify.bot().send_message(
                        settings.admin_id_list[0],
                        f"⏰ Пора вернуться к лиду #{lead.id} — {html.escape(who)}\n"
                        f"{html.escape(lead.summary or '')[:200]}",
                        reply_markup=notify.lead_keyboard(
                            lead.id, lead.raw.author_username, lead.raw.link, base,
                            contact_url=lead.raw.contact_url,
                        ),
                    )
                    lead.next_followup_at = None
                    session.add(LeadEvent(lead_id=lead.id, kind="followup_fired"))

                if due:
                    await session.commit()
        except Exception:
            log.exception("сбой напоминалки")


TUNNEL_URL_FILE = Path("/shared/tunnel_url")
TUNNEL_WATCH_SEC = 20


async def tunnel_url_loop() -> None:
    """Следит за адресом, который пишет контейнер туннеля.

    У бесплатного туннеля адрес новый при каждом переподключении. Без этого
    цикла пришлось бы каждый раз лезть в логи и слать боту /url руками.

    На хостинге адрес постоянный и задан через DOMAIN — там следить не за чем,
    и перезаписывать его найденным где-то файлом туннеля нельзя.
    """
    if settings.domain and settings.domain != "localhost":
        log.info("адрес постоянный (%s) — слежение за туннелем не нужно", settings.domain)
        return

    last: str | None = None

    while True:
        try:
            if TUNNEL_URL_FILE.exists():
                url = TUNNEL_URL_FILE.read_text(encoding="utf-8").strip()
                normalized = notify.normalize_base(url)

                if normalized and normalized != last:
                    stored = await webapp_base()
                    if normalized != stored:
                        async with SessionLocal() as session:
                            await set_setting(session, "webapp_url", normalized)
                            await session.commit()
                        # Обновляем молча. Бесплатный туннель меняет адрес каждые
                        # 7-10 минут, и сообщение на каждую смену — это десятки
                        # уведомлений за ночь. Кнопка меню рядом с полем ввода
                        # всегда указывает на свежий адрес, этого достаточно.
                        await apply_menu_button(normalized)
                        log.info("адрес мини-аппа обновлён: %s", normalized)
                    last = normalized
        except Exception:
            log.exception("сбой слежения за адресом туннеля")

        await asyncio.sleep(TUNNEL_WATCH_SEC)


async def run() -> None:
    # хендлеры групп живут отдельным роутером: там своя логика и свои риски
    dp.include_router(groups.router)

    if not settings.bot_token:
        log.error("BOT_TOKEN не задан")
        raise SystemExit(1)

    bot = notify.bot()

    await apply_menu_button(await webapp_base())

    asyncio.create_task(followup_loop())
    asyncio.create_task(tunnel_url_loop())
    log.info("бот запущен, админы: %s", settings.admin_id_list)
    await dp.start_polling(bot)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
