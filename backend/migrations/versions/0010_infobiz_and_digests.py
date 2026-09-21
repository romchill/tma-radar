"""Стоп-слова: инфобизнес на «ты» и дайджесты вакансий.

Реальные посты, пролезшие в ленту:
  «Выспался. Создал чат-бота. Заработал +17.000 рублей. Пока ты едешь…» — инфобиз;
  «Выпуск вакансий от 26.02.2026 г.» — дайджест найма в штат.

Обращение к читателю на «ты» — надёжный маркер рекламы: заказчик, которому
нужен бот, так не пишет. Прошлый шаблон перечислял глаголы и не покрыл «едешь».

Revision ID: 0010
Revises: 0009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = r"пока\s+ты\s+(сидишь|работаешь|тратишь)"
NEW = r"пока\s+ты\b"
EXTRA = [
    r"заработал\s*\+?\s*\d",
    r"(выпуск|подборка|дайджест)\s+вакансий",
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
    op.execute(keywords.update().where(keywords.c.pattern == OLD).values(pattern=NEW))
    op.bulk_insert(
        keywords,
        [
            {"pattern": p, "is_regex": True, "is_stop": True, "weight": 0, "enabled": True}
            for p in EXTRA
        ],
    )


def downgrade() -> None:
    keywords = sa.table("keywords", sa.column("pattern", sa.String))
    op.execute(keywords.update().where(keywords.c.pattern == NEW).values(pattern=OLD))
    op.execute(keywords.delete().where(keywords.c.pattern.in_(EXTRA)))
