"""Импорт данных из JSON-хранилища версии 3.x в PostgreSQL.

Запускается автоматически при первом старте 4.x, если база пуста, а файл
`data/db.json` на месте. Исходный файл не удаляется, а переименовывается
в `db.json.migrated` — путь назад остаётся.

Поддерживается только формат 3.x. Базы версий 2.x напрямую не читаются:
сначала обновитесь до 3.3.5, дайте боту один раз запуститься — он приведёт
файл к текущему виду, — и только потом переходите на 4.x. Промежуточный
шаг занимает минуту и избавляет импортёр от ветвлений, которые невозможно
проверить на живых данных.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .. import config, presets
from ..matching import CATEGORY_TITLES
from ..roles import SUPERADMIN, USER
from . import repo

log = logging.getLogger("radar.import")

MARKER = "json_import"


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Приводит структуру версии 3.x к виду репозитория."""
    users: dict[str, dict[str, Any]] = {}
    for uid, item in (raw.get("users") or {}).items():
        if not isinstance(item, dict):
            continue
        record = repo.default_user(item.get("role", USER), item.get("username", ""))
        for key in (
            "weather_mode", "weather_interval", "weather_time",
            "last_weather", "last_fixed_date", "weather_format",
        ):
            if item.get(key) is not None:
                record[key] = item[key]

        settings = item.get("settings")
        if isinstance(settings, dict):
            record["settings"] = {
                key: bool(settings.get(key, True)) for key in CATEGORY_TITLES
            }

        locations: list[dict[str, Any]] = []
        for entry in item.get("locs") or []:
            if not isinstance(entry, dict) or not entry.get("name"):
                # Строки вместо объектов — формат 2.x, он больше не поддерживается.
                if isinstance(entry, str):
                    log.warning(
                        "Локация «%s» в формате 2.x пропущена: обновитесь сначала до 3.3.5",
                        entry[:60],
                    )
                continue
            location = repo.new_location(
                str(entry["name"]),
                float(entry.get("lat") or 0.0),
                float(entry.get("lon") or 0.0),
            )
            for key in ("city", "district", "region", "street", "house"):
                if entry.get(key):
                    location[key] = str(entry[key])
            if entry.get("id"):
                location["id"] = str(entry["id"])[:16]
            locations.append(location)
        record["locs"] = locations
        users[str(uid)] = record

    superadmin = str(config.SUPERADMIN_ID)
    if superadmin not in users:
        users[superadmin] = repo.default_user(SUPERADMIN)
        users[superadmin]["weather_interval"] = 60
    else:
        users[superadmin]["role"] = SUPERADMIN

    channels = [str(item) for item in (raw.get("channels") or []) if item]
    feeds = [str(item) for item in (raw.get("rss") or []) if item]
    vk = [str(item) for item in (raw.get("vk") or []) if item]
    pending = [str(item) for item in (raw.get("pending") or []) if item]

    cities = config.SOURCE_CITIES or ([config.DEFAULT_CITY] if config.DEFAULT_CITY else [])
    for name in presets.channels_for(cities):
        if name not in channels:
            channels.append(name)
    for url in presets.rss_for(cities):
        if url not in feeds:
            feeds.append(url)

    return {
        "users": users,
        "channels": channels,
        "rss": feeds,
        "vk": vk,
        "pending": pending,
        "meta": raw.get("meta") or {},
    }


async def is_empty() -> bool:
    users = await repo.load_users()
    return not users


async def run(path: str | None = None) -> dict[str, int]:
    """Переносит JSON в базу. Возвращает счётчики перенесённого."""
    source = path or config.DATA_FILE
    raw: dict[str, Any] = {}

    if os.path.exists(source):
        try:
            with open(source, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            raw = loaded if isinstance(loaded, dict) else {}
            log.info("Найден файл прежней версии: %s", source)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Файл %s не прочитан (%s) — начинаю с пустой базы", source, exc)
            raw = {}
    else:
        log.info("Файла %s нет — создаю базу с нуля", source)

    data = _normalize(raw)

    await repo.save_users(data["users"])
    await repo.sync_sources(data["channels"], data["rss"], data["vk"], data["pending"])

    for key, value in (data["meta"] or {}).items():
        await repo.set_meta(str(key), value if isinstance(value, (dict, list)) else {"value": value})

    counters = {
        "users": len(data["users"]),
        "locations": sum(len(item["locs"]) for item in data["users"].values()),
        "channels": len(data["channels"]),
        "rss": len(data["rss"]),
        "pending": len(data["pending"]),
    }
    await repo.set_meta(MARKER, {"done": True, **counters})

    if os.path.exists(source):
        backup = f"{source}.migrated"
        try:
            os.replace(source, backup)
            log.info("Исходный файл сохранён как %s", backup)
        except OSError as exc:
            log.warning("Не удалось переименовать %s: %s", source, exc)

    log.info(
        "Перенос завершён: пользователей %d, локаций %d, каналов %d, лент %d",
        counters["users"], counters["locations"], counters["channels"], counters["rss"],
    )
    return counters
