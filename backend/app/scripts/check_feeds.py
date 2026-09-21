"""Проверка RSS-лент бирж: разбирается ли и что там вообще лежит.

Каналы в телеграме — перепечатка бирж с задержкой. Биржа отдаёт то же самое
сама и сразу, поэтому лента ценнее канала. Но лента полезна только если
разбирается целиком: заголовок, текст, ссылка на конкретный заказ и дата.
Без даты не работает окно свежести, без своей ссылки — дедупликация.

Запуск: python -m app.scripts.check_feeds [url ...]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

import aiohttp

from app.services import feeds
from app.services.matcher import matcher
from app.workers.scorer import parse_budget

FEEDS = [
    ("FL.ru", "https://www.fl.ru/rss/all.xml"),
    ("Weblancer", "https://www.weblancer.net/rss/projects/"),
    ("FreelanceHunt", "https://freelancehunt.com/rss/projects"),
]


def age(when) -> str:
    if when is None:
        return "нет даты"
    minutes = int((datetime.now(timezone.utc) - when).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} мин"
    if minutes < 60 * 48:
        return f"{minutes // 60} ч"
    return f"{minutes // 1440} дн"


async def check(http: aiohttp.ClientSession, name: str, url: str) -> bool:
    print(f"=== {name} ===")
    try:
        items = await feeds.fetch(http, url)
    except Exception as exc:
        print(f"  недоступна: {exc}\n")
        return False

    if not items:
        print("  разобрать не удалось или лента пуста\n")
        return False

    with_link = sum(1 for i in items if "/" in i.link and i.link != url)
    with_date = sum(1 for i in items if i.posted_at)
    unique_ids = len({i.item_id for i in items})
    newest = max((i.posted_at for i in items if i.posted_at), default=None)

    print(f"  заказов: {len(items)}")
    print(f"  у каждого своя ссылка: {with_link}/{len(items)}")
    print(f"  с датой: {with_date}/{len(items)}")
    print(f"  уникальных номеров: {unique_ids}/{len(items)}")
    print(f"  свежесть: {age(newest)}")

    ours = []
    for item in items:
        if await matcher.stop_hit(item.text):
            continue
        if await matcher.match(item.text):
            ours.append(item)

    print(f"  подходит под нашу нишу: {len(ours)}")
    for item in ours[:5]:
        budget, bonus = parse_budget(item.text)
        money = f"  {budget} (+{bonus})" if budget else ""
        print(f"     [{age(item.posted_at)}] {item.title[:62]}{money}")
        print(f"        {item.link}")

    ok = with_link == len(items) and with_date == len(items) and unique_ids == len(items)
    print(f"  {'[ok] лента пригодна' if ok else '[FAIL] лента разобралась не полностью'}\n")
    return ok


async def main() -> None:
    await matcher.refresh()

    pairs = [(u, u) for u in sys.argv[1:]] or FEEDS
    usable = 0
    async with aiohttp.ClientSession(timeout=feeds.TIMEOUT) as http:
        for name, url in pairs:
            if await check(http, name, url):
                usable += 1

    print(f"пригодных лент: {usable} из {len(pairs)}")


if __name__ == "__main__":
    asyncio.run(main())
