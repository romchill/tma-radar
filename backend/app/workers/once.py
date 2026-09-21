"""Один проход радара: собрать, оценить, отправить и выйти.

Нужен для запуска по расписанию на стороне, где нет вечно живущего процесса —
сейчас это GitHub Actions. Ноутбук при этом может быть выключен: обход
источников, оценка и пуши происходят на чужих серверах, а данные лежат во
внешней базе.

Бота здесь нет: он держит соединение с Telegram и в короткий запуск не
вписывается. Команды бота работают, когда поднят docker на ноутбуке; заказы
приходят в любом случае, потому что пуш отправляется обычным вызовом API.
"""

from __future__ import annotations

import asyncio

import aiohttp

from app.logging_conf import setup_logging
from app.services import feeds, kwork, notify, tgweb, vk
from app.services.matcher import matcher
from app.workers import channels, feeds as feed_worker, kwork_board, scorer, vk_walls

log = setup_logging("once")

# Потолок на случай, если очередь окажется огромной: запуск не должен висеть
# бесконечно, невыбранное разберётся в следующий раз.
MAX_SCORER_ROUNDS = 50


async def collect() -> int:
    """Обход всех источников. Сбой одного не должен ронять весь проход."""
    total = 0

    async with aiohttp.ClientSession(timeout=tgweb.TIMEOUT) as http:
        try:
            added = await channels.poll_once(http)
            log.info("каналы: новых постов %d", added)
            total += added
        except Exception:
            log.exception("сбой обхода каналов")

    async with aiohttp.ClientSession(timeout=feeds.TIMEOUT) as http:
        try:
            added = await feed_worker.poll_once(http)
            log.info("биржи: новых заказов %d", added)
            total += added
        except Exception:
            log.exception("сбой обхода лент")

    async with aiohttp.ClientSession(timeout=kwork.TIMEOUT) as http:
        try:
            added = await kwork_board.poll_once(http)
            log.info("kwork: новых заказов %d", added)
            total += added
        except Exception:
            log.exception("сбой обхода Kwork")

    async with aiohttp.ClientSession(timeout=vk.TIMEOUT) as http:
        try:
            added = await vk_walls.poll_once(http)
            log.info("вк: новых постов %d", added)
            total += added
        except Exception:
            log.exception("сбой обхода групп ВК")

    return total


async def score_all() -> int:
    """Разбирает очередь до конца, а не один батч."""
    total = 0
    for _ in range(MAX_SCORER_ROUNDS):
        done = await scorer.tick()
        if not done:
            break
        total += done
    else:
        log.warning("очередь не разобрана до конца, остаток уйдёт в следующий проход")
    return total


async def main() -> None:
    from app.db import SessionLocal

    # Прошлый запуск мог оборваться в середине батча и оставить сообщения
    # помеченными «в работе». Вечно живущий воркер разгребал бы это сам,
    # а здесь процесса, который вернётся, просто нет.
    async with SessionLocal() as session:
        restored = await scorer.reset_stale(session)
        if restored:
            log.info("вернул в очередь зависших с прошлого раза: %d", restored)

    await matcher.refresh()

    collected = await collect()
    scored = await score_all()

    log.info("проход закончен: собрано %d, оценено %d", collected, scored)
    await notify.close()


if __name__ == "__main__":
    asyncio.run(main())
