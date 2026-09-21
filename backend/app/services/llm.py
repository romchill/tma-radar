"""Обёртка над Anthropic API.

Скоринг идёт через tool use с принудительным вызовом инструмента — так модель
физически не может вернуть что-то кроме валидного JSON по нашей схеме.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from anthropic import APIStatusError, AsyncAnthropic, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.services import prompts

log = logging.getLogger(__name__)

_client: AsyncAnthropic | None = None

MAX_TEXT_CHARS = 4000


def available() -> bool:
    """Есть ли ключ. Без него система работает в бесплатном режиме:
    оценка по весу ключевиков, черновики не генерируются."""
    return bool(settings.anthropic_api_key)


def client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)
    return _client


@dataclass
class Assessment:
    is_lead: bool
    score: int
    niche: str = ""
    summary: str = ""
    pain: str = ""
    budget_hint: str | None = None
    urgency: str = "low"
    why: str = ""
    usage: dict = field(default_factory=dict)


_retry = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((RateLimitError, APIStatusError)),
)


def _context_block(chat_title: str | None, author_name: str | None) -> str:
    return (
        f"Чат: {chat_title or 'неизвестно'}\n"
        f"Автор: {author_name or 'неизвестно'}"
    )


@_retry
async def assess(
    text: str,
    *,
    chat_title: str | None = None,
    author_name: str | None = None,
    system: str | None = None,
    model: str | None = None,
) -> Assessment:
    """Оценивает сообщение. Бросает исключение, если API недоступно."""
    user_prompt = f"{_context_block(chat_title, author_name)}\n\nСообщение:\n---\n{text[:MAX_TEXT_CHARS]}\n---"

    resp = await client().messages.create(
        model=model or settings.model_scorer,
        max_tokens=700,
        system=system or prompts.SCORER_SYSTEM,
        tools=[prompts.SCORER_TOOL],
        tool_choice={"type": "tool", "name": "save_assessment"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    payload: dict | None = None
    for block in resp.content:
        if block.type == "tool_use" and block.name == "save_assessment":
            payload = block.input
            break

    if payload is None:
        raise RuntimeError("модель не вызвала save_assessment")

    budget = (payload.get("budget_hint") or "").strip()
    return Assessment(
        is_lead=bool(payload.get("is_lead")),
        score=max(0, min(100, int(payload.get("score", 0)))),
        niche=(payload.get("niche") or "")[:128],
        summary=payload.get("summary") or "",
        pain=payload.get("pain") or "",
        budget_hint=budget[:128] or None,
        urgency=payload.get("urgency") or "low",
        why=payload.get("why") or "",
        usage={
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
    )


@_retry
async def write_outreach(
    *,
    text: str,
    niche: str | None = None,
    pain: str | None = None,
    chat_title: str | None = None,
    author_name: str | None = None,
    extra: str | None = None,
    system: str | None = None,
    model: str | None = None,
) -> str:
    """Генерирует первое сообщение в ЛС."""
    resp = await client().messages.create(
        model=model or settings.model_writer,
        max_tokens=500,
        system=system or prompts.WRITER_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": prompts.writer_user_prompt(
                    text=text[:MAX_TEXT_CHARS],
                    niche=niche,
                    pain=pain,
                    chat_title=chat_title,
                    author_name=author_name,
                    extra=extra,
                ),
            }
        ],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
