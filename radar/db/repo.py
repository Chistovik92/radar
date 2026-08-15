"""Репозиторий: чтение и запись данных в PostgreSQL.

Стратегия
---------
Пользователи и локации при старте загружаются в память и остаются рабочим
набором — обработчики продолжают обращаться к обычным словарям, как в 3.x,
а изменения пишутся сквозь в базу. Это оставляет диффы прежних модулей
минимальными и держит отклик интерфейса мгновенным.

Ограничение честное: подход рассчитан на тысячи пользователей, не на сотни
тысяч. Когда объём вырастет, `save_user` уже пишет точечно, и переход
на выборку по запросу сведётся к замене чтений из кэша на запросы к базе.

События и доставки в память не грузятся никогда: они только пишутся
и читаются точечными запросами.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, func, select

from .. import config
from ..matching import CATEGORY_TITLES
from ..roles import SUPERADMIN, USER
from .engine import session
from ..identity import parse as parse_identity
from .models import Delivery, Event, Feature, Location, Meta, Source, User

log = logging.getLogger("radar.repo")


# --------------------------------------------------------------------------
#  Значения по умолчанию (совместимы с 3.x)
# --------------------------------------------------------------------------

def default_settings() -> dict[str, bool]:
    return {key: True for key in CATEGORY_TITLES}


def default_user(role: str = USER, username: str = "") -> dict[str, Any]:
    return {
        "role": role,
        "username": username,
        "locs": [],
        "settings": default_settings(),
        "weather_mode": "interval",
        "weather_interval": 0,
        "weather_time": "08:00",
        "weather_format": "text",
        "last_weather": 0,
        "last_fixed_date": "",
        "quiet_from": "",
        "quiet_to": "",
        "sos_contacts": [],
        "digest": {},
        "created": int(datetime.now(timezone.utc).timestamp()),
    }


def new_location(name: str, lat: float, lon: float, **extra: Any) -> dict[str, Any]:
    location = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "city": "",
        "district": "",
        "region": "",
        "street": "",
        "house": "",
        "added_by": 0,
    }
    location.update({key: value for key, value in extra.items() if value is not None})
    return location


# --------------------------------------------------------------------------
#  Преобразование модель ↔ словарь
# --------------------------------------------------------------------------

def location_to_dict(row: Location) -> dict[str, Any]:
    return {
        "id": row.public_id,
        "name": row.name,
        "lat": row.lat,
        "lon": row.lon,
        "street": row.street,
        "house": row.house,
        "city": row.city,
        "district": row.district,
        "region": row.region,
        "added_by": row.added_by,
    }


def user_to_dict(row: User) -> dict[str, Any]:
    settings = dict(row.settings or {})
    for key in CATEGORY_TITLES:
        settings.setdefault(key, True)
    return {
        "role": row.role,
        "username": row.username or "",
        "locs": [location_to_dict(item) for item in row.locations],
        "settings": settings,
        "weather_mode": row.weather_mode,
        "weather_interval": row.weather_interval,
        "weather_time": row.weather_time,
        "weather_format": row.weather_format,
        "last_weather": row.last_weather,
        "last_fixed_date": row.last_fixed_date,
        "quiet_from": row.quiet_from,
        "quiet_to": row.quiet_to,
        "sos_contacts": list(row.sos_contacts or []),
        "digest": dict(row.digest or {}),
        "created": int(row.created_at.timestamp()) if row.created_at else 0,
    }


# --------------------------------------------------------------------------
#  Пользователи
# --------------------------------------------------------------------------

async def load_users() -> dict[str, dict[str, Any]]:
    from ..identity import make as make_identity

    async with session() as active:
        rows = (await active.scalars(select(User))).all()
        return {
            make_identity(row.platform, row.external_id).key: user_to_dict(row)
            for row in rows
        }


async def _find_user(active, key: str | int) -> User | None:
    identity = parse_identity(key)
    return await active.scalar(
        select(User).where(
            User.platform == identity.platform,
            User.external_id == identity.external_id,
        )
    )


async def save_user(uid: str | int, data: dict[str, Any]) -> None:
    """Сохраняет пользователя целиком вместе с локациями."""
    identity = parse_identity(uid)
    async with session() as active:
        row = await _find_user(active, uid)
        if row is None:
            row = User(platform=identity.platform, external_id=identity.external_id)
            active.add(row)

        row.role = data.get("role", USER)
        row.username = (data.get("username") or "")[:64]
        row.settings = dict(data.get("settings") or default_settings())
        row.weather_mode = data.get("weather_mode", "interval")
        row.weather_interval = int(data.get("weather_interval") or 0)
        row.weather_time = data.get("weather_time", "08:00")
        row.weather_format = data.get("weather_format", "text")
        row.last_weather = int(data.get("last_weather") or 0)
        row.last_fixed_date = data.get("last_fixed_date", "")
        row.quiet_from = data.get("quiet_from", "")
        row.quiet_to = data.get("quiet_to", "")
        row.sos_contacts = list(data.get("sos_contacts") or [])
        row.digest = dict(data.get("digest") or {})
        row.seen_at = datetime.now(timezone.utc)

        await active.flush()
        user_id = row.id

        # Локации читаем запросом, а не через row.locations: обращение
        # к отношению у уже сохранённого объекта запускает ленивую подгрузку,
        # а она в async-контексте падает с MissingGreenlet.
        current = (
            await active.scalars(select(Location).where(Location.user_id == user_id))
        ).all()
        existing = {item.public_id: item for item in current}
        wanted = {item["id"]: item for item in (data.get("locs") or [])}

        for public_id, item in wanted.items():
            target = existing.get(public_id)
            if target is None:
                target = Location(public_id=public_id, user_id=user_id)
                active.add(target)
            target.name = str(item.get("name") or "")[:200]
            target.lat = float(item.get("lat") or 0.0)
            target.lon = float(item.get("lon") or 0.0)
            target.street = str(item.get("street") or "")[:160]
            target.house = str(item.get("house") or "")[:32]
            target.city = str(item.get("city") or "")[:120]
            target.district = str(item.get("district") or "")[:120]
            target.region = str(item.get("region") or "")[:120]
            target.added_by = int(item.get("added_by") or 0)

        for public_id, target in existing.items():
            if public_id not in wanted:
                await active.delete(target)


async def delete_user(uid: str | int) -> None:
    async with session() as active:
        row = await _find_user(active, uid)
        if row is not None:
            await active.delete(row)


async def internal_id(uid: str | int) -> int | None:
    """Суррогатный идентификатор пользователя — нужен для связей."""
    async with session() as active:
        row = await _find_user(active, uid)
        return int(row.id) if row is not None else None


async def save_users(users: dict[str, dict[str, Any]]) -> None:
    for uid, data in users.items():
        await save_user(uid, data)


# --------------------------------------------------------------------------
#  Источники
# --------------------------------------------------------------------------

async def load_sources() -> tuple[list[str], list[str], list[str], list[str]]:
    """Возвращает (telegram, rss, vk, очередь модерации)."""
    async with session() as active:
        rows = (await active.scalars(select(Source))).all()
    channels = [row.ref for row in rows if row.kind == "tg" and row.enabled and not row.pending]
    feeds = [row.ref for row in rows if row.kind == "rss" and row.enabled and not row.pending]
    vk = [row.ref for row in rows if row.kind == "vk" and row.enabled and not row.pending]
    pending = [row.ref for row in rows if row.pending]
    return channels, feeds, vk, pending


async def upsert_source(
    kind: str, ref: str, *, pending: bool = False, added_by: int = 0, city: str = ""
) -> None:
    # Без диалектного ON CONFLICT: одинаково работает в SQLite и PostgreSQL.
    async with session() as active:
        row = await active.scalar(
            select(Source).where(Source.kind == kind, Source.ref == ref)
        )
        if row is None:
            active.add(
                Source(kind=kind, ref=ref, pending=pending, added_by=added_by, city=city)
            )
        else:
            row.pending = pending
            row.enabled = True


async def remove_source(kind: str, ref: str) -> None:
    async with session() as active:
        await active.execute(delete(Source).where(Source.kind == kind, Source.ref == ref))


async def sync_sources(
    channels: Sequence[str], feeds: Sequence[str], vk: Sequence[str], pending: Sequence[str]
) -> None:
    """Приводит таблицу источников в соответствие со списками в памяти."""
    async with session() as active:
        rows = (await active.scalars(select(Source))).all()
        current = {(row.kind, row.ref): row for row in rows}

        wanted: dict[tuple[str, str], bool] = {}
        for ref in channels:
            wanted[("tg", ref)] = False
        for ref in feeds:
            wanted[("rss", ref)] = False
        for ref in vk:
            wanted[("vk", ref)] = False
        for ref in pending:
            wanted.setdefault(("tg", ref), True)

        for key, is_pending in wanted.items():
            row = current.get(key)
            if row is None:
                active.add(Source(kind=key[0], ref=key[1], pending=is_pending))
            else:
                row.pending = is_pending
                row.enabled = True

        for key, row in current.items():
            if key not in wanted:
                await active.delete(row)


async def mark_source(kind: str, ref: str, *, error: str = "") -> None:
    """Отмечает результат опроса источника — для отчёта о мёртвых каналах."""
    async with session() as active:
        row = await active.scalar(
            select(Source).where(Source.kind == kind, Source.ref == ref)
        )
        if row is None:
            return
        if error:
            row.fail_count += 1
            row.last_error = error[:300]
        else:
            row.fail_count = 0
            row.last_error = ""
            row.last_seen = datetime.now(timezone.utc)


async def broken_sources(threshold: int = 5) -> list[Source]:
    async with session() as active:
        return list(
            (await active.scalars(
                select(Source).where(Source.fail_count >= threshold)
            )).all()
        )


# --------------------------------------------------------------------------
#  События и доставки
# --------------------------------------------------------------------------

def event_digest(source: str, raw: str) -> str:
    return hashlib.sha1(f"{source}\n{raw}".encode("utf-8")).hexdigest()


async def store_event(analysis: Any) -> int | None:
    """Сохраняет разобранное событие, возвращает его id.

    Повторное сохранение того же текста не создаёт дубликат: сработает
    уникальный индекс по digest и вернётся существующая запись.
    """
    if not getattr(analysis, "relevant", False):
        return None

    digest = event_digest(analysis.source, analysis.raw or analysis.summary)
    async with session() as active:
        existing = await active.scalar(select(Event.id).where(Event.digest == digest))
        if existing:
            return int(existing)
        row = Event(
            digest=digest,
            source=(analysis.source or "")[:200],
            kind="rss" if analysis.link else "tg",
            link=analysis.link or "",
            categories=list(analysis.categories),
            severity=analysis.severity,
            scope=analysis.scope,
            all_clear=bool(analysis.all_clear),
            city=(analysis.city or "")[:120],
            region=(analysis.region or "")[:120],
            districts=list(analysis.districts),
            streets=list(analysis.streets),
            summary=analysis.summary or "",
            raw=(analysis.raw or "")[:8000],
            engine=analysis.engine,
        )
        active.add(row)
        await active.flush()
        return int(row.id)


async def record_delivery(
    event_id: int, user_id: int | str, location_public_id: str | None
) -> bool:
    """Отмечает доставку. False — событие этой локации уже отправляли."""
    async with session() as active:
        row = await _find_user(active, user_id)
        if row is None:
            return False
        location_id = None
        if location_public_id:
            location_id = await active.scalar(
                select(Location.id).where(
                    Location.user_id == row.id,
                    Location.public_id == location_public_id,
                )
            )
        existing = await active.scalar(
            select(Delivery.id).where(
                Delivery.event_id == event_id,
                Delivery.user_id == row.id,
                Delivery.location_id == location_id,
            )
        )
        if existing is not None:
            return False
        active.add(
            Delivery(
                event_id=event_id,
                user_id=row.id,
                location_id=location_id,
                sent_at=datetime.now(timezone.utc),
            )
        )
        return True


async def was_delivered(event_id: int, user_id: int | str, location_public_id: str | None) -> bool:
    async with session() as active:
        row = await _find_user(active, user_id)
        if row is None:
            return False
        location_id = None
        if location_public_id:
            location_id = await active.scalar(
                select(Location.id).where(
                    Location.user_id == row.id,
                    Location.public_id == location_public_id,
                )
            )
        found = await active.scalar(
            select(Delivery.id).where(
                Delivery.event_id == event_id,
                Delivery.user_id == row.id,
                Delivery.location_id == location_id,
            )
        )
        return found is not None


async def history(
    user_id: int | str,
    location_public_id: str | None = None,
    *,
    days: int = 30,
    limit: int = 20,
    categories: Iterable[str] | None = None,
) -> list[Event]:
    """История событий, приходивших пользователю (опционально по одной локации)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with session() as active:
        row = await _find_user(active, user_id)
        if row is None:
            return []
        query = (
            select(Event)
            .join(Delivery, Delivery.event_id == Event.id)
            .where(Delivery.user_id == row.id, Delivery.sent_at >= since)
            .order_by(Event.created_at.desc())
            .limit(limit)
        )
        if location_public_id:
            location_id = await active.scalar(
                select(Location.id).where(
                    Location.user_id == row.id,
                    Location.public_id == location_public_id,
                )
            )
            query = query.where(Delivery.location_id == location_id)
        rows = (await active.scalars(query)).all()

    wanted = set(categories or [])
    if wanted:
        rows = [row for row in rows if wanted & set(row.categories or [])]
    return list(rows)


async def event_stats(days: int = 30) -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with session() as active:
        events = await active.scalar(
            select(func.count(Event.id)).where(Event.created_at >= since)
        )
        deliveries = await active.scalar(
            select(func.count(Delivery.id)).where(Delivery.sent_at >= since)
        )
    return {"events": int(events or 0), "deliveries": int(deliveries or 0)}


async def purge_old_events(days: int | None = None) -> int:
    """Чистка истории. Возвращает число удалённых событий."""
    keep = config.EVENT_RETENTION_DAYS if days is None else days
    if keep <= 0:
        return 0
    edge = datetime.now(timezone.utc) - timedelta(days=keep)
    async with session() as active:
        result = await active.execute(delete(Event).where(Event.created_at < edge))
        return int(result.rowcount or 0)


# --------------------------------------------------------------------------
#  Служебные значения
# --------------------------------------------------------------------------

async def get_meta(key: str, default: Any = None) -> Any:
    async with session() as active:
        row = await active.get(Meta, key)
        return row.value if row is not None else default


async def set_meta(key: str, value: Any) -> None:
    async with session() as active:
        row = await active.get(Meta, key)
        if row is None:
            active.add(Meta(key=key, value=value))
        else:
            row.value = value


# --------------------------------------------------------------------------
#  Переключатели возможностей
# --------------------------------------------------------------------------

async def load_features() -> dict[str, bool]:
    async with session() as active:
        rows = (await active.scalars(select(Feature))).all()
        return {row.key: bool(row.enabled) for row in rows}


async def set_feature(key: str, enabled_value: bool, changed_by: int | str = 0) -> None:
    identity = parse_identity(changed_by) if changed_by else None
    actor = 0
    if identity is not None and identity.external_id.isdigit():
        actor = int(identity.external_id)
    async with session() as active:
        row = await active.get(Feature, key)
        if row is None:
            active.add(Feature(key=key, enabled=enabled_value, changed_by=actor))
        else:
            row.enabled = enabled_value
            row.changed_by = actor
