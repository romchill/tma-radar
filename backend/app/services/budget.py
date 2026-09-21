"""Разбор бюджета из текста заказа.

Без ключа Anthropic цифра бюджета — единственный сигнал, отличающий жирный
заказ от правки за тысячу. Это критично из-за дневного лимита: в ленту
попадают лучшие N за сутки, и заказ на 200 000 не должен проигрывать заказу
на 2 000 только потому, что пришёл вторым.

Биржи пишут суммы по-разному: «300 000 руб.», «55 000 ₽», «бюджет 40к»,
freelance_zakazy — «От  100,000 ₽  до  200,000 ₽» через запятую, а люди
обычно «от 45 000 до 70 000 руб», где единица стоит только в конце.
"""

from __future__ import annotations

import re

# разделитель тысяч: пробел, неразрывный пробел, узкий пробел, запятая, точка
SEP = r"[ \t   .,]"
NUM = r"\d{1,3}(?:" + SEP + r"?\d{3})+|\d{1,4}"
UNIT = r"руб\w*|₽|р\.|тыс\w*|к\b|k\b"

BUDGET_RE = re.compile(
    r"(?:бюджет\D{0,12})?(" + NUM + r")\s*(?:000)?\s*(" + UNIT + r")",
    re.IGNORECASE,
)

# «от 45 000 до 70 000 руб» — у первой суммы своей единицы может не быть,
# поэтому одной BUDGET_RE вилка не ловится: она видит только вторую половину
# и считает заказ дороже, чем он есть.
RANGE_RE = re.compile(
    r"\bот\b\s*(" + NUM + r")\s*(" + UNIT + r")?\s*"
    r"\bдо\b\s*(" + NUM + r")\s*(" + UNIT + r")",
    re.IGNORECASE,
)

# «до» между двумя отдельно найденными суммами — тоже вилка
NEAR_RANGE = re.compile(r"\bдо\b", re.IGNORECASE)

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


def _value(digits: str, unit: str | None) -> int:
    """Число с учётом единицы: «40к» и «40 тыс» — это сорок тысяч."""
    try:
        value = int(re.sub(SEP, "", digits))
    except ValueError:
        return 0
    if unit and unit.lower().startswith(("тыс", "к", "k")):
        value *= 1000
    return value


def _amounts(text: str) -> list[tuple[int, int, int]]:
    """Все суммы в тексте: (значение, начало, конец)."""
    out: list[tuple[int, int, int]] = []
    for match in BUDGET_RE.finditer(text):
        value = _value(match.group(1), match.group(2))
        if value > 0:
            out.append((value, match.start(), match.end()))
    return out


def _range(text: str) -> tuple[str, int] | None:
    """Вилка «от A до B». Считаем по нижней границе."""
    match = RANGE_RE.search(text)
    if match is None:
        return None

    low_digits, low_unit, high_digits, high_unit = match.groups()
    # единица у первой суммы часто опущена — берём от второй
    low = _value(low_digits, low_unit or high_unit)
    high = _value(high_digits, high_unit)

    if low <= 0 or high <= low:
        return None
    return f"{money(low)}–{money(high)} ₽", bonus_for(low)


def parse_budget(text: str) -> tuple[str | None, int]:
    """Возвращает человекочитаемый бюджет и прибавку к баллам.

    У вилки считаем по нижней границе: платят по ней, а верхняя — это то,
    чего заказчик хочет за эти деньги. Иначе «от 2 000 до 6 000» выглядело
    бы как шеститысячный заказ, а «от 45 000 до 70 000» переоценивалось бы
    на целую ступень.
    """
    found_range = _range(text)
    if found_range is not None:
        return found_range

    found = _amounts(text)
    if not found:
        return None, 0

    # вилка, у которой обе половины с единицами: «От 100,000 ₽ до 200,000 ₽»
    for low, high in zip(found, found[1:]):
        if high[0] > low[0] and NEAR_RANGE.search(text[low[2] : high[1]]):
            return f"{money(low[0])}–{money(high[0])} ₽", bonus_for(low[0])

    best = max(found, key=lambda item: item[0])
    return f"{money(best[0])} ₽", bonus_for(best[0])
