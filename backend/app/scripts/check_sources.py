"""Проверка разбора дайджестов и извлечения бюджета.

Тексты — настоящие посты из @freelansim_ru. БД не нужна.

Запуск: python -m app.scripts.check_sources
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from app.services.tgweb import ChannelPost, split_digest
from app.workers.scorer import MAX_HEURISTIC_SCORE, MAX_KEYWORD_SCORE, parse_budget

DIGEST = ChannelPost(
    channel="freelansim_ru",
    post_id=5605,
    text=(
        "Подборка заказов в категории Разработка (Боты и парсинг данных):\n\n"
        "1. Разработать телеграмм бота Quiz (цена договорная) https://u.habr.com/oLxp9\n"
        "2. Разработать телеграм бота для оплаты доступа в канал (цена договорная) "
        "https://u.habr.com/slDRM\n"
        "3. Разработка сайта. Интеграция базы данных Encar в сайт.  (цена договорная) "
        "https://u.habr.com/YmXJP\n"
        "4. Разработать MEV bot (solana) (300 000 руб. за проект) https://u.habr.com/J3uxV\n"
        "5. Доработка Скрипт парсера Telethon (1 000 руб. за проект) https://u.habr.com/HXJ50"
    ),
    link="https://t.me/freelansim_ru/5605",
    posted_at=datetime.now(timezone.utc),
    contact=None,
)

PLAIN = ChannelPost(
    channel="freelance_zakazy",
    post_id=77,
    text="Нужен телеграм бот для приёма заказов в кофейне, бюджет 40к",
    link="https://t.me/freelance_zakazy/77",
    posted_at=None,
    contact=None,
)

# (текст, ожидаемая прибавка к баллам)
BUDGETS: list[tuple[str, int]] = [
    ("Разработать MEV bot (solana) (300 000 руб. за проект)", 24),
    ("Разработка бота-P2P  (55 000 руб. за проект)", 18),
    ("Создать просто тг бота (5 000 руб. за проект)", 5),
    ("Доработка парсера (1 000 руб. за проект)", 0),
    ("Нужен бот для кофейни, бюджет 40к", 14),
    ("Второй проект, написать бота. Бюджет до 130к.р", 24),
    ("Разработать телеграмм бота Quiz (цена договорная)", 0),
]


def main() -> int:
    wrong = 0

    print("=== разбор дайджеста ===")
    items = split_digest(DIGEST)
    ok = len(items) == 5
    wrong += not ok
    print(f"  [{'ok' if ok else 'FAIL'}] пунктов получено: {len(items)} (ждали 5)")

    for item in items:
        print(f"      id={item.post_id}  {item.text[:58]}")
        print(f"                ссылка: {item.link}")

    links_ok = all(i.link.startswith("https://u.habr.com/") for i in items)
    ids_ok = len({i.post_id for i in items}) == len(items)
    wrong += not links_ok
    wrong += not ids_ok
    print(f"  [{'ok' if links_ok else 'FAIL'}] у каждого своя ссылка на заказ")
    print(f"  [{'ok' if ids_ok else 'FAIL'}] id уникальны (не сломают дедупликацию)")

    print("\n=== обычный пост не разбивается ===")
    plain = split_digest(PLAIN)
    ok = len(plain) == 1 and plain[0].link == PLAIN.link
    wrong += not ok
    print(f"  [{'ok' if ok else 'FAIL'}] пунктов: {len(plain)}")

    print("\n=== извлечение бюджета ===")
    for text, expected in BUDGETS:
        found, bonus = parse_budget(text)
        ok = bonus == expected
        wrong += not ok
        print(
            f"  [{'ok  ' if ok else 'FAIL'}] +{bonus:<3} (ждали +{expected:<3}) "
            f"нашёл: {str(found):<22} {text[:46]}"
        )

    print()
    print("=== ранжирование: бюджет решает ===")
    samples = [
        ("Разработка ботов с ИИ (60 000 руб. за проект)", 30),
        ("Сделать простое mini app в телеграм (35 000 руб. за проект)", 40),
        ("Создать телеграм бота с интеграцией amocrm (5 000 руб. за проект)", 65),
    ]
    scored = []
    for text, weight in samples:
        _, bonus = parse_budget(text)
        score = min(MAX_HEURISTIC_SCORE, min(MAX_KEYWORD_SCORE, 35 + weight) + bonus)
        scored.append((score, text))
    for score, text in sorted(scored, reverse=True):
        print(f"  {score:>3}  {text[:60]}")
    order_ok = scored[0][0] > scored[2][0]
    wrong += not order_ok
    print(f"  [{'ok' if order_ok else 'FAIL'}] заказ на 60 000 выше заказа на 5 000")

    print()
    print("всё верно" if not wrong else f"ПРОВАЛОВ: {wrong}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
