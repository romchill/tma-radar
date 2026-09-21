"""Стоп-слова против рекламы услуг от первого лица.

Старый набор ловил «делаю ботов», но не «Сайты и презентации для вашего
бизнеса… Помогу представить предложение» — реальный пост из vk.ru/freelance.vacancy.
Это исполнитель, предлагающий услуги, а не заказчик.

Revision ID: 0007
Revises: 0006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_STOP = [
    r"для\s+ваш(его|ей)\s+(бизнеса|компании|проекта)",
    r"(помогу|поможем)\s+(\w+\s+){0,3}(запустить|сделать|создать|оформить|представить|настроить)",
    r"(мои|наши)\s+услуги|прайс[-\s]?лист",
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
