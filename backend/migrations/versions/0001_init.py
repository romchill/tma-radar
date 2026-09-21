"""Начальная схема + сид ключевых слов.

Revision ID: 0001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="tg_chat"),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("username", sa.String(128), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "keywords",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pattern", sa.String(256), nullable=False, unique=True),
        sa.Column("is_regex", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "contacts",
        sa.Column("tg_user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(128), nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("leads_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_lead_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "raw_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("chat_title", sa.String(256), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("author_username", sa.String(128), nullable=True),
        sa.Column("author_name", sa.String(256), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("matched", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tg_chat_id", "tg_message_id", name="uq_raw_chat_message"),
    )
    op.create_index("ix_raw_status_id", "raw_messages", ["status", "id"])
    op.create_index("ix_raw_posted_at", "raw_messages", ["posted_at"])
    op.create_index("ix_raw_messages_author_id", "raw_messages", ["author_id"])

    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "raw_message_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "contact_id",
            sa.BigInteger(),
            sa.ForeignKey("contacts.tg_user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("niche", sa.String(128), nullable=True),
        sa.Column("budget_hint", sa.String(128), nullable=True),
        sa.Column("urgency", sa.String(16), nullable=True),
        sa.Column("pain", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("draft_message", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("deal_amount", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_followup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_leads_status_score", "leads", ["status", "score"])
    op.create_index("ix_leads_created_at", "leads", ["created_at"])
    op.create_index("ix_leads_score", "leads", ["score"])
    op.create_index("ix_leads_contact_id", "leads", ["contact_id"])
    op.create_index("ix_leads_next_followup_at", "leads", ["next_followup_at"])

    op.create_table(
        "lead_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "lead_id", sa.BigInteger(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lead_events_lead_id", "lead_events", ["lead_id"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Ключевики засевает миграция 0002: она знает и про стоп-слова.
    # Здесь засева нет намеренно — _seed_keywords() брала список из
    # живого кода, тот с тех пор дополнялся, и на чистой базе 0002
    # падала на вставке уже засеянных строк.


def _seed_keywords() -> None:
    from app.services.matcher import DEFAULT_KEYWORDS

    keywords = sa.table(
        "keywords",
        sa.column("pattern", sa.String),
        sa.column("is_regex", sa.Boolean),
        sa.column("weight", sa.Integer),
    )
    op.bulk_insert(
        keywords,
        [
            {"pattern": pattern, "is_regex": is_regex, "weight": weight}
            for pattern, is_regex, weight in DEFAULT_KEYWORDS
        ],
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("lead_events")
    op.drop_table("leads")
    op.drop_table("raw_messages")
    op.drop_table("contacts")
    op.drop_table("keywords")
    op.drop_table("sources")
