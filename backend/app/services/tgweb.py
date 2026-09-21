"""Чтение публичных телеграм-каналов без аккаунта.

Telegram отдаёт содержимое любого публичного канала обычной веб-страницей
по адресу `https://t.me/s/<username>`. Ни ключей, ни номера, ни входа —
поэтому это единственный способ собирать лиды, когда my.telegram.org
недоступен и юзербота завести нельзя.

Чего так не получить: закрытые каналы и любые группы — у групп веб-превью нет.

Парсим регулярками, а не html-библиотекой: разметка виджета простая и
стабильная, а лишняя зависимость на слабой машине не нужна.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime

import aiohttp

log = logging.getLogger(__name__)

BASE = "https://t.me/s/"
USER_AGENT = "Mozilla/5.0 (compatible; tma-radar/0.1)"
TIMEOUT = aiohttp.ClientTimeout(total=25)

# один блок сообщения целиком — из него уже тянем id, дату и текст
_MESSAGE = re.compile(
    r'<div class="tgme_widget_message[^"]*"[^>]*data-post="(?P<post>[^"]+)"(?P<body>.*?)'
    r'(?=<div class="tgme_widget_message[^"]*"[^>]*data-post=|</main>)',
    re.S,
)
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(?P<html>.*?)</div>', re.S)
_DATETIME = re.compile(r'<time[^>]+datetime="(?P<dt>[^"]+)"')
_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)
_USERNAME = re.compile(r"@([A-Za-z][A-Za-z0-9_]{4,31})")
_TME_LINK = re.compile(r"t\.me/(?!s/|joinchat|\+)([A-Za-z][A-Za-z0-9_]{4,31})")

# Слова, рядом с которыми ссылка t.me действительно похожа на контакт.
# Отрицательный просмотр назад обязателен: без него «подПИШись на канал»
# считается приглашением написать, и холодное предложение уходит не туда.
_CONTACT_HINT = re.compile(
    r"(?<![А-Яа-яЁёA-Za-z])"
    r"(пиш|напиш|связ|контакт|обращ|отклик|резюме|вопрос|заявк|лс\b|личк|дм\b|dm\b)",
    re.I,
)

# то, что выглядит как контакт, но контактом не является
_NOT_CONTACT = {
    "telegram", "durov", "telegramtips", "bot", "botfather", "channel",
    "contest", "share", "joinchat", "addstickers", "proxy", "socks", "iv",
}


@dataclass
class ChannelPost:
    channel: str
    post_id: int
    text: str
    link: str
    posted_at: datetime | None
    contact: str | None  # @username, вытащенный из текста


def channel_chat_id(username: str) -> int:
    """Стабильный синтетический id канала.

    Настоящие id у Telegram: пользователи — положительные и меньше 10^11,
    группы и каналы — отрицательные. Берём заведомо свободный диапазон
    выше 9*10^14, чтобы не столкнуться с настоящими, если однажды
    подключится юзербот.
    """
    digest = hashlib.sha1(username.lower().encode()).hexdigest()[:12]
    return 9 * 10**14 + int(digest, 16) % 10**11


def _clean_text(raw_html: str) -> str:
    text = _BR.sub("\n", raw_html)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    # виджет любит неразрывные пробелы
    text = text.replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_contact(text: str, raw_html: str, channel: str) -> str | None:
    """Ищет, кому писать. У поста в канале нет автора, поэтому контакт
    берётся из самого текста: «пишите @ivan».

    Ссылка t.me/xxx засчитывается только рядом со словом про связь: в посте
    полно ссылок на другие каналы, и принять такую за контакт — значит
    отправить холодное предложение постороннему человеку.
    """

    def usable(name: str) -> bool:
        low = name.lower()
        return low not in _NOT_CONTACT and low != channel.lower()

    for name in _USERNAME.findall(text):
        if usable(name):
            return name

    for match in _TME_LINK.finditer(raw_html):
        name = match.group(1)
        if not usable(name):
            continue
        around = raw_html[max(0, match.start() - 80) : match.end() + 80].lower()
        if _CONTACT_HINT.search(around):
            return name

    return None


def parse_channel(page: str, channel: str) -> list[ChannelPost]:
    posts: list[ChannelPost] = []

    for match in _MESSAGE.finditer(page):
        post_ref = match.group("post")  # вида "channel/441"
        body = match.group("body")

        text_match = _TEXT.search(body)
        if text_match is None:
            continue  # пост без текста (картинка, опрос) — скорить нечего

        raw_html = text_match.group("html")
        text = _clean_text(raw_html)
        if not text:
            continue

        try:
            post_id = int(post_ref.rsplit("/", 1)[1])
        except (IndexError, ValueError):
            continue

        posted_at = None
        dt_match = _DATETIME.search(body)
        if dt_match:
            try:
                posted_at = datetime.fromisoformat(dt_match.group("dt"))
            except ValueError:
                pass

        posts.append(
            ChannelPost(
                channel=channel,
                post_id=post_id,
                text=text,
                link=f"https://t.me/{post_ref}",
                posted_at=posted_at,
                contact=extract_contact(text, raw_html, channel),
            )
        )

    return posts


# Строка дайджеста: «1. Разработать телеграм бота Quiz (цена договорная) https://…»
_DIGEST_ITEM = re.compile(
    r"^\s*(\d{1,2})[.)]\s+(.{10,400}?)\s*(https?://\S+)\s*$",
    re.MULTILINE,
)
MIN_DIGEST_ITEMS = 2


def split_digest(post: ChannelPost) -> list[ChannelPost]:
    """Разбивает пост-подборку на отдельные заказы.

    Биржевые каналы публикуют дайджесты: один пост — пять заказов, у каждого
    своя цена и своя ссылка. Как один лид это почти бесполезно: в карточке
    мешанина, черновик пишется только по первому пункту, а заказ на 300 000 ₽
    теряется среди мелочи. Разбитые пункты проходят фильтр по отдельности,
    поэтому нерелевантные (сайты, дизайн) отсеиваются сами.
    """
    items = _DIGEST_ITEM.findall(post.text)
    if len(items) < MIN_DIGEST_ITEMS:
        return [post]

    out: list[ChannelPost] = []
    for number, title, url in items:
        out.append(
            replace(
                post,
                # номер пункта в id, чтобы уникальность сообщения не ломалась
                post_id=post.post_id * 1000 + int(number),
                text=title.strip(),
                # ссылка на сам заказ полезнее ссылки на подборку
                link=url,
                contact=extract_contact(title, title, post.channel),
            )
        )
    return out


async def fetch_channel(session: aiohttp.ClientSession, channel: str) -> list[ChannelPost]:
    """Забирает последние посты канала. Пустой список — канал закрыт,
    не существует или это группа (у групп веб-превью нет)."""
    url = f"{BASE}{channel.lstrip('@')}"
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as response:
            if response.status != 200:
                log.warning("канал %s: http %s", channel, response.status)
                return []
            page = await response.text()
    except Exception as exc:
        log.warning("канал %s недоступен: %s", channel, exc)
        return []

    posts = parse_channel(page, channel.lstrip("@"))

    expanded: list[ChannelPost] = []
    for post in posts:
        expanded.extend(split_digest(post))
    posts = expanded

    if not posts:
        log.warning(
            "канал %s: постов не найдено — возможно, это группа или закрытый канал", channel
        )
    return posts
