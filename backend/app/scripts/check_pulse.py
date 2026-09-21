"""Проверка, что сбор, оценка и напоминалка ходят в базу одним окном.

Бесплатная база засыпает после 5 минут покоя и считает только время
бодрствования. Пока скорер спрашивал «нет ли работы» каждые 5 секунд, а
напоминалка ходила своим таймером раз в 5 минут, база не засыпала никогда —
месячного лимита хватило бы примерно на шестнадцать дней.

Проверяем ровно три вещи: сигнал будит ждущего сразу, ожидание не висит
дольше отпущенного, и сигнал не остаётся взведённым на следующий круг.
"""

from __future__ import annotations

import asyncio
import time

from app.workers import pulse


async def main() -> None:
    checks: list[tuple[str, bool]] = []

    # 1. сборщик будит скорера немедленно, а не через свой интервал
    async def collector() -> None:
        await asyncio.sleep(0.05)
        pulse.ping()

    started = time.monotonic()
    asyncio.create_task(collector())
    woken = await pulse.wait(timeout=5)
    elapsed = time.monotonic() - started
    ok = woken and elapsed < 1
    checks.append(("сборщик будит скорера сразу", ok))
    print(f"  скорер проснулся за {elapsed:.2f} с, по сигналу: {woken}")

    # 2. без сигнала ожидание заканчивается само и не висит вечно
    started = time.monotonic()
    woken = await pulse.wait(timeout=0.3)
    elapsed = time.monotonic() - started
    ok = (not woken) and 0.25 < elapsed < 1.5
    checks.append(("без сигнала просыпается по таймеру", ok))
    print(f"  без сигнала ждал {elapsed:.2f} с, по сигналу: {woken}")

    # 3. сигнал одноразовый: иначе следующий круг проснулся бы впустую
    #    и разбудил бы базу на ровном месте
    woken = await pulse.wait(timeout=0.3)
    checks.append(("сигнал не залипает на следующий круг", not woken))
    print(f"  следующий круг по сигналу: {woken}")

    # 4. конец цикла будит напоминалку — она идёт в базу тем же окном
    async def scorer() -> None:
        await asyncio.sleep(0.05)
        pulse.cycle_done()

    started = time.monotonic()
    asyncio.create_task(scorer())
    woken = await pulse.wait_cycle(timeout=5)
    elapsed = time.monotonic() - started
    ok = woken and elapsed < 1
    checks.append(("напоминалка идёт следом за циклом", ok))
    print(f"  напоминалка проснулась за {elapsed:.2f} с, по сигналу: {woken}")

    # 5. сигналы не путаются между собой
    pulse.ping()
    woken = await pulse.wait_cycle(timeout=0.3)
    checks.append(("сигнал сборщика не будит напоминалку", not woken))
    await pulse.wait(timeout=0.1)  # прибираем за собой

    print()
    for name, ok in checks:
        print(("  [ok]   " if ok else "  [FAIL] ") + name)
    print("\nвсё верно" if all(ok for _, ok in checks) else "\nесть провалы")


if __name__ == "__main__":
    asyncio.run(main())
