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

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .. import config

log = logging.getLogger("radar.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        url = config.database_url()
        if config.is_sqlite():
            # У SQLite нет сетевого пула: соединение одно, поэтому pool_size
            # неприменим. WAL и увеличенный таймаут снимают блокировки при
            # одновременной записи из фонового цикла и обработчиков.
            _engine = create_async_engine(
                url,
                echo=config.DB_ECHO,
                connect_args={"timeout": 30},
            )

            @event.listens_for(_engine.sync_engine, "connect")
            def _tune_sqlite(dbapi_connection, _record):  # noqa: ANN001
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA cache_size=-8000")   # 8 МБ, экономно
                cursor.close()
        else:
            _engine = create_async_engine(
                url,
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

    if config.is_sqlite():
        # Файловая база готова сразу: ждать нечего.
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        log.info("База SQLite готова: %s", config.DB_FILE)
        return

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


async def ensure_schema() -> tuple[bool, int, bool]:
    """Создаёт схему и чинит её, если она осталась от версии с ошибкой.

    Возвращает (создавалось ли что-то, число таблиц, была ли починка).
    """
    created, tables = await create_schema()

    compatible, reason = await check_schema_compatible()
    if compatible:
        return created, tables, False

    log.warning("Обнаружена несовместимая схема: %s", reason)
    await repair_schema()
    _created, tables = await create_schema()
    return created, tables, True


async def _sqlite_pk_type(connection, table: str, column: str) -> str:
    """Объявленный тип столбца в SQLite — из PRAGMA table_info."""
    from sqlalchemy import text

    result = await connection.execute(text(f"PRAGMA table_info({table})"))
    for row in result:
        if row[1] == column:
            return str(row[2] or "").upper()
    return ""


async def check_schema_compatible() -> tuple[bool, str]:
    """Совместима ли существующая схема с текущими моделями.

    Нужно потому, что `create_all` только досоздаёт недостающие таблицы
    и никогда не меняет существующие. База, созданная версией с ошибкой
    в типе первичного ключа, так и осталась бы нерабочей: таблицы на месте,
    а вставка падает.
    """
    from sqlalchemy import inspect, text

    if not config.is_sqlite():
        return True, ""

    async with get_engine().connect() as connection:
        tables = await connection.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        if "users" not in tables:
            return True, ""

        pk_type = await _sqlite_pk_type(connection, "users", "id")
        if pk_type and pk_type != "INTEGER":
            return False, (
                f"первичный ключ users.id объявлен как {pk_type}; "
                "SQLite подставляет автоинкремент только для INTEGER"
            )

        for table, column in (("locations", "user_id"), ("deliveries", "user_id")):
            if table not in tables:
                continue
            column_type = await _sqlite_pk_type(connection, table, column)
            if column_type and column_type != "INTEGER":
                return False, f"тип {table}.{column} = {column_type}, ожидается INTEGER"

    return True, ""


async def repair_schema() -> dict[str, int]:
    """Пересоздаёт схему, сохраняя данные.

    Содержимое читается обычными запросами — чтение из «сломанной» схемы
    работает, падает только вставка, — затем таблицы создаются заново
    и данные возвращаются на место. История событий не переносится:
    она восстановима из источников и не стоит усложнения.
    """
    from sqlalchemy import select

    from .models import Base, Feature, Location, Meta, Source, User

    users: list[dict] = []
    locations: list[dict] = []
    sources: list[dict] = []
    features: list[dict] = []
    meta: list[dict] = []

    async with session() as active:
        for row in (await active.scalars(select(User))).all():
            users.append({
                "old_id": row.id,
                "platform": row.platform, "external_id": row.external_id,
                "role": row.role, "username": row.username,
                "settings": row.settings or {},
                "weather_mode": row.weather_mode, "weather_interval": row.weather_interval,
                "weather_time": row.weather_time, "weather_format": row.weather_format,
                "last_weather": row.last_weather, "last_fixed_date": row.last_fixed_date,
                "quiet_from": row.quiet_from, "quiet_to": row.quiet_to,
            })
        for row in (await active.scalars(select(Location))).all():
            locations.append({
                "old_user_id": row.user_id,
                "public_id": row.public_id, "name": row.name,
                "lat": row.lat, "lon": row.lon, "street": row.street, "house": row.house,
                "city": row.city, "district": row.district, "region": row.region,
                "added_by": row.added_by,
            })
        for row in (await active.scalars(select(Source))).all():
            sources.append({
                "kind": row.kind, "ref": row.ref, "title": row.title, "city": row.city,
                "enabled": row.enabled, "pending": row.pending, "added_by": row.added_by,
            })
        for row in (await active.scalars(select(Feature))).all():
            features.append({"key": row.key, "enabled": row.enabled,
                             "changed_by": row.changed_by})
        for row in (await active.scalars(select(Meta))).all():
            meta.append({"key": row.key, "value": row.value})

    log.warning(
        "Схема несовместима — пересоздаю. Сохранено: пользователей %d, "
        "локаций %d, источников %d",
        len(users), len(locations), len(sources),
    )

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    restored_locations = 0
    async with session() as active:
        # Старый идентификатор → новый: связь локаций с владельцами
        # восстанавливается именно по нему, а не по порядку строк.
        id_map: dict[int, int] = {}
        for item in users:
            old_id = item.pop("old_id")
            row = User(**item)
            active.add(row)
            await active.flush()
            id_map[old_id] = row.id

        for item in locations:
            old_user = item.pop("old_user_id")
            new_user = id_map.get(old_user)
            if new_user is None:
                log.warning("Локация «%s» пропущена: владелец не найден", item.get("name"))
                continue
            active.add(Location(user_id=new_user, **item))
            restored_locations += 1

        for item in sources:
            active.add(Source(**item))
        for item in features:
            active.add(Feature(**item))
        for item in meta:
            active.add(Meta(**item))

    log.info(
        "Схема пересоздана: пользователей %d, локаций %d, источников %d",
        len(users), restored_locations, len(sources),
    )
    return {
        "users": len(users),
        "locations": restored_locations,
        "sources": len(sources),
        "features": len(features),
        "meta": len(meta),
    }


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
