"""Pydantic-схемы для API мини-аппа."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- leads

class LeadOut(ORMModel):
    id: int
    score: int
    niche: str | None = None
    budget_hint: str | None = None
    urgency: str | None = None
    pain: str | None = None
    summary: str | None = None
    why: str | None = None
    status: str
    draft_message: str | None = None
    notes: str | None = None
    deal_amount: int | None = None
    created_at: datetime
    contacted_at: datetime | None = None
    next_followup_at: datetime | None = None

    # из raw_message
    text: str = ""
    link: str | None = None
    chat_title: str | None = None
    author_id: int | None = None
    author_username: str | None = None
    author_name: str | None = None
    contact_url: str | None = None
    matched: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None

    @classmethod
    def from_lead(cls, lead) -> "LeadOut":
        raw = lead.raw
        return cls(
            **{k: getattr(lead, k) for k in (
                "id", "score", "niche", "budget_hint", "urgency", "pain", "summary",
                "why", "status", "draft_message", "notes", "deal_amount",
                "created_at", "contacted_at", "next_followup_at",
            )},
            text=raw.text if raw else "",
            link=raw.link if raw else None,
            chat_title=raw.chat_title if raw else None,
            author_id=raw.author_id if raw else None,
            author_username=raw.author_username if raw else None,
            author_name=raw.author_name if raw else None,
            contact_url=raw.contact_url if raw else None,
            matched=(raw.matched or []) if raw else [],
            posted_at=raw.posted_at if raw else None,
        )


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int
    limit: int
    offset: int


class LeadUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    draft_message: str | None = None
    deal_amount: int | None = None
    next_followup_at: datetime | None = None


class DraftRequest(BaseModel):
    extra: str | None = Field(default=None, max_length=1000)
    regenerate: bool = True


class DraftOut(BaseModel):
    draft_message: str


class EventOut(ORMModel):
    id: int
    kind: str
    payload: dict | None = None
    created_at: datetime


# ---------------------------------------------------------------- sources

class SourceOut(ORMModel):
    id: int
    kind: str
    tg_chat_id: int | None = None
    username: str | None = None
    title: str | None = None
    enabled: bool
    notes: str | None = None
    last_post_at: datetime | None = None
    leads_count: int = 0
    raw_count: int = 0


class SourceIn(BaseModel):
    """Адрес источника: t.me/name для телеграма, vk.com/name для ВК.

    Тип определяется по виду адреса, но его можно задать и явно.
    """

    username: str = Field(min_length=2, max_length=128)
    kind: str | None = None


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    notes: str | None = None


# ---------------------------------------------------------------- keywords

class KeywordOut(ORMModel):
    id: int
    pattern: str
    is_regex: bool
    is_stop: bool
    weight: int
    enabled: bool


class KeywordIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=256)
    is_regex: bool = False
    is_stop: bool = False
    weight: int = Field(default=10, ge=0, le=100)
    enabled: bool = True


class KeywordUpdate(BaseModel):
    pattern: str | None = Field(default=None, min_length=2, max_length=256)
    is_regex: bool | None = None
    is_stop: bool | None = None
    weight: int | None = Field(default=None, ge=0, le=100)
    enabled: bool | None = None


class KeywordTest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class KeywordTestOut(BaseModel):
    matched: list[str]
    weight: int
    blocked_by: str | None = None


# ---------------------------------------------------------------- прочее

class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class StatsOut(BaseModel):
    by_status: dict[str, int]
    leads_today: int
    leads_7d: int
    raw_by_status: dict[str, int]
    hot_open: int
    followups_due: int
    avg_score: float
    top_sources: list[dict]
    top_keywords: list[dict]


class MeOut(BaseModel):
    id: int
    username: str | None = None
    title: str
    is_admin: bool = True
    # есть ли ключ Anthropic: без него черновики собираются по шаблону
    ai_enabled: bool = False
