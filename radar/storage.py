"""JSON-хранилище с атомарной записью, блокировкой и миграцией с версий 2.x."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

import aiofiles

from . import config
from . import presets
from .matching import CATEGORY_TITLES
from .roles import SUPERADMIN, USER

log = logging.getLogger("radar.storage")

DB: dict[str, Any] = {}
_lock = asyncio.Lock()


# --------------------------------------------------------------------------
#  Значения по умолчанию
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
        "last_weather": 0,
        "last_fixed_date": "",
        "created": int(time.time()),
    }


def new_location(name: str, lat: float, lon: float, **extra: Any) -> dict[str, Any]:
    loc = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "city": "",
        "district": "",
        "region": "",
        "street": "",
        "house": "",
    }
    loc.update({k: v for k, v in extra.items() if v is not None})
    return loc


# --------------------------------------------------------------------------
#  Миграция
# --------------------------------------------------------------------------

def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Приводит базу любой версии 2.x к структуре 3.x без потери данных."""
    data.setdefault("users", {})
    data.setdefault("channels", [])
    data.setdefault("rss", [])
    data.setdefault("pending", [])
    data.setdefault("meta", {})

    if not isinstance(data["users"], dict):
        data["users"] = {}
    if not isinstance(data["channels"], list):
        data["channels"] = []
    if not isinstance(data["rss"], list):
        data["rss"] = []
    if not isinstance(data["pending"], list):
        data["pending"] = []

    for uid, udata in list(data["users"].items()):
        if not isinstance(udata, dict):
            data["users"][uid] = default_user()
            continue
        base = default_user(udata.get("role", USER))
        for key, value in base.items():
            udata.setdefault(key, value)
        if not isinstance(udata.get("settings"), dict):
            udata["settings"] = default_settings()
        for key in CATEGORY_TITLES:
            udata["settings"].setdefault(key, True)

        locs: list[dict[str, Any]] = []
        for loc in udata.get("locs") or []:
            if isinstance(loc, str):  # формат ещё до 2.0
                locs.append(new_location(loc, 0.0, 0.0))
                continue
            if not isinstance(loc, dict) or not loc.get("name"):
                continue
            item = new_location(
                str(loc["name"]),
                float(loc.get("lat") or 0.0),
                float(loc.get("lon") or 0.0),
            )
            for key in ("city", "district", "region", "street", "house"):
                if loc.get(key):
                    item[key] = str(loc[key])
            if loc.get("id"):
                item["id"] = str(loc["id"])
            locs.append(item)
        udata["locs"] = locs

    superadmin = str(config.SUPERADMIN_ID)
    if superadmin not in data["users"]:
        data["users"][superadmin] = default_user(SUPERADMIN)
        data["users"][superadmin]["weather_interval"] = 60
    else:
        data["users"][superadmin]["role"] = SUPERADMIN

    # Стартовый набор: федеральные источники плюс пресеты городов из SOURCE_CITIES.
    cities = config.SOURCE_CITIES or ([config.DEFAULT_CITY] if config.DEFAULT_CITY else [])
    for channel in presets.channels_for(cities) + config.EXTRA_CHANNELS:
        if channel and channel not in data["channels"]:
            data["channels"].append(channel)
    for feed in presets.rss_for(cities) + config.EXTRA_RSS:
        if feed and feed not in data["rss"]:
            data["rss"].append(feed)

    data["meta"]["schema"] = 3
    return data


# --------------------------------------------------------------------------
#  Загрузка и сохранение
# --------------------------------------------------------------------------

async def load() -> None:
    global DB
    directory = os.path.dirname(config.DATA_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)

    raw: dict[str, Any] = {}
    if os.path.exists(config.DATA_FILE):
        try:
            async with aiofiles.open(config.DATA_FILE, "r", encoding="utf-8") as fh:
                parsed = json.loads(await fh.read())
            raw = parsed if isinstance(parsed, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            backup = f"{config.DATA_FILE}.broken.{int(time.time())}"
            log.error("База повреждена (%s). Копия: %s", exc, backup)
            try:
                os.replace(config.DATA_FILE, backup)
            except OSError:
                pass

    DB = migrate(raw)
    await save()
    log.info(
        "База загружена: пользователей=%d, каналов=%d, RSS=%d",
        len(DB["users"]), len(DB["channels"]), len(DB["rss"]),
    )


async def save() -> None:
    async with _lock:
        payload = json.dumps(DB, ensure_ascii=False, indent=2)
        tmp = f"{config.DATA_FILE}.tmp"
        async with aiofiles.open(tmp, "w", encoding="utf-8") as fh:
            await fh.write(payload)
        os.replace(tmp, config.DATA_FILE)


# --------------------------------------------------------------------------
#  Доступ к данным
# --------------------------------------------------------------------------

def users() -> dict[str, Any]:
    return DB.setdefault("users", {})


def get_user(uid: int | str) -> dict[str, Any] | None:
    return users().get(str(uid))


def exists(uid: int | str) -> bool:
    return str(uid) in users()


def role_of(uid: int | str) -> str | None:
    user = get_user(uid)
    return user.get("role") if user else None


def register(uid: int | str, username: str = "") -> dict[str, Any]:
    user = default_user(USER, username)
    users()[str(uid)] = user
    return user


def find_location(uid: int | str, loc_id: str) -> dict[str, Any] | None:
    user = get_user(uid)
    if not user:
        return None
    for loc in user["locs"]:
        if loc.get("id") == loc_id:
            return loc
    return None


def remove_location(uid: int | str, loc_id: str) -> bool:
    user = get_user(uid)
    if not user:
        return False
    before = len(user["locs"])
    user["locs"] = [loc for loc in user["locs"] if loc.get("id") != loc_id]
    return len(user["locs"]) != before


def channels() -> list[str]:
    return DB.setdefault("channels", [])


def rss_feeds() -> list[str]:
    return DB.setdefault("rss", [])


def pending() -> list[str]:
    return DB.setdefault("pending", [])


def meta() -> dict[str, Any]:
    return DB.setdefault("meta", {})
