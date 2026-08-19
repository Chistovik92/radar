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
    raw_users = raw.get("users")
    if not isinstance(raw_users, dict):
        raw_users = {}
    for uid, item in raw_users.items():
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
        raw_locs = item.get("locs")
        if not isinstance(raw_locs, (list, tuple)):
            raw_locs = []
        for entry in raw_locs:
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

    def as_list(value: Any) -> list[str]:
        """Терпимо читает список: в повреждённом файле там может быть что угодно."""
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if item]
        return []

    channels = as_list(raw.get("channels"))
    feeds = as_list(raw.get("rss"))
    vk = as_list(raw.get("vk"))
    pending = as_list(raw.get("pending"))

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
        "meta": raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
    }


async def is_empty() -> bool:
    users = await repo.load_users()
    return not users


def legacy_present(path: str | None = None) -> bool:
    """Лежит ли рядом файл базы от версии 3.x.

    Перенос из него прекращён в 4.6.1, но обнаружить файл всё равно нужно:
    иначе бот молча стартует с пустой базой, и человек решит, что данные
    потеряны, хотя они лежат в соседнем файле.
    """
    return os.path.exists(path or config.DATA_FILE)


async def run(path: str | None = None) -> dict[str, int]:
    """Перенос из db.json удалён в 4.6.1.

    Оставлена заглушка, а не выкинута функция целиком: её зовут диагностика
    и старые сценарии, и внятная ошибка полезнее AttributeError.
    """
    raise RuntimeError(
        "Перенос из data/db.json прекращён с версии 4.6.1. "
        "Обновитесь сначала до 4.6.0 — она перенесёт данные, — "
        "и только затем на текущую версию."
    )
