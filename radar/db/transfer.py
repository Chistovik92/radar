"""Перенос данных между SQLite и PostgreSQL (с 5.9).

До 5.9 смена базы в установщике давала пустую новую базу: старая
оставалась на диске, а пользователи, адреса, источники и история — в ней.
Здесь — перенос в обе стороны.

Как устроен:

* таблицы берутся из моделей (`Base.metadata`) и идут в порядке внешних
  ключей — пользователи раньше локаций, события раньше доставок;
* из источника читаются только те столбцы, что есть и в нём, и в модели:
  база от старой версии без новых столбцов переносится, недостающее
  получает значения по умолчанию из модели;
* чтение и запись идут через типы моделей, поэтому JSON, даты и логические
  значения превращаются корректно (в SQLite они хранятся иначе, чем в
  PostgreSQL);
* ключи сохраняются как были — ссылки между таблицами не рвутся; счётчики
  автоинкремента PostgreSQL после этого выравниваются, иначе первая же
  новая запись получила бы уже занятый номер;
* целевая база должна быть пустой. Непустую заменяет только явное
  `replace=True`: перенос поверх чужих данных смешал бы две базы;
* в конце число строк в каждой таблице сверяется с источником.

Запуск — `python -m radar.cli db copy --from sqlite --to postgres`
(или наоборот); установщик делает это сам, когда базу меняют.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .models import Base

log = logging.getLogger("radar.db.transfer")

BATCH = 500


class TransferError(Exception):
    """Перенос невозможен или не сошёлся — текст для человека."""


def url_for(backend: str) -> str:
    """Адрес базы нужного вида из тех же настроек, что у бота (.env)."""
    backend = (backend or "").strip().lower()
    if backend == "sqlite":
        path = os.path.abspath(os.getenv("DB_FILE") or "data/radar.db")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return f"sqlite+aiosqlite:///{path}"
    if backend in ("postgres", "postgresql"):
        explicit = (os.getenv("DATABASE_URL") or "").strip()
        if explicit.startswith(("postgresql", "postgres")):
            for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://",
                           "postgresql://", "postgres://"):
                if explicit.startswith(prefix):
                    return "postgresql+asyncpg://" + explicit[len(prefix):]
        password = os.getenv("DB_PASSWORD") or ""
        auth = f"{os.getenv('DB_USER') or 'radar'}"
        if password:
            auth += f":{quote_plus(password)}"
        host = os.getenv("DB_HOST") or "postgres"
        port = os.getenv("DB_PORT") or "5432"
        return f"postgresql+asyncpg://{auth}@{host}:{port}/{os.getenv('DB_NAME') or 'radar'}"
    raise TransferError(f"Незнакомый вид базы: «{backend}». Нужен sqlite или postgres.")


def _engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        return create_async_engine(url, connect_args={"timeout": 30})
    return create_async_engine(url, pool_pre_ping=True)


def _describe(url: str) -> str:
    """Адрес без пароля — для журнала и сообщений."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://…@{rest.split('@', 1)[1]}"
    return url


async def _columns(engine: AsyncEngine) -> dict[str, set[str]]:
    """Какие таблицы и столбцы уже есть в базе."""
    async with engine.connect() as connection:
        def read(sync_connection) -> dict[str, set[str]]:
            inspector = inspect(sync_connection)
            return {name: {column["name"] for column in inspector.get_columns(name)}
                    for name in inspector.get_table_names()}

        return await connection.run_sync(read)


async def _count(engine: AsyncEngine, table) -> int:
    async with engine.connect() as connection:
        return int(await connection.scalar(select(func.count()).select_from(table)) or 0)


async def counts(url: str) -> dict[str, int]:
    """Число строк в каждой таблице модели; нет таблицы — нет и строки."""
    engine = _engine(url)
    try:
        present = await _columns(engine)
        return {table.name: await _count(engine, table)
                for table in Base.metadata.sorted_tables if table.name in present}
    finally:
        await engine.dispose()


async def copy(source_url: str, target_url: str, *, replace: bool = False) -> dict[str, int]:
    """Перенести все данные. Возвращает {таблица: строк}."""
    if source_url == target_url:
        raise TransferError("Источник и цель — одна и та же база.")
    source, target = _engine(source_url), _engine(target_url)
    try:
        present = await _columns(source)
        if not present:
            raise TransferError(f"В источнике нет таблиц: {_describe(source_url)}.")

        async with target.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        busy = {table.name: await _count(target, table) for table in Base.metadata.sorted_tables}
        busy = {name: rows for name, rows in busy.items() if rows}
        if busy and not replace:
            raise TransferError(
                "Целевая база не пуста (" + ", ".join(f"{k}: {v}" for k, v in busy.items())
                + "). Перенос поверх смешал бы две базы; заменить её — флаг --replace.")

        copied: dict[str, int] = {}
        async with target.begin() as connection:
            if busy:
                for table in reversed(Base.metadata.sorted_tables):
                    await connection.execute(table.delete())
            for table in Base.metadata.sorted_tables:
                if table.name not in present:
                    copied[table.name] = 0
                    continue
                shared = [column for column in table.columns
                          if column.name in present[table.name]]
                total = 0
                async with source.connect() as reader:
                    result = await reader.stream(select(*shared))
                    async for chunk in result.partitions(BATCH):
                        rows = [dict(row._mapping) for row in chunk]
                        await connection.execute(table.insert(), rows)
                        total += len(rows)
                copied[table.name] = total
            if target.dialect.name == "postgresql":
                await _reset_sequences(connection)

        for table in Base.metadata.sorted_tables:
            if table.name not in present:
                continue
            want, got = await _count(source, table), await _count(target, table)
            if want != got:
                raise TransferError(f"Таблица {table.name}: в источнике {want}, "
                                    f"перенесено {got}.")
        log.info("Перенос %s → %s: %s", _describe(source_url), _describe(target_url),
                 ", ".join(f"{k} {v}" for k, v in copied.items() if v))
        return copied
    finally:
        await source.dispose()
        await target.dispose()


async def _reset_sequences(connection: Any) -> None:
    """Счётчики SERIAL/IDENTITY — за максимальный перенесённый номер."""
    for table in Base.metadata.sorted_tables:
        # У текстовых ключей (features, meta) счётчика нет — pg_get_serial_sequence
        # вернёт NULL, и такой столбец просто пропускается.
        for column in table.primary_key.columns:
            sequence = await connection.scalar(
                text("SELECT pg_get_serial_sequence(:table, :column)"),
                {"table": table.name, "column": column.name})
            if not sequence:
                continue
            # Не ниже 1: ключ moderated_chats — id группы Telegram, он
            # отрицательный, а счётчик меньше своего минимума не встаёт.
            await connection.execute(text(
                f"SELECT setval(:sequence, GREATEST(COALESCE((SELECT MAX({column.name}) "
                f"FROM {table.name}), 1), 1), COALESCE((SELECT MAX({column.name}) "
                f"FROM {table.name}), 0) >= 1)"), {"sequence": sequence})
