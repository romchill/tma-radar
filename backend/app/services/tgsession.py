"""Выбор способа хранения сессии юзербота.

Telethon по умолчанию держит сессию файлом. На ноутбуке это удобно, а на
хостинге бесполезно: диск контейнера сбрасывается при каждом передеплое, и
после любого обновления кода юзербот требовал бы входа заново — с кодом из
телеграма, руками, вслепую через логи.

Поэтому там, где диска нет, сессия хранится строкой в секретах. Строка — это
полный доступ к аккаунту, поэтому в репозиторий она не попадает и в логах не
печатается.
"""

from __future__ import annotations

from telethon.sessions import StringSession

from app.config import settings


def build():
    """Сессия для TelegramClient: строка из секретов или файл на диске."""
    raw = (settings.tg_session_string or "").strip()
    if raw:
        return StringSession(raw)
    return settings.tg_session


def is_string_session() -> bool:
    return bool((settings.tg_session_string or "").strip())
