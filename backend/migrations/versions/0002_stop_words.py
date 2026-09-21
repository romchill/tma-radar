"""Стоп-слова и набор ключевиков под ниши «боты» и «мини-аппы».

Старый набор ловил «требуется разработчик» без привязки к боту или аппу и
тащил в ленту вакансии в штат. Здесь он заменяется на прицельный, плюс
появляются стоп-слова.

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# то, что засеяла миграция 0001 — убираем только это, чужое не трогаем
OLD_SEED = [
    r"мини[\s-]?апп",
    r"mini\s?app",
    r"\btma\b",
    r"web\s?app",
    r"тг[\s-]?апп",
    r"(нужен|ищу|ищем|требуется|нужны)\s+(\w+\s+){0,3}(разработчик|программист|кодер|команда|студия)",
    r"(бот|бота|ботов)\s+(под|для|на)\s+заказ",
    r"(напис|сдела|разработа|запусти)\w*\s+(\w+\s+){0,3}бот",
    r"телеграм[\s-]?(магазин|шоп|бот)",
    r"(личный кабинет|каталог|витрин\w+|запись|бронирован\w+)\s+(в|внутри)\s+(телеграм|тг)",
    r"(оплат\w+|эквайринг|подписк\w+)\s+(в|через)\s+(телеграм|тг|боте)",
    r"бот\s+(сломал|не работает|глючит|отвалил)",
    r"(ищу|ищем)\s+(нового\s+)?подрядчика",
    r"\bтз\b.{0,40}(бот|апп|приложен)",
    "телеграм приложение",
]


def upgrade() -> None:
    op.add_column(
        "keywords",
        sa.Column("is_stop", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_keywords_is_stop", "keywords", ["is_stop"])

    keywords = sa.table(
        "keywords",
        sa.column("pattern", sa.String),
        sa.column("is_regex", sa.Boolean),
        sa.column("is_stop", sa.Boolean),
        sa.column("weight", sa.Integer),
        sa.column("enabled", sa.Boolean),
    )

    # выкидываем старый сид вместе с пойманным по нему мусором
    op.execute(
        keywords.delete().where(keywords.c.pattern.in_(OLD_SEED))
    )

    from app.services.matcher import DEFAULT_KEYWORDS, DEFAULT_STOP_WORDS

    rows = [
        {"pattern": p, "is_regex": rx, "is_stop": False, "weight": w, "enabled": True}
        for p, rx, w in DEFAULT_KEYWORDS
    ] + [
        {"pattern": p, "is_regex": rx, "is_stop": True, "weight": 0, "enabled": True}
        for p, rx in DEFAULT_STOP_WORDS
    ]
    _insert_ignoring_existing(keywords, rows)


def downgrade() -> None:
    op.drop_index("ix_keywords_is_stop", table_name="keywords")
    op.drop_column("keywords", "is_stop")


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
