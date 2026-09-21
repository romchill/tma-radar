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
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
    _rename_keyword(OLD, NEW)
    _insert_ignoring_existing(
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
