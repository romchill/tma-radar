"""Дата последнего поста в источнике.

Аудит показал, что 7 источников из 13 мертвы: @freelansim_ru молчал 570 дней
(Хабр Фриланс закрылся), @botrazrabotka — 1561 день, vk.com/club12188866 —
1805 дней. Радар исправно наполнял ленту заказами, которые давно забрали,
а ссылки на них уже не открывались.

Теперь сборщики пишут сюда дату свежайшего поста, и мёртвый источник видно
в приложении.

Revision ID: 0011
Revises: 0010
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sources", sa.Column("last_post_at", sa.DateTime(timezone=True), nullable=True)
    )
    # то, что уже собрано, даёт первое приближение
    op.execute(
        """
        UPDATE sources s
           SET last_post_at = sub.newest
          FROM (
                SELECT source_id, max(posted_at) AS newest
                  FROM raw_messages
                 WHERE source_id IS NOT NULL AND posted_at IS NOT NULL
                 GROUP BY source_id
               ) sub
         WHERE sub.source_id = s.id
        """
    )


def downgrade() -> None:
    op.drop_column("sources", "last_post_at")
