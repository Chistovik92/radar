"""Обратное геокодирование (Nominatim) с бережным соблюдением лимита 1 запрос/сек."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from . import config

log = logging.getLogger("radar.geocode")

_URL = "https://nominatim.openstreetmap.org/reverse"
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

    return {
        "name": label,
        "street": street,
        "house": house,
        "city": city,
        "district": district,
        "region": region,
    }


def _fallback(lat: float, lon: float) -> dict[str, str]:
    return {
        "name": f"{lat:.5f}, {lon:.5f}",
        "street": "",
        "house": "",
        "city": config.DEFAULT_CITY,
        "district": "",
        "region": "",
    }
