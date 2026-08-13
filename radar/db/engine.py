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


class AuthenticationError(RuntimeError):
    """Пароль не подошёл — ждать бессмысленно, нужно вмешательство."""


def _is_auth_error(exc: BaseException) -> bool:
    """Отличает «пароль не тот» от «база ещё не поднялась».

    Различие принципиально: во втором случае надо ждать, в первом ожидание
    бесполезно — PostgreSQL запоминает пароль при первой инициализации тома,
    и правка .env на уже созданную базу ничего не меняет.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "invalidpassword", "password authentication failed",
        "invalidauthorizationspecification", "role \"", "не пройдена проверка подлинности",
        "authentication failed", "invalidcatalogname", "does not exist",
    )
    return any(marker in text for marker in markers)


async def wait_ready(attempts: int = 30, delay: float = 2.0) -> None:
    """Ждёт, пока PostgreSQL примет подключение.

    На слабом железе контейнер базы поднимается дольше бота, поэтому без
    ожидания первый запуск падал бы на ровном месте. Но причина неудачи
    печатается в лог: молчаливое ожидание не даёт понять, база не успела
    подняться или пароль не подошёл.
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
            reason = f"{type(exc).__name__}: {exc}"

            if _is_auth_error(exc):
                log.critical("PostgreSQL отклонил подключение: %s", reason)
                log.critical(
                    "Пароль в .env не совпадает с тем, который база запомнила "
                    "при первом запуске. PostgreSQL задаёт пароль только при "
                    "инициализации тома — правка .env на существующую базу "
                    "ничего не меняет."
                )
                log.critical(
                    "Решение: либо верните прежний пароль в .env, либо пересоздайте "
                    "базу — docker compose down && rm -rf data/postgres — "
                    "и запустите установщик заново. Данные из data/db.json "
                    "перенесутся повторно."
                )
                raise AuthenticationError(reason) from exc

            if attempt == 1:
                log.info("Жду готовности PostgreSQL… (%s)", reason[:160])
            elif attempt % 5 == 0:
                log.info("Попытка %d/%d: %s", attempt, attempts, reason[:160])
            await asyncio.sleep(delay)

    log.critical("PostgreSQL не ответил за %.0f секунд", attempts * delay)
    raise RuntimeError(f"PostgreSQL недоступен: {last}")


async def create_schema() -> tuple[bool, int]:
    """Создаёт недостающие таблицы напрямую из моделей.

    Почему не Alembic при старте: его `command.upgrade` синхронный, и запуск
    из рабочего потока приводил к вложенному `asyncio.run()` поверх уже
    работающего цикла событий. На ARM это зависало наглухо — контейнер
    перезапускался по кругу, не оставляя даже трассировки.

    `create_all` идемпотентен: существующие таблицы не трогает. Alembic
    остаётся для настоящих изменений схемы и запускается отдельной командой,
    а не на каждом старте.

    Возвращает (создавалось ли что-то, сколько таблиц в базе).
    """
    from sqlalchemy import inspect

    from .models import Base

    async with get_engine().begin() as connection:
        before = await connection.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        await connection.run_sync(Base.metadata.create_all)
        after = await connection.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )

    created = sorted(after - before)
    if created:
        log.info("Созданы таблицы: %s", ", ".join(created))
    return bool(created), len(after)


async def stamp_alembic(revision: str = "0001_initial") -> None:
    """Отмечает версию схемы, чтобы будущие миграции знали точку отсчёта."""
    from sqlalchemy import text

    try:
        async with get_engine().begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version ("
                    "version_num VARCHAR(32) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
            current = await connection.execute(text("SELECT version_num FROM alembic_version"))
            if current.first() is None:
                await connection.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                    {"rev": revision},
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось отметить версию схемы: %s", exc)


async def dispose() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
