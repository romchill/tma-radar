"""Сужение набора: границы слова и отказ от общефрилансовых формулировок.

Две правки по итогам реальных постов:

1. Каналы вешают на посты категорийные хештеги вроде #скрипты_боты_miniapp.
   Без границы слова любой пост такого канала считался мини-аппом — так
   «Переделать прошивки на плате» попало в ленту.

2. «Ищу подрядчика/исполнителя» ловит любой фриланс-заказ: карточки товаров,
   дизайн, тексты. К ботам и мини-аппам это отношения не имеет.

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# было -> стало
RENAMED = [
    (r"мини[\s-]?апп", r"\bмини[\s-]?апп"),
    (r"mini\s?app", r"\bmini\s?app\b"),
    (r"web\s?app", r"\bweb\s?app\b"),
]

DROPPED = [
    r"(ищу|ищем|нужен|требуется)\s+(\w+\s+){0,2}(подрядчик|исполнител)\w*",
    r"(ищу|ищем)\s+(нового\s+)?подрядчика",
]


def _table() -> sa.Table:
    return sa.table("keywords", sa.column("pattern", sa.String))


def upgrade() -> None:
    keywords = _table()
    for old, new in RENAMED:
        _rename_keyword(old, new)
    op.execute(keywords.delete().where(keywords.c.pattern.in_(DROPPED)))


def downgrade() -> None:
    keywords = _table()
    for old, new in RENAMED:
        op.execute(keywords.update().where(keywords.c.pattern == new).values(pattern=old))


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
