"""Промокоды партнёрских проектов.

Уникальность пары «проект + пользователь» задана в схеме, а не только
в коде: правило «один код на человека на проект» должно держаться даже
при двух одновременных нажатиях.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_promo_codes"
down_revision = "0002_short_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project", sa.String(length=32), nullable=False),
        sa.Column("user_key", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project", "user_key", name="uq_promo_project_user"),
    )
    op.create_index("ix_promo_codes_project", "promo_codes", ["project"])
    op.create_index("ix_promo_codes_user_key", "promo_codes", ["user_key"])
    op.create_index("ix_promo_codes_code", "promo_codes", ["code"])


def downgrade() -> None:
    op.drop_index("ix_promo_codes_code", table_name="promo_codes")
    op.drop_index("ix_promo_codes_user_key", table_name="promo_codes")
    op.drop_index("ix_promo_codes_project", table_name="promo_codes")
    op.drop_table("promo_codes")
