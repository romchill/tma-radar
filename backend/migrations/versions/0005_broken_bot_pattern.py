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
    _rename_keyword(OLD, NEW)


def downgrade() -> None:
    keywords = _table()
    op.execute(keywords.update().where(keywords.c.pattern == NEW).values(pattern=OLD))


def _rename_keyword(old: str, new: str) -> None:
    """Переименовать шаблон, а если новое имя уже занято — убрать старый.

    На чистой базе актуальный список засевается сразу целиком (миграция 0002
    берёт его из кода приложения), поэтому переименовывать бывает не во что:
    цель уже на месте. Прямой UPDATE в этом случае ломается об уникальный
    индекс по pattern.
    """
    op.execute(
        sa.text(
            "DELETE FROM keywords WHERE pattern = :old "
            "AND EXISTS (SELECT 1 FROM keywords k WHERE k.pattern = :new)"
        ).bindparams(old=old, new=new)
    )
    op.execute(
        sa.text("UPDATE keywords SET pattern = :new WHERE pattern = :old").bindparams(
            old=old, new=new
        )
    )
