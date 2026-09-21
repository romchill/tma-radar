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
