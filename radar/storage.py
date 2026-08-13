"""Рабочий набор данных: словари в памяти поверх PostgreSQL.

Обработчики работают с обычными словарями, как в версиях 3.x, — сигнатуры
функций сохранены намеренно, чтобы переход на базу не потребовал правки
интерфейсных модулей. Изменения пишутся сквозь: `save()` отправляет в базу
только тех пользователей, кто действительно менялся.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .db import repo
from .roles import USER

log = logging.getLogger("radar.storage")

DB: dict[str, Any] = {"users": {}, "channels": [], "rss": [], "vk": [], "pending": [], "meta": {}}

_lock = asyncio.Lock()
# Снимки состояния: позволяют сохранять только реально изменившихся
# пользователей, не требуя от обработчиков помечать изменения вручную.
_snapshots: dict[str, str] = {}
_sources_snapshot: str = ""


def _fingerprint(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)

# Прежние имена сохранены: на них ссылаются обработчики и тесты.
default_settings = repo.default_settings
default_user = repo.default_user
new_location = repo.new_location


# --------------------------------------------------------------------------
#  Загрузка и сохранение
# --------------------------------------------------------------------------

async def load() -> None:
    """Читает всё содержимое базы в память."""
    global _sources_snapshot
    users = await repo.load_users()
    channels, feeds, vk, pending = await repo.load_sources()

    DB["users"] = users
    DB["channels"] = channels
    DB["rss"] = feeds
    DB["vk"] = vk
    DB["pending"] = pending
    DB["meta"] = {}
    _snapshots.clear()
    _snapshots.update({uid: _fingerprint(data) for uid, data in users.items()})
    _sources_snapshot = _fingerprint([channels, feeds, vk, pending])

    log.info(
        "Загружено: пользователей %d, каналов %d, лент %d, VK %d",
        len(users), len(channels), len(feeds), len(vk),
    )


async def save(uid: str | int | None = None) -> None:
    """Пишет в базу то, что изменилось с прошлого сохранения.

    Без аргумента проверяет всех пользователей и списки источников;
    с аргументом — только указанного пользователя. Сравнение идёт
    по снимку в памяти, поэтому обработчикам не нужно ничего помечать.
    """
    global _sources_snapshot
    async with _lock:
        if uid is not None:
            key = str(uid)
            data = DB["users"].get(key)
            if data is not None:
                mark = _fingerprint(data)
                if _snapshots.get(key) != mark:
                    await repo.save_user(key, data)
                    _snapshots[key] = mark
            return

        for user_id, data in list(DB["users"].items()):
            mark = _fingerprint(data)
            if _snapshots.get(user_id) != mark:
                await repo.save_user(user_id, data)
                _snapshots[user_id] = mark

        for stale in set(_snapshots) - set(DB["users"]):
            _snapshots.pop(stale, None)

        sources = [DB["channels"], DB["rss"], DB.get("vk", []), DB["pending"]]
        mark = _fingerprint(sources)
        if mark != _sources_snapshot:
            await repo.sync_sources(*sources)
            _sources_snapshot = mark


# --------------------------------------------------------------------------
#  Доступ к данным (сигнатуры из 3.x)
# --------------------------------------------------------------------------

def users() -> dict[str, Any]:
    return DB["users"]


def get_user(uid: int | str) -> dict[str, Any] | None:
    return DB["users"].get(str(uid))


def exists(uid: int | str) -> bool:
    return str(uid) in DB["users"]


def role_of(uid: int | str) -> str | None:
    user = get_user(uid)
    return user.get("role") if user else None


def register(uid: int | str, username: str = "") -> dict[str, Any]:
    user = repo.default_user(USER, username)
    DB["users"][str(uid)] = user
    return user


def find_location(uid: int | str, loc_id: str) -> dict[str, Any] | None:
    user = get_user(uid)
    if not user:
        return None
    for location in user["locs"]:
        if location.get("id") == loc_id:
            return location
    return None


def remove_location(uid: int | str, loc_id: str) -> bool:
    user = get_user(uid)
    if not user:
        return False
    before = len(user["locs"])
    user["locs"] = [item for item in user["locs"] if item.get("id") != loc_id]
    return len(user["locs"]) != before


async def drop_user(uid: int | str) -> None:
    """Полное удаление пользователя вместе с локациями."""
    DB["users"].pop(str(uid), None)
    _snapshots.pop(str(uid), None)
    await repo.delete_user(uid)


def channels() -> list[str]:
    return DB["channels"]


def rss_feeds() -> list[str]:
    return DB["rss"]


def vk_groups() -> list[str]:
    return DB.setdefault("vk", [])


def pending() -> list[str]:
    return DB["pending"]


def meta() -> dict[str, Any]:
    return DB["meta"]


async def meta_get(key: str, default: Any = None) -> Any:
    return await repo.get_meta(key, default)


async def meta_set(key: str, value: Any) -> None:
    await repo.set_meta(key, value)
