"""Все фоновые задачи в одном процессе.

На слабой машине три отдельных контейнера — это три копии интерпретатора
с SQLAlchemy, pydantic и anthropic внутри, то есть лишние ~200 МБ впустую.
Collector, scorer и bot — обычные asyncio-задачи, поэтому живут в одном
событийном цикле без потери в поведении.

Каждая задача под присмотром: падение одной не роняет остальные, перезапуск
идёт с нарастающей паузой. Если нужна изоляция (например, скорер начал
упираться в CPU), любую задачу можно вынести обратно в свой контейнер —
модули для этого не менялись.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.config import settings
from app.logging_conf import setup_logging
from app.workers import bot, channels, collector, scorer, vk_walls

log = setup_logging("worker")

RETRY_MIN_SEC = 15
RETRY_MAX_SEC = 300


async def supervise(name: str, factory: Callable[[], Awaitable[None]]) -> None:
    """Держит задачу живой. factory вызывается заново на каждый перезапуск,
    потому что клиенты (Telethon, aiogram) переиспользовать после падения нельзя."""
    delay = RETRY_MIN_SEC

    while True:
        try:
            log.info("[%s] старт", name)
            await factory()
            log.warning("[%s] задача завершилась сама", name)
        except asyncio.CancelledError:
            log.info("[%s] остановлен", name)
            raise
        except SystemExit as exc:
            # collector так сообщает, что сессия юзербота не создана —
            # это чинится руками, поэтому просто ждём и пробуем снова
            log.error("[%s] не может стартовать (%s), жду %d с", name, exc, delay)
        except Exception:
            log.exception("[%s] упал, перезапуск через %d с", name, delay)

        await asyncio.sleep(delay)
        delay = min(delay * 2, RETRY_MAX_SEC)


def userbot_configured() -> bool:
    return bool(settings.tg_api_id and settings.tg_api_hash)


async def main() -> None:
    jobs: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("channels", channels.run),
        ("vk", vk_walls.run),
        ("scorer", scorer.run),
        ("bot", bot.run),
    ]

    # Юзербот подключается, только если есть api_id/api_hash с my.telegram.org.
    # Без них Telethon не стартует в принципе, и держать задачу в вечном
    # перезапуске — только засорять логи.
    if userbot_configured():
        jobs.insert(0, ("collector", lambda: collector.Collector().run()))
    else:
        log.info(
            "юзербот отключён (нет TG_API_ID/TG_API_HASH) — "
            "лиды собираются из публичных каналов"
        )

    log.info("фоновые задачи в одном процессе: %s", ", ".join(name for name, _ in jobs))

    tasks = [asyncio.create_task(supervise(name, factory)) for name, factory in jobs]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
