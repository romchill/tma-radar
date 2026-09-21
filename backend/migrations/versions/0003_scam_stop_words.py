"""Стоп-слова против «лёгкого заработка».

Скам маскируется под поиск исполнителей («ищем исполнителей простых заданий»)
и проходил положительный фильтр.

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_STOP = [
    r"(простые|простых|лёгк\w+|легк\w+)\s+задани",
    r"опыт\s+не\s+(требуется|нужен|важен)",
    r"выплат\w*\s+(без\s+задержек|ежедневн|на\s+карту)",
    r"(деньги|доход|заработок)\s+(на\s+карту|от\s+\d)",
    r"без\s+вложений",
    r"\d\s*[-–]\s*\d\s*(тыс|к)\s+в\s+день",
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
