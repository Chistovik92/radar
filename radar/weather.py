"""Погода и краткий прогноз через Open-Meteo (без ключа API)."""

from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("radar.weather")

_URL = "https://api.open-meteo.com/v1/forecast"

CODES = {
    0: "☀️ ясно", 1: "🌤 малооблачно", 2: "⛅️ облачно", 3: "☁️ пасмурно",
    45: "🌫 туман", 48: "🌫 изморозь",
    51: "🌦 морось", 53: "🌦 морось", 55: "🌦 сильная морось",
    56: "🌧 ледяная морось", 57: "🌧 ледяная морось",
    61: "🌧 небольшой дождь", 63: "🌧 дождь", 65: "🌧 сильный дождь",
    66: "🌧 ледяной дождь", 67: "🌧 ледяной дождь",
    71: "🌨 небольшой снег", 73: "🌨 снег", 75: "❄️ сильный снег", 77: "🌨 снежная крупа",
    80: "🌧 ливень", 81: "🌧 ливень", 82: "⛈ сильный ливень",
    85: "🌨 снегопад", 86: "🌨 сильный снегопад",
    95: "⛈ гроза", 96: "⛈ гроза с градом", 99: "⛈ сильная гроза с градом",
}


async def forecast(session: aiohttp.ClientSession, lat: float, lon: float) -> str:
    """HTML-блок: текущая погода и прогноз на 6 часов."""
    if not lat and not lon:
        return "⚠️ Нет координат — отправьте геопозицию заново."

    params = {
        "latitude": f"{lat}",
        "longitude": f"{lon}",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "wind_speed_10m,precipitation,weather_code",
        "hourly": "temperature_2m,precipitation_probability",
        "timezone": "auto",
        "forecast_hours": "7",
        "wind_speed_unit": "ms",
    }
    try:
        async with session.get(_URL, params=params) as response:
            if response.status != 200:
                return f"⚠️ Сервис погоды вернул код {response.status}."
            data = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Погода недоступна: %s", exc)
        return "⚠️ Сбой получения погоды."

    current = data.get("current") or {}
    try:
        code = CODES.get(int(current.get("weather_code", -1)), "")
    except (TypeError, ValueError):
        code = ""

    temp = current.get("temperature_2m", "?")
    feels = current.get("apparent_temperature")
    wind = current.get("wind_speed_10m", "?")
    humidity = current.get("relative_humidity_2m")

    head = f"🌡 <b>Сейчас:</b> {temp}°C"
    if feels is not None:
        head += f" (ощущается {feels}°C)"
    head += f" | 💨 {wind} м/с"
    if humidity is not None:
        head += f" | 💧 {humidity}%"
    if code:
        head += f" | {code}"

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    probs = hourly.get("precipitation_probability") or []
    slots = []
    for index in range(1, min(7, len(times))):
        clock = times[index].split("T")[1][:5] if "T" in times[index] else f"+{index}ч"
        value = temps[index] if index < len(temps) else "?"
        chance = probs[index] if index < len(probs) else 0
        slots.append(f"<code>{clock}</code> {value}°C ({chance}%)")

    if slots:
        return head + "\n⏱ <b>6 часов:</b> " + " | ".join(slots)
    return head
