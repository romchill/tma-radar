"""Проверка, что юзербот возьмёт сессию оттуда, откуда надо.

На ноутбуке сессия — файл, на хостинге файла нет: диск контейнера
сбрасывается при каждом передеплое. Ошибка здесь тихая и дорогая: юзербот
молча потребует вход заново, а заметно это станет только по тому, что лиды
из чатов перестали приходить.

Настоящий вход тут не выполняется — проверяется только выбор хранилища.
"""

from __future__ import annotations

from telethon.crypto import AuthKey
from telethon.sessions import StringSession

from app.config import settings
from app.services import tgsession


def sample_string() -> str:
    """Строка-образец правильного формата от несуществующего аккаунта.

    Просто `StringSession().save()` не годится: у сессии без ключа Telethon
    возвращает пустую строку, и проверка «со строкой берётся строковая
    сессия» превращается в проверку «с пустотой берётся файл».
    """
    session = StringSession()
    session.set_dc(2, "149.154.167.51", 443)
    session.auth_key = AuthKey(bytes(256))
    return session.save()


SAMPLE = sample_string()


def main() -> None:
    checks: list[tuple[str, bool]] = []

    original = settings.tg_session_string

    try:
        settings.tg_session_string = ""
        built = tgsession.build()
        ok = isinstance(built, str) and built == settings.tg_session
        checks.append(("без строки берётся файл на диске", ok))
        print(f"  пусто -> {type(built).__name__}: {built}")

        settings.tg_session_string = SAMPLE
        built = tgsession.build()
        ok = isinstance(built, StringSession)
        checks.append(("со строкой берётся строковая сессия", ok))
        print(f"  строка -> {type(built).__name__}")

        settings.tg_session_string = "   " + SAMPLE + "  "
        built = tgsession.build()
        ok = isinstance(built, StringSession)
        checks.append(("пробелы по краям не мешают", ok))

        settings.tg_session_string = "   "
        built = tgsession.build()
        ok = isinstance(built, str)
        checks.append(("строка из пробелов = не задана", ok))
    finally:
        settings.tg_session_string = original

    print()
    for name, ok in checks:
        print(("  [ok]   " if ok else "  [FAIL] ") + name)
    print("\nвсё верно" if all(ok for _, ok in checks) else "\nесть провалы")


if __name__ == "__main__":
    main()
