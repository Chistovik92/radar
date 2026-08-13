"""Подключение к PostgreSQL: движок, фабрика сессий, ожидание готовности базы.

Функция называется `get_engine`, а не `engine`, намеренно: имя `engine`
занято самим модулем `radar.db.engine`, и экспорт одноимённой функции
из `radar/db/__init__.py` затенял бы модуль. Тогда `from radar.db import
engine` возвращал бы функцию, а обращение к `engine.wait_ready()` падало бы
с AttributeError уже в рантайме.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .. import config

log = logging.getLogger("radar.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            config.database_url(),
            echo=config.DB_ECHO,
            pool_size=config.DB_POOL_SIZE,
            max_overflow=config.DB_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """Сессия с автоматическим commit и откатом при ошибке."""
    factory = session_factory()
    async with factory() as active:
        try:
            yield active
            await active.commit()
        except Exception:
            await active.rollback()
            raise


async def wait_ready(attempts: int = 30, delay: float = 2.0) -> None:
    """Ждёт, пока PostgreSQL примет подключение.

    На слабом железе контейнер базы поднимается дольше бота, поэтому
    без ожидания первый запуск падал бы на ровном месте.
    """
    from sqlalchemy import text

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
            if attempt > 1:
                log.info("База ответила с попытки %d", attempt)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == 1:
                log.info("Жду готовности PostgreSQL…")
            await asyncio.sleep(delay)
    raise RuntimeError(f"PostgreSQL недоступен: {last}")


async def dispose() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
