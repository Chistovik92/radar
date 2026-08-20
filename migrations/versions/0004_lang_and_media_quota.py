"""Язык интерфейса и квоты загрузки видео.

Поле `lang` пустое у всех, кто уже пользуется ботом, — это и есть признак
«язык не выбран»: при первом обращении после обновления система спросит.
Заполнять его русским по умолчанию нельзя, иначе выбор никогда не будет
предложен, а англоязычные останутся с русским интерфейсом навсегда.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_lang_and_media_quota"
down_revision = "0003_promo_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("lang", sa.String(length=2), nullable=False, server_default=""),
    )
    op.create_table(
        "media_quota",
        sa.Column("user_key", sa.String(length=64), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_until", sa.String(length=32), nullable=False,
                  server_default=""),
        sa.PrimaryKeyConstraint("user_key"),
    )


def downgrade() -> None:
    op.drop_table("media_quota")
    op.drop_column("users", "lang")
