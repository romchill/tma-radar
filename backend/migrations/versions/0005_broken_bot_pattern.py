"""Починка ключевика «бот сломался».

Между «бот» и «сломался» почти всегда стоит уточнение — «бот записи сломался»,
«бот рассылки перестал работать». Старый шаблон требовал их подряд и такие
посты пропускал, хотя это самые конверсионные лиды: у человека уже есть бот,
он уже платил за него и ищет замену подрядчику.

Revision ID: 0005
Revises: 0004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = r"бот\s+(сломал|не работает|глючит|отвалил|перестал|упал)"
NEW = r"бот\w*\s+(\w+\s+){0,3}(сломал|не работает|глючит|отвалил|перестал|упал)"


def _table() -> sa.Table:
    return sa.table("keywords", sa.column("pattern", sa.String))


def upgrade() -> None:
    keywords = _table()
    op.execute(keywords.update().where(keywords.c.pattern == OLD).values(pattern=NEW))


def downgrade() -> None:
    keywords = _table()
    op.execute(keywords.update().where(keywords.c.pattern == NEW).values(pattern=OLD))
