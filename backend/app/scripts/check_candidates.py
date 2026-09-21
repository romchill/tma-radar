"""Проверка каналов-кандидатов перед добавлением в сбор.

Угадывать имена каналов бесполезно — проверено на шести десятках попыток.
Имена берутся из статей-подборок, но и им верить нельзя: половина ссылок
в таких статьях ведёт в никуда, а половина оставшихся — наём в штат.

Поэтому каждое имя проверяется по четырём признакам, и решает не название,
а последний из них:

  1. читается ли вообще (у групп веб-версии нет, у выдуманных имён — тоже);
  2. когда был последний пост — источник, молчащий месяцами, бесполезен;
  3. сколько постов проходит наш фильтр — то есть заказы ли это на ботов
     и мини-аппы, а не вакансии в штат и не тексты с дизайном;
  4. есть ли в постах бюджеты — признак биржевого заказа, а не болтовни.

Запуск: python -m app.scripts.check_candidates [@имя ...]
Без аргументов проверяет встроенный список.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

import aiohttp

from app.services import tgweb
from app.services.matcher import matcher
from app.workers.scorer import parse_budget

# Имена из статей-подборок плюс те, что похожи по формату на два уже
# работающих канала (@it_zakazy, @freelance_zakazy — парсеры бирж).
CANDIDATES = [
    # из подборки lidopad.online
    "freelancetavern", "distantsiya", "freelance_ru", "freelancechoice",
    "zakaz_freelance", "freelance_jobs_tg", "easy_freelance", "it_freelance",
    "backend_orders", "web_design_orders", "mobile_dev_jobs", "python_jobs_ru",
    "frontend_freelance", "wordpress_freelance", "tilda_freelance",
    # из подборки kadrof.ru
    "kadrof_work", "zapwork", "Getitrussia", "rueventjob", "workzavr",
    # формат работающих каналов
    "zakazy_it", "freelance_zakaz", "zakazi_freelance", "kwork_zakazy",
    "zakazy_kwork", "fl_zakazy", "freelance_orders", "workzilla_zakazy",
    "botzakazy", "zakazy_na_boty", "telegram_zakazy", "miniapp_zakazy",
]

FRESH_DAYS = 3


def age(posted_at) -> str:
    if posted_at is None:
        return "?"
    days = (datetime.now(timezone.utc) - posted_at).days
    if days == 0:
        hours = int((datetime.now(timezone.utc) - posted_at).total_seconds() // 3600)
        return f"{hours} ч" if hours else "только что"
    return f"{days} дн"


async def probe(http: aiohttp.ClientSession, name: str) -> dict:
    try:
        posts = await tgweb.fetch_channel(http, name)
    except Exception as exc:
        return {"name": name, "error": str(exc)[:40]}

    if not posts:
        return {"name": name, "error": "не читается"}

    newest = max((p.posted_at for p in posts if p.posted_at), default=None)

    matched = 0
    with_budget = 0
    samples: list[str] = []
    for post in posts:
        hits = await matcher.match(post.text)
        if hits:
            matched += 1
            if parse_budget(post.text)[0]:
                with_budget += 1
            if len(samples) < 2:
                samples.append(" ".join(post.text.split())[:70])

    return {
        "name": name,
        "posts": len(posts),
        "newest": newest,
        "matched": matched,
        "with_budget": with_budget,
        "samples": samples,
    }


async def main() -> None:
    names = [a.lstrip("@") for a in sys.argv[1:]] or CANDIDATES

    await matcher.refresh()
    print(f"проверяю {len(names)} кандидатов, по одному — чтобы не долбить t.me\n")

    results = []
    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as http:
        for name in names:
            results.append(await probe(http, name))
            await asyncio.sleep(1.5)

    good, dead, junk = [], [], []
    for r in results:
        if r.get("error"):
            dead.append(r)
        elif r["matched"] == 0:
            junk.append(r)
        else:
            good.append(r)

    print("=== ГОДНЫЕ: есть заказы на ботов и мини-аппы ===")
    for r in sorted(good, key=lambda x: -x["matched"]):
        print(
            f"  @{r['name']:<24} постов {r['posts']:>2}  подходит {r['matched']:>2}"
            f"  с бюджетом {r['with_budget']:>2}  свежесть {age(r['newest'])}"
        )
        for sample in r["samples"]:
            print(f"        {sample}")

    print("\n=== НЕ ТА НИША: читается, но заказов на ботов нет ===")
    for r in junk:
        print(f"  @{r['name']:<24} постов {r['posts']:>2}  свежесть {age(r['newest'])}")

    print("\n=== НЕ ЧИТАЕТСЯ: выдуманное имя, группа или закрытый канал ===")
    print("  " + ", ".join(f"@{r['name']}" for r in dead))

    print(f"\nитого годных: {len(good)} из {len(names)}")


if __name__ == "__main__":
    asyncio.run(main())
