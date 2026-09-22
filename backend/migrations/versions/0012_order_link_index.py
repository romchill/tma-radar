"""Индекс по ссылке на заказ — для склейки дублей.

Один заказ приходит дважды: напрямую с Kwork и постом в канале, который
Kwork перепечатывает. Склеиваются копии по ссылке, а значит на каждое новое
сообщение делается поиск по raw_messages.link. Пока строк сотни, это
незаметно, но таблица растёт на сотни записей в сутки.

Revision ID: 0012
Revises: 0011
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_raw_link", "raw_messages", ["link"])


def downgrade() -> None:
    op.drop_index("ix_raw_link", table_name="raw_messages")
