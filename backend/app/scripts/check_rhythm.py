"""Проверка, что сборщики будят базу одним окном, а не вразнобой.

Обычное `sleep(interval)` в конце цикла сдвигает следующий заход на
длительность работы. У сборщиков она разная — обход Kwork идёт полминуты,
обход каналов дольше, — и за сутки они расходятся по фазе на десятки минут.

Бесплатной базе это дорого: она засыпает после 5 минут покоя, и четыре
сборщика вразнобой держат её включённой почти всё время. На общей сетке они
просыпаются на одних и тех же отметках, база отрабатывает один раз и спит.

Мерить надо именно попадание в отметку, а не «сколько прошло между
пробуждениями»: сборщик, закончивший работу сразу после отметки, ждёт
следующую и оказывается на круг позади — при этом он по-прежнему на сетке
и базу будит вместе со всеми.
"""

from __future__ import annotations

import asyncio
import time

from app.workers import pulse

INTERVAL = 2.0
ROUNDS = 5
# «сборщики» с разной длительностью работы, как в жизни
DURATIONS = {"каналы": 0.5, "kwork": 0.3, "ленты": 0.05, "вк": 0.02}


async def collector(name: str, work: float, sleeper, wakeups: dict) -> None:
    for _ in range(ROUNDS):
        wakeups.setdefault(name, []).append(time.time())
        await asyncio.sleep(work)
        await sleeper(INTERVAL)


async def phases(sleeper) -> list[float]:
    """Куда внутри интервала попадают пробуждения.

    0 — ровно на отметку сетки. Разброс этих значений и показывает,
    просыпаются сборщики вместе или размазаны по всему интервалу.
    """
    wakeups: dict[str, list[float]] = {}
    await asyncio.gather(
        *(collector(n, w, sleeper, wakeups) for n, w in DURATIONS.items())
    )
    # первое пробуждение — момент старта, он у всех общий и ни о чём не говорит
    out = []
    for times in wakeups.values():
        for moment in times[1:]:
            phase = moment % INTERVAL
            out.append(min(phase, INTERVAL - phase))  # расстояние до отметки
    return out


async def main() -> None:
    print(f"интервал {INTERVAL} с, {ROUNDS} кругов, работа от 0.02 до 0.5 с")
    print("меряем, насколько пробуждения отходят от отметки сетки\n")

    plain = await phases(asyncio.sleep)
    grid = await phases(pulse.sleep_until_next_tick)

    print(f"  обычный sleep:  худшее отклонение {max(plain):.2f} с")
    print(f"  общая сетка:    худшее отклонение {max(grid):.2f} с")

    checks = [
        ("обычный sleep уводит с отметки", max(plain) > INTERVAL / 8),
        ("на сетке все попадают в отметку", max(grid) < 0.05),
    ]

    print()
    for name, ok in checks:
        print(("  [ok]   " if ok else "  [FAIL] ") + name)
    print("\nвсё верно" if all(ok for _, ok in checks) else "\nесть провалы")


if __name__ == "__main__":
    asyncio.run(main())
