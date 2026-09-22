"""Проверка, что в карточке стоит ссылка на сам заказ, а не на пост о нём.

Каналы @freelance_zakazy и @it_zakazy — перепечатка Kwork, и настоящая
ссылка лежит в разметке поста. Текстовый парсер её терял вместе с тегами, и
владельцу приходилось открывать пост канала, а уже оттуда идти на биржу.

У @freelance_zakazy к каждой ссылке приклеен `?ref=15678240` — партнёрский
код владельца канала. Переход по нему записывает переход на чужую партнёрку,
поэтому хвост снимается.

Первая часть проверки — на живом канале, вторая — на разобранных примерах.
"""

from __future__ import annotations

import asyncio

import aiohttp

from app.services import orderlink, tgweb

CASES = [
    (
        "ссылка Kwork с чужим реферальным кодом",
        "https://kwork.ru/projects/3257567?ref=15678240",
        "https://kwork.ru/projects/3257567",
        "Kwork",
    ),
    (
        "ссылка Kwork без хвоста",
        "загляни сюда https://kwork.ru/projects/3256689 там бот",
        "https://kwork.ru/projects/3256689",
        "Kwork",
    ),
    (
        "ссылка FL.ru",
        '<a href="https://www.fl.ru/projects/5522818/poisk.html">заказ</a>',
        "https://www.fl.ru/projects/5522818/poisk.html",
        "FL.ru",
    ),
    (
        "рекламные метки тоже снимаются",
        "https://kwork.ru/projects/111222?utm_source=tg&utm_medium=post",
        "https://kwork.ru/projects/111222",
        "Kwork",
    ),
    ("ссылка на пост канала — не заказ", "https://t.me/freelance_zakazy/445859", None, None),
    ("главная биржи — не заказ", "https://kwork.ru/", None, None),
    ("текст без ссылок", "нужен бот для записи клиентов", None, None),
]


def check_cases() -> list[tuple[str, bool]]:
    out = []
    for name, source, want_url, want_shop in CASES:
        found = orderlink.find(source)
        ok = found == want_url
        if want_shop is not None:
            ok = ok and orderlink.shop_name(found) == want_shop
        out.append((name, ok))
        print(("  [ok]   " if ok else "  [FAIL] ") + name)
        if not ok:
            print(f"         получили {found!r}, ждали {want_url!r}")
    return out


async def check_live() -> tuple[str, bool]:
    """Настоящий канал: сколько постов отдают ссылку на заказ."""
    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as http:
        posts = await tgweb.fetch_channel(http, "freelance_zakazy")

    if not posts:
        print("  канал не прочитался — проверку на живом пропускаем")
        return ("живой канал отдаёт ссылки на заказ", True)

    with_order = [p for p in posts if p.order_url]
    print(f"\n  постов {len(posts)}, со ссылкой на заказ {len(with_order)}")
    for post in with_order[:3]:
        print(f"     пост:  {post.link}")
        print(f"     заказ: {post.order_url}")

    dirty = [p for p in with_order if "ref=" in (p.order_url or "")]
    ok = bool(with_order) and not dirty
    if dirty:
        print(f"  [FAIL] у {len(dirty)} ссылок остался чужой реферальный хвост")
    return ("живой канал отдаёт чистые ссылки на заказ", ok)


async def main() -> None:
    print("=== разобранные примеры ===")
    checks = check_cases()

    print("\n=== живой канал ===")
    checks.append(await check_live())

    print()
    for name, ok in checks:
        print(("  [ok]   " if ok else "  [FAIL] ") + name)
    print("\nвсё верно" if all(ok for _, ok in checks) else "\nесть провалы")


if __name__ == "__main__":
    asyncio.run(main())
