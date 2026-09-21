"""Стоп-слова против рекламы исполнителей от первого лица.

Реальные посты из групп ВК с открытой стеной: «Нужен крутой сайт, магазин или
Telegram-бот? Я помогу!», «Предоставляю услуги: создание сайтов», «Возьмусь за
доработку». Исполнители рекламируются, цитируя вопрос клиента, поэтому такой
текст выглядит как заказ и проходил положительный фильтр.

Revision ID: 0008
Revises: 0007
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_STOP = [
    r"\bя\s+помогу\b",
    r"(предоставляю|оказываю|предлагаю)\s+(\w+\s+){0,2}услуг",
    r"(возьмусь|берусь)\s+за\s+(\w+\s+){0,2}(работ|проект|доработк|разработк|задач)",
]


def upgrade() -> None:
    keywords = sa.table(
        "keywords",
        sa.column("pattern", sa.String),
        sa.column("is_regex", sa.Boolean),
        sa.column("is_stop", sa.Boolean),
        sa.column("weight", sa.Integer),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        keywords,
        [
            {"pattern": p, "is_regex": True, "is_stop": True, "weight": 0, "enabled": True}
            for p in NEW_STOP
        ],
    )


def downgrade() -> None:
    keywords = sa.table("keywords", sa.column("pattern", sa.String))
    op.execute(keywords.delete().where(keywords.c.pattern.in_(NEW_STOP)))
