"""Чтение биржи заказов Kwork.

Kwork отдаёт заказы анонимному посетителю: страница биржи несёт в себе
готовый JSON со всеми полями — заголовок, описание, бюджет, срок, дата и
профиль заказчика. Это богаче любого телеграм-канала, которые в основном
и живут перепечаткой того же Kwork с задержкой и потерей половины полей.

Сортировка на бирже не по дате: свежий заказ может оказаться на третьей
странице. Поэтому категорию читаем целиком, а не только первую страницу —
категории небольшие, это дёшево.

Официального API нет, поэтому разбор держится на структуре страницы. Если
Kwork её поменяет, сбор молча опустеет — в приложении это видно по дате
последнего заказа у источника.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=30)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

BASE = "https://kwork.ru/projects"
STATE = "window.stateData="

# страховка от бесконечного обхода, если биржа вдруг отдаст сотни страниц
MAX_PAGES = 12

# даты на бирже без зоны, по московскому времени
MOSCOW_OFFSET = timedelta(hours=3)


@dataclass
class KworkProject:
    id: int
    title: str
    text: str
    link: str
    budget: str | None
    posted_at: datetime | None
    customer_url: str | None


def extract_state(html: str) -> dict:
    """Достаёт JSON, вшитый в страницу.

    Границу объекта ищем счётчиком скобок, а не регуляркой: в описаниях
    заказов попадаются и фигурные скобки, и кавычки, и экранированные
    кавычки внутри них.
    """
    start = html.find(STATE)
    if start < 0:
        raise ValueError("на странице нет stateData — биржа сменила разметку")
    start += len(STATE)

    depth = 0
    in_string = False
    escaped = False

    for i, ch in enumerate(html[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : i + 1])

    raise ValueError("stateData обрывается на середине")


def parse_date(raw: str | None) -> datetime | None:
    """Даты на бирже без зоны, по московскому времени."""
    if not raw:
        return None
    try:
        naive = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=timezone(MOSCOW_OFFSET)).astimezone(timezone.utc)


def money(value) -> str | None:
    """«4000.00» -> «4 000 ₽». Пустой бюджет бывает у заказов «договорная»."""
    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return f"{amount:,}".replace(",", " ") + " ₽"


def to_project(row: dict) -> KworkProject | None:
    project_id = row.get("id")
    title = (row.get("name") or "").strip()
    if not project_id or not title:
        return None

    description = (row.get("description") or "").strip()
    text = f"{title}\n\n{description}".strip() if description else title

    low = money(row.get("priceLimit"))
    high = money(row.get("possiblePriceLimit"))
    if low and high and high != low:
        budget = f"{low.rsplit(' ', 1)[0]}–{high}"
    else:
        budget = low or high

    # Бюджет с биржи дописываем в текст: скорер и шаблоны писем читают
    # сумму из текста, отдельного поля у них нет. Заодно она видна в карточке.
    if budget:
        text = text + "\n\nБюджет: " + budget

    return KworkProject(
        id=int(project_id),
        title=title,
        text=text,
        link=f"{BASE}/{project_id}",
        budget=budget,
        posted_at=parse_date(row.get("date_create")),
        customer_url=row.get("wantUserGetProfileUrl") or None,
    )


async def fetch_page(
    session: aiohttp.ClientSession, category: str | None, page: int
) -> tuple[list[KworkProject], int]:
    """Одна страница биржи. Возвращает заказы и сколько всего страниц."""
    params = {}
    if category:
        params["c"] = category
    if page > 1:
        params["page"] = str(page)

    async with session.get(BASE, params=params, headers=HEADERS) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        html = await response.text(errors="replace")

    state = extract_state(html)
    pagination = state.get("pagination") or {}
    rows = pagination.get("data") or state.get("wants") or []

    projects = [p for p in (to_project(r) for r in rows if isinstance(r, dict)) if p]
    last_page = int(pagination.get("last_page") or 1)
    return projects, last_page


async def fetch_category(
    session: aiohttp.ClientSession, category: str | None = None
) -> list[KworkProject]:
    """Вся категория целиком: на бирже сортировка не по дате."""
    projects, last_page = await fetch_page(session, category, 1)

    for page in range(2, min(last_page, MAX_PAGES) + 1):
        more, _ = await fetch_page(session, category, page)
        projects.extend(more)

    # один и тот же заказ попадается на разных страницах, если список
    # успел сдвинуться между запросами
    unique: dict[int, KworkProject] = {}
    for project in projects:
        unique.setdefault(project.id, project)
    return list(unique.values())
