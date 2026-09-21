"""Проверка живой базы: доходим, пишем, читаем, убираем за собой.

Нужна при переезде на внешний Postgres. Строку подключения владелец копирует
из панели хостинга как есть, и до этой проверки непонятно, договорятся ли
драйвер, шифрование и сеть.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.dburl import normalize


async def main() -> None:
    url, args = normalize(settings.database_url)
    host = url.split("@")[-1].split("/")[0]
    print(f"хост:      {host}")
    print(f"шифрование: {'да' if args.get('ssl') else 'нет'}")

    async with SessionLocal() as session:
        version = await session.scalar(text("SHOW server_version"))
        print(f"postgres:  {version}")

        await session.execute(text("CREATE TABLE IF NOT EXISTS _probe (v int)"))
        await session.execute(text("INSERT INTO _probe VALUES (42)"))
        got = await session.scalar(text("SELECT v FROM _probe LIMIT 1"))
        await session.execute(text("DROP TABLE _probe"))
        await session.commit()
        print(f"запись:    {'ok' if got == 42 else 'ПРОВАЛ'}")

        tables = await session.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        )
        print(f"таблиц:    {tables}")

    print("\nбаза готова" if got == 42 else "\nбаза недоступна")


if __name__ == "__main__":
    asyncio.run(main())
