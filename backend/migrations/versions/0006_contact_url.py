"""Прямая ссылка на контакт лида.

До сих пор «написать» собиралось как t.me/<author_username>. С появлением ВК
этого мало: контакт там — профиль vk.com, а у постов с бирж контакта нет вовсе.
Храним готовую ссылку, а приложение просто открывает её.

Revision ID: 0006
Revises: 0005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("raw_messages", sa.Column("contact_url", sa.Text(), nullable=True))

    # у уже собранных телеграм-лидов контакт выводится из username
    op.execute(
        """
        UPDATE raw_messages
           SET contact_url = 'https://t.me/' || author_username
         WHERE author_username IS NOT NULL
           AND contact_url IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("raw_messages", "contact_url")
