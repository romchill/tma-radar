"""Предфильтр: что вообще похоже на заказ, а что сразу мимо.

Два списка. Первый ловит заказы на ботов и мини-аппы. Второй — стоп-слова:
если сработал хоть один, пост отбрасывается, даже когда совпало десять
ключевиков. Так отсекаются вакансии в штат, резюме исполнителей и реклама
таких же студий — по одним положительным словам их от заказа не отличить.

Стоп-слова важнее для бесплатного режима: там нет модели, которая поняла бы
смысл, и без них лента забивается наймом в штат.
"""

from __future__ import annotations

import logging
import re
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Keyword

log = logging.getLogger(__name__)

CACHE_TTL_SEC = 60

# (pattern, is_regex, weight)
# Ниша: боты под любые площадки и Telegram Mini Apps. Всё, что про «просто
# разработчика» без упоминания бота или аппа, намеренно не ловим — именно эта
# формулировка тащила вакансии в штат.
DEFAULT_KEYWORDS: list[tuple[str, bool, int]] = [
    # --- прямой заказ на бота ---
    (r"(нужен|нужна|нужно|ищу|ищем|требуется|ищется)\s+(\w+\s+){0,3}(бот|бота|чат-?бот\w*)", True, 35),
    (r"(заказать|разработать|написать|сделать|запустить|создать)\s+(\w+\s+){0,3}(бот|бота|чат-?бот\w*)", True, 35),
    (r"(бот|бота|чат-?бот\w*)\s+(под ключ|на заказ)", True, 35),
    (r"разработк\w+\s+(\w+\s+){0,2}бот", True, 30),
    # --- площадки ---
    (r"(telegram|телеграм|тг|whats\s?app|вотс?ап|вацап|\bvk\b|\bвк\b|вконтакте|discord|дискорд|avito|авито|\bmax\b|макс)[\s-]?бот", True, 30),
    (r"бот\s+(для|под)\s+(telegram|телеграм|тг|whats\s?app|вотс?ап|\bvk\b|\bвк\b|discord|avito|авито)", True, 30),
    # --- мини-аппы ---
    (r"\bмини[\s-]?апп", True, 40),
    (r"\bmini\s?app\b", True, 40),
    (r"\btma\b", True, 30),
    (r"telegram\s+web\s?app", True, 35),
    (r"\bweb\s?app\b", True, 20),
    (r"(приложени\w+|апп\w*)\s+(в|внутри|для)\s+(телеграм|telegram|тг)", True, 35),
    # --- боль, которая решается ботом или аппом ---
    (r"(запись|бронирован\w+|каталог|витрин\w+|магазин|оплат\w+|подписк\w+|личный кабинет)\s+(в|внутри|через)\s+(телеграм|тг|боте)", True, 30),
    (r"автоматизир\w+\s+(\w+\s+){0,3}(продаж|заказ|записи|поддержк|переписк)", True, 20),
    # между «бот» и «сломался» часто стоит уточнение: «бот записи сломался»
    (r"бот\w*\s+(\w+\s+){0,3}(сломал|не работает|глючит|отвалил|перестал|упал)", True, 30),
    # Слов «ищу подрядчика/исполнителя» в наборе намеренно нет: они ловят
    # любой фриланс-заказ. Пост обязан упоминать бота или апп — иначе это
    # не наша ниша. «Бот сломался, ищем подрядчика» ловится строкой выше.
]

# Сработало любое — пост не лид. Только однозначные маркеры: спорные слова
# вроде «вакансия» намеренно не берём, они встречаются и в настоящих заказах.
DEFAULT_STOP_WORDS: list[tuple[str, bool]] = [
    # наём в штат
    (r"(зарплат\w+|з/п|оклад)\s*[:\-—]?\s*(от\s*)?\d", True),
    (r"оформлени\w+\s+(по\s+)?(тк|трудов)", True),
    (r"\bтк\s*рф\b", True),
    (r"трудов\w+\s+договор", True),
    (r"полн\w+\s+занятост", True),
    (r"график\s+работы", True),
    (r"соц\.?\s?пакет", True),
    (r"опыт\s+работы\s+от\s+\d", True),
    (r"испытательн\w+\s+срок", True),
    (r"(оплачиваем\w+\s+)?отпуск\s+\d", True),
    # резюме и самопрезентации исполнителей
    (r"#resume|#резюме", True),
    (r"(ищу|ищем|в поиске)\s+работ", True),
    (r"рассмотрю\s+предложени", True),
    (r"мо[ёе]\s+портфолио", True),
    (r"готов\s+к\s+(сотрудничеству|работе)", True),
    (r"\bcv\b|\bрезюме\b", True),
    # реклама таких же исполнителей
    (r"(делаем|делаю|разрабатываем|разрабатываю|пишем|пишу)\s+(\w+\s+){0,3}(бот|сайт|приложен)", True),
    (r"(наша|наше|мы)\s+(студия|агентство|команда)", True),
    (r"(услуги|прайс)\s+(разработк|студи)", True),
    # то же, но от первого лица и без слова «делаю»:
    # «Сайты и презентации для вашего бизнеса… Помогу представить предложение»
    (r"для\s+ваш(его|ей)\s+(бизнеса|компании|проекта)", True),
    (r"(помогу|поможем)\s+(\w+\s+){0,3}(запустить|сделать|создать|оформить|представить|настроить)", True),
    (r"(мои|наши)\s+услуги|прайс[-\s]?лист", True),
    # Исполнители часто рекламируются вопросом клиента: «Нужен бот? Я помогу!».
    # Без этих строк такая реклама выглядит как заказ и лезет в ленту.
    (r"\bя\s+помогу\b", True),
    (r"(предоставляю|оказываю|предлагаю)\s+(\w+\s+){0,2}услуг", True),
    (r"(возьмусь|берусь)\s+за\s+(\w+\s+){0,2}(работ|проект|доработк|разработк|задач)", True),
    # заведомо не наши темы
    (r"(казино|casino|ставк\w+ на спорт|букмекер|арбитраж трафика|нюдс|пирамид)", True),
    # «лёгкий заработок» — этот мусор маскируется под поиск исполнителей
    (r"(простые|простых|лёгк\w+|легк\w+)\s+задани", True),
    (r"опыт\s+не\s+(требуется|нужен|важен)", True),
    (r"выплат\w*\s+(без\s+задержек|ежедневн|на\s+карту)", True),
    (r"(деньги|доход|заработок)\s+(на\s+карту|от\s+\d)", True),
    (r"без\s+вложений", True),
    (r"\d\s*[-–]\s*\d\s*(тыс|к)\s+в\s+день", True),
    # Инфобизнес: «Выспался. Создал чат-бота. Заработал +17.000. Пока ты едешь…».
    # Обращение к читателю на «ты» — надёжный маркер: заказчик так не пишет.
    (r"пока\s+ты\b", True),
    (r"из\s+дома\s+по\s+\d+\s*к\b", True),
    (r"на\s+окладе\s+\d", True),
    (r"заработал\s*\+?\s*\d", True),
    # дайджесты вакансий: «Выпуск вакансий от 26.02.2026»
    (r"(выпуск|подборка|дайджест)\s+вакансий", True),
]


class KeywordMatcher:
    """Компилирует ключевики и стоп-слова из БД, держит их в памяти с TTL."""

    def __init__(self) -> None:
        self._compiled: list[tuple[str, re.Pattern[str], int]] = []
        self._stop: list[tuple[str, re.Pattern[str]]] = []
        self._loaded_at: float = 0.0

    async def refresh(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._loaded_at < CACHE_TTL_SEC:
            return

        async with SessionLocal() as session:
            rows = (
                await session.execute(select(Keyword).where(Keyword.enabled.is_(True)))
            ).scalars().all()

        compiled: list[tuple[str, re.Pattern[str], int]] = []
        stop: list[tuple[str, re.Pattern[str]]] = []

        for kw in rows:
            pattern = kw.pattern if kw.is_regex else re.escape(kw.pattern)
            try:
                rx = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                log.warning("битый regex %r: %s", kw.pattern, exc)
                continue
            if kw.is_stop:
                stop.append((kw.pattern, rx))
            else:
                compiled.append((kw.pattern, rx, kw.weight))

        self._compiled = compiled
        self._stop = stop
        self._loaded_at = time.monotonic()
        log.debug("ключевиков %d, стоп-слов %d", len(compiled), len(stop))

    async def stop_hit(self, text: str) -> str | None:
        """Первое сработавшее стоп-слово. None — пост не заблокирован."""
        await self.refresh()
        for name, rx in self._stop:
            if rx.search(text):
                return name
        return None

    async def match(self, text: str) -> list[str]:
        """Сработавшие ключевики. Пустой список — пост мимо.

        Стоп-слово перевешивает любое количество совпадений.
        """
        await self.refresh()
        if not text:
            return []
        if await self.stop_hit(text):
            return []
        return [name for name, rx, _ in self._compiled if rx.search(text)]

    async def weight(self, text: str) -> int:
        await self.refresh()
        if await self.stop_hit(text):
            return 0
        return sum(w for _, rx, w in self._compiled if rx.search(text))


matcher = KeywordMatcher()
