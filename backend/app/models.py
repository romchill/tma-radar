"""Схема БД.

Поток данных:
    sources -> raw_messages -(scorer)-> leads -> lead_events
                    ^                     |
                 keywords              contacts (антидубль)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# ---------------------------------------------------------------- статусы

class RawStatus:
    PENDING = "pending"      # ждёт скоринга
    PROCESSING = "processing"  # взято скорером в работу
    SCORED = "scored"        # LLM признала лидом -> создан lead
    REJECTED = "rejected"    # LLM: не лид
    DUPLICATE = "duplicate"  # автор уже в работе (cooldown)
    ERROR = "error"

    ALL = (PENDING, PROCESSING, SCORED, REJECTED, DUPLICATE, ERROR)


class LeadStatus:
    NEW = "new"
    CONTACTED = "contacted"
    DIALOG = "dialog"
    OFFER = "offer"
    DEAL = "deal"
    LOST = "lost"
    TRASH = "trash"

    ALL = (NEW, CONTACTED, DIALOG, OFFER, DEAL, LOST, TRASH)
    PIPELINE = (NEW, CONTACTED, DIALOG, OFFER, DEAL)


# ---------------------------------------------------------------- таблицы

class Source(Base):
    """Источник лидов: чат/канал в тг, rss-лента биржи и т.п."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="tg_chat")  # tg_chat | rss | api
    tg_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(256))
    url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text)
    # дата самого свежего поста: по ней видно, что источник умер
    last_post_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Keyword(Base):
    """Предфильтр перед LLM: дешёвый отсев по подстроке/regex."""

    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(256), unique=True)
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # стоп-слово: сработало — пост отбрасывается, сколько бы ни совпало обычных
    is_stop: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    weight: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(Base):
    """Один автор = один контакт. Нужен для антидубля и истории."""

    __tablename__ = "contacts"

    tg_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(String(256))
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    leads_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_lead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawMessage(Base):
    """Сырое пойманное сообщение. Оно же — очередь для скорера."""

    __tablename__ = "raw_messages"
    __table_args__ = (
        UniqueConstraint("tg_chat_id", "tg_message_id", name="uq_raw_chat_message"),
        Index("ix_raw_status_id", "status", "id"),
        Index("ix_raw_posted_at", "posted_at"),
        # по ссылке ищется тот же заказ, пойманный другим источником
        Index("ix_raw_link", "link"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))

    tg_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    chat_title: Mapped[str | None] = mapped_column(String(256))

    author_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    author_username: Mapped[str | None] = mapped_column(String(128))
    author_name: Mapped[str | None] = mapped_column(String(256))

    text: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    # готовая ссылка «написать»: t.me у телеграма, vk.com у ВК, None если контакта нет
    contact_url: Mapped[str | None] = mapped_column(Text)
    matched: Mapped[list | None] = mapped_column(JSONB)  # какие ключевики сработали

    status: Mapped[str] = mapped_column(
        String(16), default=RawStatus.PENDING, server_default=RawStatus.PENDING
    )
    error: Mapped[str | None] = mapped_column(Text)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead: Mapped[Lead | None] = relationship(back_populates="raw", uselist=False)


class Lead(Base):
    """Результат работы LLM: карточка, с которой ты работаешь в мини-аппе."""

    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_status_score", "status", "score"),
        Index("ix_leads_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raw_message_id: Mapped[int] = mapped_column(
        ForeignKey("raw_messages.id", ondelete="CASCADE"), unique=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.tg_user_id", ondelete="SET NULL"), index=True
    )

    # что вытащила модель
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    niche: Mapped[str | None] = mapped_column(String(128))
    budget_hint: Mapped[str | None] = mapped_column(String(128))
    urgency: Mapped[str | None] = mapped_column(String(16))  # low | medium | high
    pain: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    why: Mapped[str | None] = mapped_column(Text)

    # воронка
    status: Mapped[str] = mapped_column(
        String(16), default=LeadStatus.NEW, server_default=LeadStatus.NEW
    )
    draft_message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    deal_amount: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw: Mapped[RawMessage] = relationship(back_populates="lead", lazy="joined")


class LeadEvent(Base):
    """История: смена статуса, отправка, заметка."""

    __tablename__ = "lead_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """Настройки, редактируемые прямо из мини-аппа (промпты, пороги)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
