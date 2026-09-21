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
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
    _insert_ignoring_existing(
        keywords,
        [
            {"pattern": p, "is_regex": True, "is_stop": True, "weight": 0, "enabled": True}
            for p in NEW_STOP
        ],
    )


def downgrade() -> None:
    keywords = sa.table("keywords", sa.column("pattern", sa.String))
    op.execute(keywords.delete().where(keywords.c.pattern.in_(NEW_STOP)))


def _insert_ignoring_existing(table, rows) -> None:
    """Вставка, которая не спорит с уже засеянными строками.

    Ключевики засеваются несколькими миграциями подряд, и часть из них
    импортирует актуальный список из кода приложения. На чистой базе ранняя
    миграция засевает уже дополненный набор, и следующая падает на уникальном
    индексе по pattern. Пропускаем то, что на месте.
    """
    if not rows:
        return
    op.execute(
        pg_insert(table).values(rows).on_conflict_do_nothing(index_elements=["pattern"])
    )
