"""Стоп-слова против инфобизнес-спама.

Реальный пост из t.me/vdhl_good: «Веду 3 проекта из дома по 40к — на карте
+120.000 в месяц, пока ты сидишь на окладе 60к». Такое рекламируется через
бота, поэтому слово «бот» в тексте есть и пост проходил положительный фильтр.

Revision ID: 0009
Revises: 0008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_STOP = [
    r"пока\s+ты\s+(сидишь|работаешь|тратишь)",
    r"из\s+дома\s+по\s+\d+\s*к\b",
    r"на\s+окладе\s+\d",
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
