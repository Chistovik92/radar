"""Начальная схема версии 4.0

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False, server_default="telegram"),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("username", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("weather_mode", sa.String(length=16), nullable=False, server_default="interval"),
        sa.Column("weather_interval", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weather_time", sa.String(length=8), nullable=False, server_default="08:00"),
        sa.Column("weather_format", sa.String(length=8), nullable=False, server_default="text"),
        sa.Column("last_weather", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_fixed_date", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("quiet_from", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("quiet_to", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_user_identity"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_platform", "users", ["platform"])
    op.create_index("ix_users_external_id", "users", ["external_id"])

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False, server_default="0"),
        sa.Column("lon", sa.Float(), nullable=False, server_default="0"),
        sa.Column("street", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("house", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("district", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("region", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("added_by", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "public_id", name="uq_location_public"),
    )
    op.create_index("ix_locations_user_id", "locations", ["user_id"])
    op.create_index("ix_locations_public_id", "locations", ["public_id"])
    op.create_index("ix_locations_city", "locations", ["city"])

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="tg"),
        sa.Column("ref", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("added_by", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "ref", name="uq_source_ref"),
    )
    op.create_index("ix_sources_pending", "sources", ["pending"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("digest", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="tg"),
        sa.Column("link", sa.Text(), nullable=False, server_default=""),
        sa.Column("categories", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="city"),
        sa.Column("all_clear", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("region", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("districts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("streets", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("engine", sa.String(length=16), nullable=False, server_default="ai"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("digest"),
    )
    op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_index("ix_events_city", "events", ["city"])
    op.create_index("ix_events_city_created", "events", ["city", "created_at"])

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", "location_id", name="uq_delivery"),
    )
    op.create_index("ix_deliveries_event_id", "deliveries", ["event_id"])
    op.create_index("ix_deliveries_user_id", "deliveries", ["user_id"])
    op.create_index("ix_deliveries_sent_at", "deliveries", ["sent_at"])

    op.create_table(
        "features",
        sa.Column("key", sa.String(length=48), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("changed_by", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "meta",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("meta")
    op.drop_table("features")
    op.drop_table("deliveries")
    op.drop_table("events")
    op.drop_table("sources")
    op.drop_table("locations")
    op.drop_table("users")
