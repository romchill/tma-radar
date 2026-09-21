"""Разовый вход юзербота. Выдаёт строку сессии для хостинга.

Запускать на своём компьютере, обязательно с -it — понадобится ввести код,
который телеграм пришлёт СООБЩЕНИЕМ в сам телеграм (не СМС):

    docker compose run --rm -it api python -m app.scripts.login

В конце скрипт напечатает строку сессии. Её нужно положить в секрет
TG_SESSION_STRING на хостинге — тогда юзербот переживёт любой передеплой,
а диск ему не понадобится.

Строка сессии — это полный доступ к аккаунту. Никому её не передавай, в
репозиторий не клади. Если утекла — заверши сеансы в телеграме:
Настройки -> Устройства -> Завершить все другие сеансы.
"""

from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import settings


async def main() -> None:
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise SystemExit(
            "Нет TG_API_ID и TG_API_HASH.\n"
            "Взять их: my.telegram.org -> API development tools.\n"
            "Код для входа туда приходит СООБЩЕНИЕМ в телеграм, симка не нужна."
        )

    # Вход всегда в строковую сессию: её можно и напечатать, и сохранить
    # файлом, а файловую в строку уже не превратить.
    client = TelegramClient(
        StringSession(),
        settings.tg_api_id,
        settings.tg_api_hash,
        device_model="Desktop",
        system_version="Windows 10",
    )
    await client.start(phone=settings.tg_phone or None)

    me = await client.get_me()
    print(f"\nВошли как {me.first_name} @{me.username} (id={me.id})")

    print("\nЧаты и каналы этого аккаунта (первые 30):")
    groups = 0
    async for dialog in client.iter_dialogs(limit=30):
        if dialog.is_user:
            continue
        groups += 1
        kind = "чат" if dialog.is_group else "канал"
        print(f"  {dialog.id:>16}  [{kind}] {dialog.name}")

    if not groups:
        print("  пусто — вступи в нужные чаты и запусти вход ещё раз")

    print("\n" + "=" * 62)
    print("СТРОКА СЕССИИ — положить в секрет TG_SESSION_STRING на хостинге.")
    print("Это полный доступ к аккаунту, никому не показывай.")
    print("=" * 62)
    print(client.session.save())
    print("=" * 62)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
