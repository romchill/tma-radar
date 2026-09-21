"""Проверка разбора строки подключения к базе.

Владелец копирует строку из панели бесплатного хостинга как есть. Neon даёт
её в формате libpq (`postgresql://...?sslmode=require&channel_binding=require`),
и на ней SQLAlchemy с asyncpg падает дважды: нет драйвера в схеме и нет
параметра `sslmode`. Проверяем, что всё это чинится само.
"""

from __future__ import annotations

from app.dburl import normalize, to_sync

NEON = (
    "postgresql://radar:tajnoe@ep-cool-frog-12345.eu-central-1.aws.neon.tech/"
    "radar?sslmode=require&channel_binding=require"
)

CASES = [
    (
        "строка с невидимым BOM в начале",
        chr(0xFEFF) + NEON,
        "postgresql+asyncpg://radar:tajnoe@ep-cool-frog-12345.eu-central-1.aws.neon.tech/radar",
        {"ssl": True},
    ),
    (
        "строка Neon как есть",
        NEON,
        "postgresql+asyncpg://radar:tajnoe@ep-cool-frog-12345.eu-central-1.aws.neon.tech/radar",
        {"ssl": True},
    ),
    (
        "короткий postgres://",
        "postgres://u:p@host:5432/db",
        "postgresql+asyncpg://u:p@host:5432/db",
        {},
    ),
    (
        "локальный docker compose",
        "postgresql+asyncpg://radar:radar@db:5432/radar",
        "postgresql+asyncpg://radar:radar@db:5432/radar",
        {},
    ),
    (
        "явно выключенный ssl",
        "postgresql://u:p@host/db?sslmode=disable",
        "postgresql+asyncpg://u:p@host/db",
        {},
    ),
]

checks: list[tuple[str, bool]] = []

for name, raw, want_url, want_args in CASES:
    url, args = normalize(raw)
    ok = url == want_url and args == want_args
    checks.append((name, ok))
    print(("  [ok]   " if ok else "  [FAIL] ") + name)
    if not ok:
        print(f"         получили: {url}  {args}")
        print(f"         ждали:    {want_url}  {want_args}")

print("\nсинхронный URL для alembic:")
sync = to_sync(NEON)
print("  " + sync)
ok_sync = sync.startswith("postgresql://") and "asyncpg" not in sync and "sslmode=require" in sync
checks.append(("alembic получает libpq-строку с sslmode", ok_sync))
print(("  [ok]   " if ok_sync else "  [FAIL] ") + "alembic получает libpq-строку с sslmode")

print("\nвсё верно" if all(ok for _, ok in checks) else "\nесть провалы")
