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

# Владелец оставил только телеграм и Kwork (21.09.2026). FL.ru и группы ВК
# отсюда убраны намеренно — не возвращать без его просьбы. Код чтения RSS
# (`kind='rss'`) и стен ВК (`kind='vk_group'`) на месте и заработает сразу,
# если такой источник снова появится в списке.
SOURCES = [
    # (kind, username, title, url)
    # Биржа напрямую: первоисточник, а не перепечатка. Категория 11
    # «Разработка и IT» — ~104 активных заказа, у каждого дата и бюджет.
    # Категория 41 целиком внутри неё, отдельно качать нечего.
    ("kwork", None, "Kwork · разработка", "https://kwork.ru/projects?c=11"),
    # ---- телеграм-каналы ----
    # Самое точное попадание из всех каналов: 12 заказов на ботов из 20
    # постов против 6 из 20 у прежнего лидера it_zakazy.
    ("tg_channel", "job_for_bots", "job_for_bots", None),
    # лучший живой: рубрика «Скрипты, боты и mini apps», ведёт на Kwork
    ("tg_channel", "it_zakazy", "it_zakazy", None),
    # бюджеты указаны прямо в посте вилкой «от и до»
    ("tg_channel", "freelance_zakazy", "freelance_zakazy", None),
    ("tg_channel", "naudalenkebro", "naudalenkebro", None),
    ("tg_channel", "worklis", "worklis", None),
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
