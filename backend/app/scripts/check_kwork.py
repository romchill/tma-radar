"""Проверка разбора биржи Kwork и выбор категории для сбора.

Официального API у биржи нет: данные вытаскиваются из JSON, вшитого в
страницу. Значит проверять надо не «пришло что-то» и не «двести байт», а то,
что нужно радару: у каждого заказа своя ссылка, свой номер, дата и бюджет.
Без даты не работает окно свежести, без номера — защита от дублей.

Заодно сравниваем категории: если узкая целиком лежит внутри широкой, качать
обе бессмысленно.

Запуск: python -m app.scripts.check_kwork [категория ...]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

import aiohttp

from app.services import kwork
from app.services.matcher import matcher
from app.workers.scorer import parse_budget

CATEGORIES = ["11", "41"]


def age(when) -> str:
    if when is None:
        return "нет даты"
    minutes = int((datetime.now(timezone.utc) - when).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} мин"
    if minutes < 60 * 48:
        return f"{minutes // 60} ч"
    return f"{minutes // 1440} дн"


async def check(http: aiohttp.ClientSession, category: str) -> tuple[set[int], int]:
    print(f"=== категория c={category} ===")
    projects = await kwork.fetch_category(http, category)

    if not projects:
        print("  пусто — вероятно, биржа сменила разметку\n")
        return set(), 0

    with_link = sum(1 for p in projects if p.link.rstrip("/").split("/")[-1].isdigit())
    with_date = sum(1 for p in projects if p.posted_at)
    with_budget = sum(1 for p in projects if p.budget)
    newest = max((p.posted_at for p in projects if p.posted_at), default=None)

    print(f"  заказов: {len(projects)}")
    print(f"  у каждого своя ссылка: {with_link}/{len(projects)}")
    print(f"  с датой: {with_date}/{len(projects)}")
    print(f"  с бюджетом: {with_budget}/{len(projects)}")
    print(f"  свежайший: {age(newest)}")

    ours = []
    for project in projects:
        if await matcher.stop_hit(project.text):
            continue
        if await matcher.match(project.text):
            ours.append(project)

    print(f"  подходит под нашу нишу: {len(ours)}")
    for project in sorted(ours, key=lambda p: p.posted_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:6]:
        parsed, bonus = parse_budget(project.text)
        money = f"   {parsed} (+{bonus} к баллу)" if parsed else "   бюджет не распознан"
        print(f"     [{age(project.posted_at)}] {project.title[:58]}")
        print(f"        {project.link}{money}")

    ok = with_link == len(projects) and with_date == len(projects)
    print(f"  {'[ok] пригодна' if ok else '[FAIL] разобралась не полностью'}\n")
    return {p.id for p in projects}, len(ours)


async def main() -> None:
    await matcher.refresh()
    categories = sys.argv[1:] or CATEGORIES

    seen: dict[str, set[int]] = {}
    total_ours = 0
    async with aiohttp.ClientSession(timeout=kwork.TIMEOUT) as http:
        for category in categories:
            ids, ours = await check(http, category)
            seen[category] = ids
            total_ours += ours

    if len(seen) == 2:
        a, b = list(seen)
        if seen[a] and seen[b]:
            if seen[b] <= seen[a]:
                print(f"c={b} целиком внутри c={a} — хватит одной c={a}")
            elif seen[a] <= seen[b]:
                print(f"c={a} целиком внутри c={b} — хватит одной c={b}")
            else:
                common = len(seen[a] & seen[b])
                print(f"категории пересекаются на {common} заказов, но не вложены")

    print(f"\nвсего подходящих заказов сейчас: {total_ours}")


if __name__ == "__main__":
    asyncio.run(main())
