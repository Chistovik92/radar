"""Схема базы данных.

Перенос с JSON-хранилища версий 3.x: структура повторяет прежние сущности,
чтобы миграция была однозначной, но добавляет то, чего в файле быть не могло —
историю событий и доставок, а также журнал источников.

Идентификатор пользователя — это Telegram ID, поэтому первичный ключ задаётся
явно и не генерируется базой.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Базовый класс моделей."""

    type_annotation_map = {dict[str, Any]: JSONB, list[str]: JSONB}


class User(Base):
    """Пользователь любой платформы.

    Ключ суррогатный, а не Telegram ID: с версии 4.2 бот работает сразу
    в двух мессенджерах, и один и тот же числовой идентификатор может
    принадлежать разным людям в Telegram и MAX. Пара (platform, external_id)
    уникальна и служит естественным ключом.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), default="telegram", index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    weather_mode: Mapped[str] = mapped_column(String(16), default="interval")
    weather_interval: Mapped[int] = mapped_column(Integer, default=0)
    weather_time: Mapped[str] = mapped_column(String(8), default="08:00")
    weather_format: Mapped[str] = mapped_column(String(8), default="text")  # text | image
    last_weather: Mapped[int] = mapped_column(BigInteger, default=0)
    last_fixed_date: Mapped[str] = mapped_column(String(16), default="")

    # Задел под 4.1: тихие часы и антиспам.
    quiet_from: Mapped[str] = mapped_column(String(8), default="")
    quiet_to: Mapped[str] = mapped_column(String(8), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    locations: Mapped[list["Location"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_user_identity"),
    )


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lon: Mapped[float] = mapped_column(Float, default=0.0)
    street: Mapped[str] = mapped_column(String(160), default="")
    house: Mapped[str] = mapped_column(String(32), default="")
    city: Mapped[str] = mapped_column(String(120), default="", index=True)
    district: Mapped[str] = mapped_column(String(120), default="")
    region: Mapped[str] = mapped_column(String(120), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    added_by: Mapped[int] = mapped_column(BigInteger, default=0)  # кто добавил, 0 — сам

    user: Mapped[User] = relationship(back_populates="locations")

    __table_args__ = (UniqueConstraint("user_id", "public_id", name="uq_location_public"),)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), default="tg")  # tg | rss | vk
    ref: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    added_by: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    fail_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("kind", "ref", name="uq_source_ref"),)


class Event(Base):
    """Разобранное сообщение источника. Основа истории по адресу."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    digest: Mapped[str] = mapped_column(String(40), unique=True, index=True)

    source: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(8), default="tg")
    link: Mapped[str] = mapped_column(Text, default="")

    categories: Mapped[list[str]] = mapped_column(JSONB, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    scope: Mapped[str] = mapped_column(String(16), default="city")
    all_clear: Mapped[bool] = mapped_column(Boolean, default=False)

    city: Mapped[str] = mapped_column(String(120), default="", index=True)
    region: Mapped[str] = mapped_column(String(120), default="")
    districts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    streets: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)

    summary: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(16), default="ai")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    __table_args__ = (Index("ix_events_city_created", "city", "created_at"),)


class Delivery(Base):
    """Кому и по какой локации событие было отправлено.

    Нужна для истории «что приходило по этому адресу» и для антиспама:
    повторную отправку того же события той же локации легко отсечь.
    """

    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("locations.id", ondelete="SET NULL"), default=None
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    delivered: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("event_id", "user_id", "location_id", name="uq_delivery"),
    )


class Feature(Base):
    """Переключатели возможностей, доступные суперадминистратору в боте.

    Значение по умолчанию задаётся в коде, а запись в этой таблице его
    переопределяет — так функцию можно включить или выключить без обновления
    версии и без перезапуска контейнера.
    """

    __tablename__ = "features"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    changed_by: Mapped[int] = mapped_column(BigInteger, default=0)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Meta(Base):
    """Служебные пары ключ-значение: версия анонса, флаги миграций."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
