"""Обратное геокодирование (Nominatim) с бережным соблюдением лимита 1 запрос/сек."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from . import config, netcache

log = logging.getLogger("radar.geocode")

_URL = "https://nominatim.openstreetmap.org/reverse"

# Адреса не переезжают, поэтому обратное геокодирование держим сутки:
# при ограничении Nominatim в один запрос в секунду каждое попадание
# в кэш — это секунда, возвращённая циклу.
REVERSE_TTL = 24 * 3600
# Прямой поиск живёт меньше: новый дом в базе Nominatim может появиться,
# и запомнить «такого адреса нет» на сутки было бы неверно.
FORWARD_TTL = 3600

_REVERSE = netcache.TTLCache(REVERSE_TTL, limit=2000)
_FORWARD = netcache.TTLCache(FORWARD_TTL, limit=500)


def cache_stats() -> dict:
    """Для /perf: сколько запросов к Nominatim удалось не делать."""
    return {"reverse": _REVERSE.stats(), "forward": _FORWARD.stats()}


def forget_cache() -> None:
    _REVERSE.clear()
    _FORWARD.clear()
_gate = asyncio.Lock()
_last_call = 0.0

async def _throttle() -> None:
    global _last_call
    async with _gate:
        delta = time.monotonic() - _last_call
        if delta < 1.1:
            await asyncio.sleep(1.1 - delta)
        _last_call = time.monotonic()


async def reverse(
    session: aiohttp.ClientSession, lat: float, lon: float
) -> dict[str, str]:
    """Возвращает словарь с ключами name/city/district/region/street/house."""
    # Nominatim разрешает один запрос в секунду, и это жёстче любого
    # нашего таймаута: повторный разбор тех же координат — секунда,
    # отнятая у всего остального цикла. Адреса при этом не меняются,
    # поэтому держим их долго.
    key = netcache.round_point(lat, lon)
    cached = _REVERSE.get(key)
    if cached is not None:
        return dict(cached)

    await _throttle()
    params = {
        "lat": f"{lat}",
        "lon": f"{lon}",
        "format": "jsonv2",
        "zoom": "18",
        "accept-language": "ru",
        "addressdetails": "1",
    }
    try:
        async with session.get(
            _URL, params=params, headers={"User-Agent": config.USER_AGENT}
        ) as response:
            if response.status != 200:
                log.warning("Nominatim вернул %s", response.status)
                return _fallback(lat, lon)
            payload: dict[str, Any] = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Геокодирование не удалось: %s", exc)
        return _fallback(lat, lon)

    address = payload.get("address") or {}
    street = (
        address.get("road")
        or address.get("pedestrian")
        or address.get("residential")
        or address.get("neighbourhood")
        or ""
    )
    house = address.get("house_number") or ""
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or config.DEFAULT_CITY
    )
    district = (
        address.get("city_district")
        or address.get("district")
        or address.get("suburb")
        or address.get("county")
        or ""
    )
    region = address.get("state") or address.get("region") or ""

    label = ", ".join(part for part in (street, house) if part)
    if not label:
        label = district or city or f"{lat:.5f}, {lon:.5f}"
    if city and city not in label:
        label = f"{label} ({city})"

    result = {
        "name": label,
        "street": street,
        "house": house,
        "city": city,
        "district": district,
        "region": region,
    }
    # Запасной вариант не кэшируем: он означает «не дозвонились», и
    # запомнить его — значит закрепить неудачу на сутки. Сюда мы
    # доходим только с настоящим ответом.
    _REVERSE.put(key, dict(result))
    return result


def _fallback(lat: float, lon: float) -> dict[str, str]:
    return {
        "name": f"{lat:.5f}, {lon:.5f}",
        "street": "",
        "house": "",
        "city": config.DEFAULT_CITY,
        "district": "",
        "region": "",
    }


_SEARCH_URL = "https://nominatim.openstreetmap.org/search"


async def forward(
    session: aiohttp.ClientSession, query: str, city_hint: str = ""
) -> list[dict[str, str]]:
    """Прямое геокодирование: по строке адреса вернуть варианты с координатами.

    Нужно администрации, чтобы добавлять локации пользователям без геопозиции.
    """
    text = (query or "").strip()
    if len(text) < 3:
        return []
    if city_hint and city_hint.lower() not in text.lower():
        text = f"{text}, {city_hint}"

    # Администрация добавляет локации пачками и нередко повторяет одну
    # и ту же улицу. Каждый повтор — секунда ожидания у Nominatim.
    key = text.lower()
    cached = _FORWARD.get(key)
    if cached is not None:
        return [dict(item) for item in cached]

    await _throttle()
    params = {
        "q": text,
        "format": "jsonv2",
        "addressdetails": "1",
        "accept-language": "ru",
        "limit": "5",
        "countrycodes": "ru",
    }
    try:
        async with session.get(
            _SEARCH_URL, params=params, headers={"User-Agent": config.USER_AGENT}
        ) as response:
            if response.status != 200:
                log.warning("Nominatim search вернул %s", response.status)
                return []
            payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Поиск адреса не удался: %s", exc)
        return []

    results: list[dict[str, str]] = []
    for item in payload if isinstance(payload, list) else []:
        try:
            lat = float(item.get("lat"))
            lon = float(item.get("lon"))
        except (TypeError, ValueError):
            continue
        address = item.get("address") or {}
        street = (
            address.get("road")
            or address.get("pedestrian")
            or address.get("residential")
            or ""
        )
        house = address.get("house_number") or ""
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or ""
        )
        label = ", ".join(part for part in (street, house) if part)
        if not label:
            label = str(item.get("name") or "").strip()
        if not label:
            continue
        if city and city not in label:
            label = f"{label} ({city})"
        results.append(
            {
                "name": label,
                "display": str(item.get("display_name") or label),
                "lat": f"{lat}",
                "lon": f"{lon}",
                "street": street,
                "house": house,
                "city": city,
                "district": address.get("city_district") or address.get("suburb") or "",
                "region": address.get("state") or "",
            }
        )

    # Пустую выдачу тоже запоминаем: «такого адреса нет» — это ответ,
    # и переспрашивать его каждую секунду незачем. Но ненадолго:
    # в Nominatim адреса появляются.
    _FORWARD.put(key, [dict(item) for item in results])
    return results
