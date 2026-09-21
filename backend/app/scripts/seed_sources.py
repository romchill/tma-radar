"""Заводит рабочие источники в пустой базе.

Источники накапливались вручную командой /add в боте, и при переезде на
другую базу их пришлось бы вбивать заново. Список живых проверен по дате
последнего поста: мёртвые сюда не попали.

Запускается повторно без вреда — уже существующие источники пропускаются.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Source

SOURCES = [
    # (kind, username, title)
    # лучший живой: рубрика «Скрипты, боты и mini apps», ведёт на Kwork
    ("tg_channel", "it_zakazy", "it_zakazy"),
    # бюджеты указаны прямо в посте вилкой «от и до»
    ("tg_channel", "freelance_zakazy", "freelance_zakazy"),
    ("tg_channel", "naudalenkebro", "naudalenkebro"),
    ("tg_channel", "worklis", "worklis"),
    # ВК: на стене пишут сами люди, есть прямой контакт
    ("vk_group", "echo_php", "PHP"),
]


async def main() -> None:
    added, skipped = 0, 0

    async with SessionLocal() as session:
        for kind, username, title in SOURCES:
            exists = await session.scalar(
                select(Source.id).where(Source.kind == kind, Source.username == username)
            )
            if exists:
                print(f"  уже есть: {kind} {username}")
                skipped += 1
                continue

            session.add(Source(kind=kind, username=username, title=title, enabled=True))
            print(f"  добавлен: {kind} {username}")
            added += 1

        await session.commit()

    print(f"\nдобавлено: {added}, пропущено: {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
