"""Ссылка на сам заказ, а не на пост о нём.

Каналы вроде @freelance_zakazy и @it_zakazy — перепечатка бирж, и в разметке
поста лежит настоящая ссылка на заказ. Текстовый парсер её терял: он срезает
теги вместе с адресами, и в карточке оставалась только ссылка на пост канала.
Владельцу приходилось открывать пост, а оттуда идти на биржу.

Заодно снимаем реферальный хвост. У @freelance_zakazy каждая ссылка идёт с
`?ref=15678240` — это партнёрский код владельца канала, и переход по нему
записывает владельца радара на чужую партнёрку.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Биржи, где ссылка ведёт на страницу конкретного заказа. Адрес на главную
# страницу биржи бесполезен, поэтому нужен путь с номером заказа.
ORDER_URL = re.compile(
    r"https?://(?:www\.)?("
    r"kwork\.ru/projects/\d+"
    r"|fl\.ru/projects/\d+"
    r"|freelance\.ru/projects/\d+"
    r"|weblancer\.net/projects/[\w-]+"
    r"|u\.habr\.com/\w+"
    r")[^\s\"'<>]*",
    re.IGNORECASE,
)

# Партнёрские и рекламные хвосты: к самому заказу отношения не имеют.
TRACKING = {"ref", "referer", "referrer", "from", "utm_source", "utm_medium",
            "utm_campaign", "utm_term", "utm_content", "yclid", "gclid", "fbclid"}


def strip_tracking(url: str) -> str:
    """Убирает партнёрские метки, остальные параметры оставляет как есть."""
    scheme, netloc, path, query, fragment = urlsplit(url)
    if not query:
        return url
    kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
            if k.lower() not in TRACKING]
    return urlunsplit((scheme, netloc, path, urlencode(kept), fragment))


def find(*sources: str | None) -> str | None:
    """Первая ссылка на заказ из переданных кусков текста или разметки."""
    for source in sources:
        if not source:
            continue
        match = ORDER_URL.search(source)
        if match:
            return strip_tracking(match.group(0))
    return None


def shop_name(url: str | None) -> str | None:
    """Как называется место, куда ведёт ссылка — для подписи кнопки."""
    if not url:
        return None
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    known = {
        "kwork.ru": "Kwork",
        "fl.ru": "FL.ru",
        "freelance.ru": "Freelance.ru",
        "weblancer.net": "Weblancer",
        "u.habr.com": "Хабр Фриланс",
    }
    if host in known:
        return known[host]
    if host.endswith("t.me"):
        return None  # ссылка на пост, а не на заказ
    return host or None
