"""Приведение строки подключения к виду, который понимают asyncpg и alembic.

Бесплатные хостинги баз (Neon, Supabase, Railway) выдают строку в формате
libpq: `postgresql://user:pass@host/db?sslmode=require&channel_binding=require`.
SQLAlchemy с драйвером asyncpg на ней падает дважды: сначала потому, что не
указан драйвер, потом на параметре `sslmode`, которого asyncpg не знает —
у него ключ называется `ssl`.

Чтобы владельцу не пришлось руками править строку, которую он скопировал в
панели хостинга, разбор делается здесь.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# параметры libpq, которые asyncpg не принимает и которые надо выкинуть
DROP_PARAMS = {"sslmode", "channel_binding", "options", "target_session_attrs"}

# значения sslmode, при которых шифрование обязательно
SSL_REQUIRED = {"require", "verify-ca", "verify-full"}

# Невидимый мусор, приезжающий вместе с копипастой: метка BOM и нулевой ширины
# пробелы из веб-страниц. На вид строка правильная, а SQLAlchemy падает на ней
# с невнятным «Could not parse URL». Уже ловили: PowerShell приписал BOM, когда
# строка подключения передавалась в секреты GitHub через конвейер.
# Записаны кодами намеренно — сами символы в исходнике не видны.
INVISIBLE = "".join(
    chr(code)
    for code in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060)
)


def clean(url: str) -> str:
    return (url or "").strip().strip(INVISIBLE).strip()


def normalize(url: str) -> tuple[str, dict]:
    """Возвращает asyncpg-URL и connect_args для create_async_engine."""
    url = clean(url)
    if not url:
        return url, {}

    scheme, netloc, path, query, fragment = urlsplit(url)

    # postgres:// и postgresql:// -> драйвер обязателен
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    params = parse_qsl(query, keep_blank_values=True)
    kept: list[tuple[str, str]] = []
    connect_args: dict = {}

    for key, value in params:
        low = key.lower()
        if low == "sslmode":
            if value.lower() in SSL_REQUIRED:
                connect_args["ssl"] = True
        elif low == "ssl":
            connect_args["ssl"] = value.lower() not in ("0", "false", "disable")
        elif low not in DROP_PARAMS:
            kept.append((key, value))

    return urlunsplit((scheme, netloc, path, urlencode(kept), fragment)), connect_args


def to_sync(url: str) -> str:
    """Синхронный URL для alembic: asyncpg он не умеет, а sslmode понимает."""
    url = clean(url)
    scheme, netloc, path, query, fragment = urlsplit(url)

    if scheme.startswith("postgresql+asyncpg") or scheme in ("postgres", "postgresql"):
        scheme = "postgresql"
    else:
        scheme = scheme.replace("+asyncpg", "")

    params = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k.lower() != "ssl"]
    return urlunsplit((scheme, netloc, path, urlencode(params), fragment))
