"""Общая подписка и медиаквота сохраняются в профиле пользователя.

До этой миграции значения жили только в памяти: перезапуск позволял получить
пробный период повторно и стирал выданные дни и дневной счётчик загрузок.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_subscription_state"
down_revision = "0004_lang_and_media_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("sub", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "users",
        sa.Column("media_quota", postgresql.JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("users", "media_quota")
    op.drop_column("users", "sub")
