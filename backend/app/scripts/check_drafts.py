"""Проверка черновиков на реальных постах с бирж.

Тексты взяты из @it_zakazy и @freelance_zakazy как есть, со всей шапкой:
именно она ломала и выбор шаблона, и выжимку задачи.

Запуск: python -m app.scripts.check_drafts
"""

from __future__ import annotations

import sys

from app.services.templates import build_draft, pick_kind

# (ожидаемый шаблон, что должно попасть в задачу, текст поста)
CASES: list[tuple[str, str, str]] = [
    (
        "platform_bot",
        "WhatsApp",
        "📁 Скрипты, боты и mini apps | 💰 20 000 ₽ | ⏰ 10 дн.\n\n"
        "WhatsApp-бот с ИИ для ответов клиентам на типовые вопросы",
    ),
    (
        "bot",
        "Telegram-бот",
        "📁 Скрипты, боты и mini apps | 💰 30 000 ₽ | ⏰ 10 дн.\n\n"
        "MVP Telegram-бот+Web-сервис для Честного знака",
    ),
    (
        "bot",
        "корпоративного ассистента",
        "📌 Разработка бота, корпоративного ассистента\n\n"
        "📝 Разработка корпоративного AI-ассистента в формате бота.\n"
        "💳 Бюджет: От 5,000 ₽",
    ),
    (
        "mini_app",
        "мини аппа",
        "Ищем разработчика мини аппа под онлайн-школу, личный кабинет ученика",
    ),
    (
        "broken",
        "",
        "Бот записи к мастерам перестал работать, разраб пропал",
    ),
]


def main() -> int:
    wrong = 0
    for expected_kind, must_contain, post in CASES:
        kind = pick_kind(post)
        draft = build_draft(post)

        kind_ok = kind == expected_kind
        text_ok = (not must_contain) or (must_contain.lower() in draft.lower())
        # шапка биржи не должна утечь в сообщение клиенту
        clean = "₽" not in draft and "дн." not in draft

        ok = kind_ok and text_ok and clean
        wrong += not ok

        print("=" * 74)
        print(f"[{'ok' if ok else 'FAIL'}] шаблон={kind} (ждали {expected_kind})", end="")
        if not text_ok:
            print(f"  — в тексте нет «{must_contain}»", end="")
        if not clean:
            print("  — в черновик утекла шапка биржи", end="")
        print("\n")
        print(draft)
        print()

    print(f"ИТОГ: {'всё верно' if not wrong else f'ПРОВАЛОВ {wrong}'} из {len(CASES)}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
