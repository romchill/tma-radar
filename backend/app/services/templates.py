"""Черновик первого сообщения без модели.

Без ключа Anthropic писать текст некому, но оставлять пустое поле — значит
заставлять сочинять с нуля на каждом лиде. Шаблон закрывает 80%: цепляет за
конкретную задачу клиента, предлагает понятный следующий шаг и оставляет
место для правки перед отправкой.

Шаблоны намеренно не обещают опыт и кейсы, которых может не быть: враньё
в первом сообщении вскрывается на втором.
"""

from __future__ import annotations

import re

# --- определение типа заказа по тексту -------------------------------------

# между «бот» и «сломался» часто стоит уточнение: «бот записи сломался»
BROKEN = re.compile(
    r"бот\w*\s+(\w+\s+){0,3}(сломал|не работает|глючит|отвалил|перестал|упал)", re.I
)
MINI_APP = re.compile(r"(\bмини[\s-]?апп|\bmini\s?app|\btma\b|приложени\w+\s+(в|внутри|для)\s+(телеграм|тг))", re.I)
PLATFORM = re.compile(
    r"(whats\s?app|вотс?ап|вацап|\bvk\b|\bвк\b|вконтакте|discord|дискорд|avito|авито|\bmax\b)",
    re.I,
)

# строка-шапка биржи: рубрика, бюджет, срок — но не задача
META_LINE = re.compile(
    r"(₽|руб\b|\bдн\.?\b|\bдней\b|бюджет\s*[:—-]|\bсрок\s*[:—-])",
    re.I,
)

PLATFORM_NAMES = {
    "whatsapp": "WhatsApp", "whats app": "WhatsApp", "вотсап": "WhatsApp",
    "вотсапп": "WhatsApp", "вацап": "WhatsApp",
    "vk": "VK", "вк": "VK", "вконтакте": "VK",
    "discord": "Discord", "дискорд": "Discord",
    "avito": "Avito", "авито": "Avito", "max": "Max",
}

# --- шаблоны ----------------------------------------------------------------
# {task} — задача клиента его же словами, {extra} — постоянная вводная о себе.

TEMPLATES: dict[str, str] = {
    "broken": (
        "Здравствуйте. Увидел, что у вас перестал работать бот.\n\n"
        "Могу посмотреть, что именно сломалось, и починить. Если код внутри "
        "совсем плохой — скажу честно, что дешевле переписать, чем латать.\n\n"
        "Опишете, что перестало работать? Посмотрю бесплатно и скажу срок."
    ),
    "mini_app": (
        "Здравствуйте. Увидел вашу задачу: {task}\n\n"
        "Делаю мини-аппы для Telegram — всё работает внутри мессенджера, "
        "клиенту не нужно никуда переходить и ничего устанавливать.\n\n"
        "Могу собрать прототип, чтобы вы посмотрели вживую до оплаты. Интересно?"
    ),
    "platform_bot": (
        "Здравствуйте. Увидел вашу задачу: {task}\n\n"
        "Делаю ботов под {platform} — возьмусь и разберусь в деталях по ходу.\n\n"
        "Расскажете подробнее, что бот должен уметь? Прикину сроки."
    ),
    "bot": (
        "Здравствуйте. Увидел вашу задачу: {task}\n\n"
        "Делаю ботов и мини-аппы для Telegram и других площадок. "
        "Работаю сам, поэтому без менеджеров и долгих согласований.\n\n"
        "Расскажете подробнее, что должно получиться? Прикину сроки."
    ),
    "generic": (
        "Здравствуйте. Увидел вашу задачу: {task}\n\n"
        "Делаю ботов и мини-аппы — под Telegram, WhatsApp, VK и Avito.\n\n"
        "Если задача ещё актуальна, расскажите подробнее — прикину сроки."
    ),
}

MAX_TASK_LEN = 120


def _lines(text: str) -> list[str]:
    """Строки поста без оформления и без служебной шапки биржи.

    Шапка вида «📁 Скрипты, боты и mini apps | 💰 20 000 ₽ | ⏰ 10 дн.» — это
    рубрика и условия, а не задача. Её нельзя ни показывать клиенту как его же
    слова, ни использовать для выбора шаблона: из-за слов «mini apps» в рубрике
    заказ на WhatsApp-бота определялся как мини-апп.
    """
    body = re.sub(r"[📌📝💳🌐〰️⏰💰📁🔺🔻⚪️✅❗️‼️]+", " ", text)
    body = re.sub(r"#\S+", " ", body)

    parts = re.split(r"\n+|(?<=[.!?])\s+", body)
    cleaned = [re.sub(r"\s+", " ", p).strip(" .,:;—-|") for p in parts]
    return [p for p in cleaned if p and not META_LINE.search(p)]


def _clean_task(text: str) -> str:
    """Короткая выжимка задачи словами самого клиента."""
    lines = _lines(text)
    task = next((p for p in lines if len(p) > 25), "")
    if not task:
        task = next((p for p in lines if p), re.sub(r"\s+", " ", text).strip())

    if len(task) > MAX_TASK_LEN:
        task = task[:MAX_TASK_LEN].rsplit(" ", 1)[0] + "…"
    return task


def _platform(text: str) -> str | None:
    found = PLATFORM.search(text)
    if not found:
        return None
    return PLATFORM_NAMES.get(found.group(1).lower())


def pick_kind(text: str) -> str:
    # по тексту без шапки: рубрика биржи не должна решать за клиента
    body = " ".join(_lines(text)) or text

    if BROKEN.search(body):
        return "broken"
    # площадка важнее: «WhatsApp-бот» — это бот под WhatsApp, а не мини-апп,
    # даже если слово mini app мелькнуло где-то рядом
    if _platform(body):
        return "platform_bot"
    if MINI_APP.search(body):
        return "mini_app"
    if re.search(r"бот", body, re.I):
        return "bot"
    return "generic"


def build_draft(text: str, extra: str | None = None, templates: dict | None = None) -> str:
    """Собирает черновик под задачу клиента."""
    kind = pick_kind(text)
    template = (templates or TEMPLATES).get(kind) or TEMPLATES["generic"]

    draft = template.format(
        task=_clean_task(text),
        platform=_platform(text) or "нужную площадку",
    )

    if extra and extra.strip():
        draft += f"\n\n{extra.strip()}"

    return draft
