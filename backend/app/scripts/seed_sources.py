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
    # (kind, username, title, url)
    # ---- биржи напрямую: первоисточник, а не перепечатка ----
    # Kwork, категория 11 «Разработка и IT»: 104 активных заказа, у каждого
    # дата и бюджет. Категория 41 целиком внутри неё — проверено, отдельно
    # качать нечего.
    ("kwork", None, "Kwork · разработка", "https://kwork.ru/projects?c=11"),
    # FL.ru: единственная биржа с открытым RSS. Лента общая на все категории,
    # 60 заказов примерно за 7 часов — ключевики отсеют лишнее.
    ("rss", None, "FL.ru · все заказы", "https://www.fl.ru/rss/all.xml"),
    # ---- телеграм-каналы: те же биржи, но с задержкой ----
    # лучший живой: рубрика «Скрипты, боты и mini apps», ведёт на Kwork
    ("tg_channel", "it_zakazy", "it_zakazy", None),
    # бюджеты указаны прямо в посте вилкой «от и до»
    ("tg_channel", "freelance_zakazy", "freelance_zakazy", None),
    ("tg_channel", "naudalenkebro", "naudalenkebro", None),
    ("tg_channel", "worklis", "worklis", None),
    # ВК: на стене пишут сами люди, есть прямой контакт
    ("vk_group", "echo_php", "PHP", None),
]


async def main() -> None:
    added, skipped = 0, 0

    async with SessionLocal() as session:
        for kind, username, title, url in SOURCES:
            # у каналов и групп ключ — имя, у бирж имени нет, ключ — адрес
            key = Source.username == username if username else Source.url == url
            exists = await session.scalar(select(Source.id).where(Source.kind == kind, key))
            if exists:
                print(f"  уже есть: {kind} {username or url}")
                skipped += 1
                continue

            session.add(
                Source(kind=kind, username=username, title=title, url=url, enabled=True)
            )
            print(f"  добавлен: {kind} {username or url}")
            added += 1

        await session.commit()

    print(f"\nдобавлено: {added}, пропущено: {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
