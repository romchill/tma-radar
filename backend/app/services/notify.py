"""Пуши в телеграм. Используется скорером и напоминалкой.

Адрес мини-аппа сюда передаётся снаружи, а не берётся из .env: домена нет,
бесплатный туннель выдаёт новый адрес примерно раз в час, и переписывать
ради этого .env с перезапуском контейнера — плохой ритуал. Адрес лежит в
app_settings и меняется командой /url в боте.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import settings
from app.services import orderlink

log = logging.getLogger(__name__)

_bot: Bot | None = None

URGENCY_MARK = {"high": "🔥", "medium": "⚡", "low": "•"}


def bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


def normalize_base(base: str | None) -> str | None:
    """Telegram открывает мини-апп только по https. Всё остальное — не адрес."""
    if not base:
        # запасной вариант: домен из .env, если он вообще задан
        if settings.domain and settings.domain != "localhost":
            base = f"https://{settings.domain}"
        else:
            return None
    base = base.strip().rstrip("/")
    return base if base.startswith("https://") else None


def webapp_url(base: str | None, lead_id: int | None = None) -> str | None:
    root = normalize_base(base)
    if root is None:
        return None
    return f"{root}/?startapp=lead_{lead_id}" if lead_id else f"{root}/"


def lead_keyboard(
    lead_id: int,
    username: str | None,
    link: str | None,
    base: str | None = None,
    contact_url: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    url = webapp_url(base, lead_id)
    if url:
        rows.append(
            [InlineKeyboardButton(text="Открыть карточку", web_app=WebAppInfo(url=url))]
        )

    second: list[InlineKeyboardButton] = []
    if contact_url:
        second.append(InlineKeyboardButton(text="✍️ Написать", url=contact_url))
    elif username:
        second.append(InlineKeyboardButton(text="✍️ Написать", url=f"https://t.me/{username}"))
    if link:
        # Подписываем кнопку местом назначения: «Открыть на Kwork» сразу
        # говорит, куда ведёт и где откликаться, а «Открыть заказ» — нет.
        shop = orderlink.shop_name(link)
        if shop:
            label = f"Открыть на {shop}"
        else:
            label = "Открыть заказ" if not (contact_url or username) else "Источник"
        second.append(InlineKeyboardButton(text=label, url=link))
    if second:
        rows.append(second)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def posted_ago(posted_at) -> str | None:
    """Сколько заказу времени. При окне в 12 часов это главный факт в карточке."""
    if posted_at is None:
        return None
    minutes = int((datetime.now(timezone.utc) - posted_at).total_seconds() // 60)
    if minutes < 1:
        return "только что"
    if minutes < 60:
        return f"{minutes} мин назад"
    return f"{minutes // 60} ч назад"


def render_lead(lead, raw, hot: bool = False) -> str:
    who = raw.author_name or (f"@{raw.author_username}" if raw.author_username else "аноним")
    head = "🔥 <b>Горячий лид" if hot else "📨 <b>Новый заказ"
    lines = [
        f"{head} {lead.score}/100</b>",
        "",
        html.escape((lead.summary or raw.text)[:400]),
    ]

    facts = []
    if lead.budget_hint:
        facts.append(f"💰 {html.escape(lead.budget_hint)}")
    age = posted_ago(getattr(raw, "posted_at", None))
    if age:
        facts.append(f"🕒 {age}")
    if facts:
        lines.append("\n" + "  ".join(facts))

    # У бирж «автор» и «источник» — одно и то же: повторять незачем.
    source = raw.chat_title or "?"
    origin = who if who == source else f"{who} · {source}"
    lines.append(f"\n<i>{html.escape(origin)}</i>")

    # Ссылку показываем текстом, а не только кнопкой: её видно сразу, можно
    # скопировать и переслать, и понятно, куда идти откликаться.
    link = getattr(raw, "link", None)
    if link:
        shop = orderlink.shop_name(link)
        title = f"Открыть на {shop}" if shop else "Открыть заказ"
        lines.append(f'🔗 <a href="{html.escape(link, quote=True)}">{title}</a>')

    if not getattr(raw, "contact_url", None):
        lines.append("<i>прямого контакта нет — откликаться там же</i>")

    lines.append(f"\n<blockquote expandable>{html.escape(raw.text[:900])}</blockquote>")
    return "\n".join(lines)


async def notify_text(text: str) -> bool:
    """Служебное сообщение админам (например, что лимит на сегодня исчерпан)."""
    if not settings.bot_token or not settings.admin_id_list:
        return False

    delivered = False
    for admin_id in settings.admin_id_list:
        try:
            await bot().send_message(admin_id, text, disable_web_page_preview=True)
            delivered = True
        except Exception as exc:
            log.warning("не отправил сообщение админу %s: %s", admin_id, exc)
    return delivered


async def notify_lead(lead, raw, base: str | None = None, hot: bool = False) -> bool:
    """Шлёт карточку лида всем админам. Возвращает True, если кому-то дошло."""
    if not settings.bot_token or not settings.admin_id_list:
        return False

    text = render_lead(lead, raw, hot=hot)
    kb = lead_keyboard(
        lead.id, raw.author_username, raw.link, base,
        contact_url=getattr(raw, "contact_url", None),
    )
    delivered = False

    for admin_id in settings.admin_id_list:
        try:
            await bot().send_message(
                admin_id, text, reply_markup=kb, disable_web_page_preview=True
            )
            delivered = True
        except Exception as exc:
            log.warning("не отправил пуш админу %s: %s", admin_id, exc)

    return delivered


async def close() -> None:
    global _bot
    if _bot is not None:
        await _bot.session.close()
        _bot = None
