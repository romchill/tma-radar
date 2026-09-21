"""Разбор бюджета из текста заказа.

Без ключа Anthropic цифра бюджета — единственный сигнал, отличающий жирный
заказ от правки за тысячу. Это критично из-за дневного лимита: в ленту
попадают лучшие N за сутки, и заказ на 200 000 не должен проигрывать заказу
на 2 000 только потому, что пришёл вторым.

Биржи пишут суммы по-разному: «300 000 руб.», «55 000 ₽», «бюджет 40к»,
а freelance_zakazy — «От  100,000 ₽  до  200,000 ₽», через запятую. Старая
версия не знала про запятую и читала «100,000 ₽» как ноль, из-за чего заказ
на 100–200 тысяч получал ноль бонуса и вылетал из ленты по лимиту.
"""

from __future__ import annotations

import re

# разделитель тысяч: пробел, неразрывный пробел, узкий пробел, запятая, точка
SEP = r"[ \t   .,]"

BUDGET_RE = re.compile(
    r"(?:бюджет\D{0,12})?(\d{1,3}(?:" + SEP + r"?\d{3})+|\d{1,4})\s*(?:000)?\s*"
    r"(руб|₽|р\.|тыс|к\b|k\b)",
    re.IGNORECASE,
)

# «до» между двумя суммами = вилка «от A до B»
RANGE_MARK = re.compile(r"\bдо\b", re.IGNORECASE)

THRESHOLDS = (
    (100_000, 24),
    (50_000, 18),
    (30_000, 14),
    (10_000, 9),
    (5_000, 5),
)


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def bonus_for(value: int) -> int:
    for threshold, bonus in THRESHOLDS:
        if value >= threshold:
            return bonus
    return 0


def _amounts(text: str) -> list[tuple[int, int, int]]:
    """Все суммы в тексте: (значение, начало, конец)."""
    out: list[tuple[int, int, int]] = []
    for match in BUDGET_RE.finditer(text):
        digits = re.sub(SEP, "", match.group(1))
        try:
            value = int(digits)
        except ValueError:
            continue
        if match.group(2).lower().startswith(("тыс", "к", "k")):
            value *= 1000
        if value > 0:
            out.append((value, match.start(), match.end()))
    return out


def parse_budget(text: str) -> tuple[str | None, int]:
    """Возвращает человекочитаемый бюджет и прибавку к баллам.

    У вилки «от A до B» считаем по нижней границе: платят по ней, а верхняя —
    это то, чего заказчик хочет за эти деньги. Иначе «от 2 000 до 6 000»
    выглядело бы как шеститысячный заказ.
    """
    found = _amounts(text)
    if not found:
        return None, 0

    for low, high in zip(found, found[1:]):
        if high[0] > low[0] and RANGE_MARK.search(text[low[2] : high[1]]):
            return f"{money(low[0])}–{money(high[0])} ₽", bonus_for(low[0])

    best = max(found, key=lambda item: item[0])
    return f"{money(best[0])} ₽", bonus_for(best[0])
