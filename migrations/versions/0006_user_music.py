"""Музыкальное состояние пользователя сохраняется между перезапусками.

Здесь личные файлы, избранное внешнего каталога, история и настройки профиля.
До отдельного JSON-поля ``storage.save()`` молча терял весь слот ``music``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_user_music"
down_revision = "0005_subscription_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("music", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                  nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("users", "music")
