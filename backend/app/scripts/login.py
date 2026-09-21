"""Разовый интерактивный вход юзербота.

Запускать так (обязательно с -it, нужен ввод кода из телеграма):

    docker compose run --rm collector python -m app.scripts.login

Файл сессии ляжет в ./backend/sessions и переживёт пересборку контейнера.
Никому его не передавай: это полный доступ к аккаунту.
"""

from __future__ import annotations

import asyncio

from telethon import TelegramClient

from app.config import settings


async def main() -> None:
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise SystemExit("Заполни TG_API_ID и TG_API_HASH в .env (my.telegram.org)")

    client = TelegramClient(settings.tg_session, settings.tg_api_id, settings.tg_api_hash)
    await client.start(phone=settings.tg_phone or None)

    me = await client.get_me()
    print(f"\nГотово. Вошли как {me.first_name} @{me.username} (id={me.id})")
    print(f"Сессия: {settings.tg_session}.session\n")

    print("Диалоги аккаунта (первые 30):")
    async for dialog in client.iter_dialogs(limit=30):
        if not dialog.is_user:
            print(f"  {dialog.id:>16}  {dialog.name}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
