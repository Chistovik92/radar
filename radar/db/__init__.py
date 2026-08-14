"""Слой базы данных: модели, подключение, репозиторий."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from .engine import (
    check_schema_compatible,
    create_schema,
    ensure_schema,
    dispose,
    get_engine,
    session,
    session_factory,
    stamp_alembic,
    wait_ready,
)
from .models import Base, Delivery, Event, Feature, Location, Meta, Source, User

# Внимание: здесь нельзя экспортировать имена `engine`, `models`, `repo`,
# `importer` — они совпадают с именами подмодулей пакета и затенили бы их
# при `from radar.db import engine`.
__all__ = [
    "Base", "Delivery", "Event", "Feature", "Location", "Meta", "Source", "User",
    "create_schema", "dispose", "get_engine", "session", "session_factory",
    "stamp_alembic", "wait_ready",
]
