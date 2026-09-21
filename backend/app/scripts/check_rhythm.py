"""Проверка, что сборщики не расползаются по фазе.

Обычное `sleep(interval)` в конце цикла сдвигает следующий заход на
длительность работы. У сборщиков она разная — обход Kwork идёт полминуты,
обход каналов дольше, — и за сутки они расходятся на десятки минут.

Бесплатной базе это дорого: она засыпает после 5 минут покоя, и четыре
сборщика вразнобой держат её включённой почти всё время. На общей сетке они
просыпаются одновременно, база отрабатывает один раз и снова спит.

Проверяем численно: гоняем четыре «сборщика» с разной длительностью работы и
смотрим, как расходятся моменты их пробуждения.
"""

from __future__ import annotations

import asyncio
import time

from app.workers import pulse

INTERVAL = 2.0
ROUNDS = 4
# «сборщики» с разной длительностью работы, как в жизни
DURATIONS = {"каналы": 0.5, "kwork": 0.3, "ленты": 0.05, "вк": 0.02}


async def collector(name: str, work: float, sleeper, wakeups: dict) -> None:
    for _ in range(ROUNDS):
        wakeups.setdefault(name, []).append(time.time())
        await asyncio.sleep(work)
        await sleeper(INTERVAL)


async def measure(sleeper) -> float:
    """Максимальный разброс моментов пробуждения в последнем круге."""
    wakeups: dict[str, list[float]] = {}
    await asyncio.gather(
        *(collector(n, w, sleeper, wakeups) for n, w in DURATIONS.items())
    )
    last = [times[-1] for times in wakeups.values()]
    return max(last) - min(last)


async def main() -> None:
    print(f"интервал {INTERVAL} с, {ROUNDS} круга, работа от 0.02 до 0.5 с\n")

    drift_plain = await measure(asyncio.sleep)
    print(f"  обычный sleep:     разброс {drift_plain:.2f} с")

    drift_grid = await measure(pulse.sleep_until_next_tick)
    print(f"  общая сетка:       разброс {drift_grid:.2f} с")

    checks = [
        ("обычный sleep расползается", drift_plain > INTERVAL / 4),
        ("на сетке сборщики идут вместе", drift_grid < 0.1),
        ("сетка заметно лучше", drift_grid < drift_plain / 3),
    ]

    print()
    for name, ok in checks:
        print(("  [ok]   " if ok else "  [FAIL] ") + name)
    print("\nвсё верно" if all(ok for _, ok in checks) else "\nесть провалы")


if __name__ == "__main__":
    asyncio.run(main())
