"""Чтение RSS-лент бирж заказов.

Каналы в телеграме, которыми радар пользовался до сих пор, — это перепечатка
бирж с задержкой и без половины полей. Биржа отдаёт то же самое сама, сразу
и с бюджетом: FL.ru держит открытый RSS на 60 последних заказов.

Разбор — на стандартной библиотеке, лишней зависимости ради RSS не нужно.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=25)

# Биржи закрываются от чужих сборщиков: без внятного User-Agent Weblancer
# и FreelanceHunt отвечают 403.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

TAGS = re.compile(r"<[^>]+>")
SPACES = re.compile(r"[ \t ]+")
BLANK_LINES = re.compile(r"\n{3,}")

# номер заказа из ссылки вида /projects/5522818/poisk-it-konsultanta.html
PROJECT_ID = re.compile(r"/(\d{4,})(?:[/_-]|\.html|$)")


@dataclass
class FeedItem:
    feed_url: str
    item_id: int
    title: str
    text: str
    link: str
    posted_at: datetime | None


def feed_chat_id(feed_url: str) -> int:
    """Стабильный синтетический id ленты.

    Тот же приём, что и у каналов: занимаем заведомо свободный диапазон,
    чтобы синтетические id не столкнулись с настоящими телеграмными.
    Диапазон соседний с каналами, но не пересекается с ними.
    """
    digest = hashlib.sha1(feed_url.lower().encode()).hexdigest()[:12]
    return 8 * 10**14 + int(digest, 16) % 10**11


def item_id(link: str, guid: str | None) -> int:
    """Номер заказа. Нужен стабильный: по нему работает защита от дублей."""
    match = PROJECT_ID.search(link or "")
    if match:
        return int(match.group(1))

    # у ленты без номера в ссылке берём хеш от guid или самой ссылки
    key = (guid or link or "").encode()
    return int(hashlib.sha1(key).hexdigest()[:10], 16) % 10**11


def clean_html(raw: str) -> str:
    """Описание в RSS приходит размеченным — оставляем один текст."""
    text = raw.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n").replace("</div>", "\n")
    text = TAGS.sub(" ", text)
    text = html.unescape(text)
    text = SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", text).strip()


def parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    # лента может отдать дату без зоны — считаем её UTC, иначе сравнение
    # со «свежестью» падает на naive/aware
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse(feed_url: str, body: str) -> list[FeedItem]:
    """Разбирает RSS. Кривая лента даёт пустой список, а не исключение."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []

    items: list[FeedItem] = []
    for node in root.iter("item"):
        link = (node.findtext("link") or "").strip()
        title = clean_html(node.findtext("title") or "")
        body_text = clean_html(node.findtext("description") or "")

        if not title and not body_text:
            continue

        # заголовок у биржи — это и есть суть заказа, он важнее описания
        text = f"{title}\n\n{body_text}".strip() if body_text else title

        items.append(
            FeedItem(
                feed_url=feed_url,
                item_id=item_id(link, node.findtext("guid")),
                title=title,
                text=text,
                link=link or feed_url,
                posted_at=parse_date(node.findtext("pubDate")),
            )
        )

    return items


async def fetch(session: aiohttp.ClientSession, feed_url: str) -> list[FeedItem]:
    async with session.get(feed_url, headers=HEADERS) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        # биржи отдают windows-1251 и не всегда объявляют это в заголовке
        body = await response.text(errors="replace")
    return parse(feed_url, body)
