"""Погода Open-Meteo: получение данных и оформление сводки.

Разбор ответа и вёрстка разделены: `fetch` ходит в сеть, `render` — чистая
функция, которую можно покрыть тестами офлайн.

Вёрстка ориентирована на то, как погоду показывают поисковики и мобильные
приложения: крупное текущее значение, строка деталей, почасовая таблица
с колонкой осадков и столбиком температуры, затем прогноз по дням.
Почасовая часть выводится моноширинным блоком — иначе колонки разъезжаются.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

from . import netcache

log = logging.getLogger("radar.weather")

_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo обновляет прогноз раз в час, поэтому четверть часа — запас
# с двойным перекрытием. Дольше держать не стоит: в сводке есть местное
# время, и оно начнёт заметно отставать.
CACHE_TTL = 900
_CACHE = netcache.TTLCache(CACHE_TTL, limit=400)

# Коды погоды WMO: описание и значок (день / ночь).
CODES: dict[int, tuple[str, str, str]] = {
    0: ("ясно", "☀️", "🌙"),
    1: ("малооблачно", "🌤", "🌙"),
    2: ("переменная облачность", "⛅️", "☁️"),
    3: ("пасмурно", "☁️", "☁️"),
    45: ("туман", "🌫", "🌫"),
    48: ("изморозь", "🌫", "🌫"),
    51: ("морось", "🌦", "🌧"),
    53: ("морось", "🌦", "🌧"),
    55: ("сильная морось", "🌦", "🌧"),
    56: ("ледяная морось", "🌧", "🌧"),
    57: ("ледяная морось", "🌧", "🌧"),
    61: ("небольшой дождь", "🌦", "🌧"),
    63: ("дождь", "🌧", "🌧"),
    65: ("сильный дождь", "🌧", "🌧"),
    66: ("ледяной дождь", "🌧", "🌧"),
    67: ("ледяной дождь", "🌧", "🌧"),
    71: ("небольшой снег", "🌨", "🌨"),
    73: ("снег", "🌨", "🌨"),
    75: ("сильный снег", "❄️", "❄️"),
    77: ("снежная крупа", "🌨", "🌨"),
    80: ("ливень", "🌦", "🌧"),
    81: ("ливень", "🌧", "🌧"),
    82: ("сильный ливень", "⛈", "⛈"),
    85: ("снегопад", "🌨", "🌨"),
    86: ("сильный снегопад", "❄️", "❄️"),
    95: ("гроза", "⛈", "⛈"),
    96: ("гроза с градом", "⛈", "⛈"),
    99: ("сильная гроза с градом", "⛈", "⛈"),
}

SPARK = "▁▂▃▄▅▆▇█"
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
WEEKDAYS_EN = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

def describe(code: int | None, day: bool = True, lang: str = "ru") -> tuple[str, str]:
    from . import i18n

    key = int(code) if code is not None else -1
    name_ru, icon_day, icon_night = CODES.get(key, ("", "🌡", "🌡"))
    name = i18n.t(f"weather.wmo.{key}", lang, name_ru) if name_ru else ""
    return name, (icon_day if day else icon_night)


@dataclass
class Hour:
    label: str          # «14ч»
    temp: float
    probability: int
    code: int | None = None
    day: bool = True


@dataclass
class Day:
    label: str          # «сегодня», «завтра», «пт 15»
    low: float
    high: float
    probability: int
    code: int | None = None


@dataclass
class Weather:
    ok: bool = False
    error: str = ""
    temp: float | None = None
    feels: float | None = None
    wind: float | None = None
    gusts: float | None = None
    humidity: int | None = None
    pressure: float | None = None
    code: int | None = None
    is_day: bool = True
    # Направление, откуда дует, в градусах: 0 — северный ветер.
    wind_dir: int | None = None
    sunrise: str = ""
    sunset: str = ""
    # Местное время локации на момент запроса, "ЧЧ:ММ". Нужно картинке:
    # фон рисуется по времени там, где стоит локация, а не на сервере.
    local_time: str = ""
    hourly: list[Hour] = field(default_factory=list)
    daily: list[Day] = field(default_factory=list)


# --------------------------------------------------------------------------
#  Получение данных
# --------------------------------------------------------------------------

async def fetch(
    session: aiohttp.ClientSession, lat: float, lon: float, hours: int = 8,
    lang: str = "ru",
) -> Weather:
    from . import i18n

    if not lat and not lon:
        return Weather(ok=False, error=i18n.t(
            "weather.error.no_coords", lang, "нет координат — отправьте геопозицию заново"
        ))

    params = {
        "latitude": f"{lat}",
        "longitude": f"{lon}",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
                   "surface_pressure,weather_code,is_day",
        "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,"
                 "weather_code,sunrise,sunset",
        "timezone": "auto",
        "forecast_days": "4",
        "wind_speed_unit": "ms",
    }
    # Кэш держит СЫРОЙ ответ, а не разобранный: разбор зависит от языка,
    # и кэшировать его значило бы хранить по копии на язык при общем
    # сетевом запросе. Соседи по дому дают одинаковые координаты
    # с точностью до сотых — и столько же одинаковых запросов подряд.
    key = netcache.round_point(lat, lon)
    data = _CACHE.get(key)

    if data is None:
        try:
            async with session.get(_URL, params=params) as response:
                if response.status != 200:
                    status_text = i18n.t(
                        "weather.error.bad_status", lang, "сервис погоды вернул код"
                    )
                    return Weather(ok=False, error=f"{status_text} {response.status}")
                data = await response.json(content_type=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("Погода недоступна: %s", exc)
            return Weather(ok=False, error=i18n.t(
                "weather.error.fetch_failed", lang, "сбой получения погоды"
            ))
        _CACHE.put(key, data)

    return parse(data, hours, lang)


def cache_stats() -> dict:
    """Для /perf: видно ли, что кэш вообще работает."""
    return _CACHE.stats()


def forget_cache() -> None:
    """Сброс — в тестах и после смены настроек."""
    _CACHE.clear()


def parse(data: dict, hours: int = 8, lang: str = "ru") -> Weather:
    """Превращает ответ Open-Meteo в структуру. Вынесено ради тестируемости."""
    from . import i18n

    hour_suffix = i18n.t("weather.hour_suffix", lang, "ч")
    current = data.get("current") or {}
    weather = Weather(
        ok=True,
        temp=_number(current.get("temperature_2m")),
        feels=_number(current.get("apparent_temperature")),
        wind=_number(current.get("wind_speed_10m")),
        gusts=_number(current.get("wind_gusts_10m")),
        humidity=_integer(current.get("relative_humidity_2m")),
        pressure=_number(current.get("surface_pressure")),
        code=_integer(current.get("weather_code")),
        is_day=bool(current.get("is_day", 1)),
        wind_dir=_integer(current.get("wind_direction_10m")),
    )
    stamp = str(current.get("time") or "")
    if "T" in stamp:
        weather.local_time = stamp.split("T")[1][:5]

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    probabilities = hourly.get("precipitation_probability") or []
    codes = hourly.get("weather_code") or []
    day_flags = hourly.get("is_day") or []

    now = _now_index(times, current.get("time"))
    for index in range(now, min(now + hours, len(times))):
        temp = _number(temps[index] if index < len(temps) else None)
        if temp is None:
            continue
        stamp = times[index]
        label = (
            stamp.split("T")[1][:2] + hour_suffix if "T" in stamp
            else f"+{index - now}{hour_suffix}"
        )
        weather.hourly.append(
            Hour(
                label=label,
                temp=temp,
                probability=_integer(
                    probabilities[index] if index < len(probabilities) else 0
                ) or 0,
                code=_integer(codes[index]) if index < len(codes) else None,
                day=bool(day_flags[index]) if index < len(day_flags) else True,
            )
        )

    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    lows = daily.get("temperature_2m_min") or []
    highs = daily.get("temperature_2m_max") or []
    day_probabilities = daily.get("precipitation_probability_max") or []
    day_codes = daily.get("weather_code") or []
    sunrises = daily.get("sunrise") or []
    sunsets = daily.get("sunset") or []

    if sunrises:
        weather.sunrise = str(sunrises[0]).split("T")[-1][:5]
    if sunsets:
        weather.sunset = str(sunsets[0]).split("T")[-1][:5]

    for index, date in enumerate(dates[:4]):
        low = _number(lows[index] if index < len(lows) else None)
        high = _number(highs[index] if index < len(highs) else None)
        if low is None or high is None:
            continue
        weather.daily.append(
            Day(
                label=_day_label(date, index, lang),
                low=low,
                high=high,
                probability=_integer(
                    day_probabilities[index] if index < len(day_probabilities) else 0
                ) or 0,
                code=_integer(day_codes[index]) if index < len(day_codes) else None,
            )
        )

    return weather


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _now_index(times: list, current_time) -> int:
    """Первый час, который ещё не прошёл."""
    if not times:
        return 0
    marker = str(current_time or "")[:13]
    for index, stamp in enumerate(times):
        if str(stamp)[:13] >= marker:
            return index
    return 0


def _day_label(date: str, index: int, lang: str = "ru") -> str:
    from . import i18n

    if index == 0:
        return i18n.t("weather.today", lang, "сегодня")
    if index == 1:
        return i18n.t("weather.tomorrow", lang, "завтра")
    try:
        parsed = datetime.strptime(str(date)[:10], "%Y-%m-%d")
        weekdays = WEEKDAYS_EN if i18n.normalize(lang) == i18n.EN else WEEKDAYS
        return f"{weekdays[parsed.weekday()]} {parsed.day}"
    except ValueError:
        return str(date)[:10]


# --------------------------------------------------------------------------
#  Оформление
# --------------------------------------------------------------------------

def _sparkline(values: list[float]) -> list[str]:
    if not values:
        return []
    low, high = min(values), max(values)
    span = high - low
    if span < 0.5:  # ровная температура — рисуем середину
        return ["▄"] * len(values)
    return [SPARK[min(7, int((value - low) / span * 7.99))] for value in values]


def _temp(value: float | None) -> str:
    return f"{round(value):+d}°".replace("+", "") if value is not None else "—"


def render(weather: Weather, title: str = "", lang: str = "ru") -> str:
    """Собирает готовый HTML-блок сводки."""
    from . import i18n

    if not weather.ok:
        no_data = i18n.t("weather.error.no_data", lang, "нет данных о погоде")
        return f"⚠️ {weather.error or no_data}"

    name, icon = describe(weather.code, weather.is_day, lang)
    lines: list[str] = []
    if title:
        lines.append(title)

    head = f"{icon} <b>{_temp(weather.temp)}</b>"
    if name:
        head += f" — {name}"
    lines.append(head)

    details: list[str] = []
    if weather.feels is not None and weather.temp is not None:
        if abs(weather.feels - weather.temp) >= 1:
            feels = i18n.t("weather.feels", lang, "ощущается")
            details.append(f"{feels} {_temp(weather.feels)}")
    if weather.wind is not None:
        wind = f"💨 {weather.wind:.0f} м/с"
        if weather.gusts and weather.gusts - (weather.wind or 0) >= 3:
            wind += f" (порывы {weather.gusts:.0f})"
        details.append(wind)
    if weather.humidity is not None:
        details.append(f"💧 {weather.humidity}%")
    if weather.pressure:
        details.append(f"{weather.pressure * 0.750062:.0f} мм")
    if details:
        lines.append(" · ".join(details))

    if weather.hourly:
        bars = _sparkline([hour.temp for hour in weather.hourly])
        rows = []
        for hour, bar in zip(weather.hourly, bars):
            _, hour_icon = describe(hour.code, hour.day, lang)
            chance = f"{hour.probability:>3d}%" if hour.probability else "   ·"
            rows.append(f"{hour.label:<4}{hour_icon} {_temp(hour.temp):>4} {bar} {chance}")
        lines.append("")
        lines.append("<pre>" + "\n".join(rows) + "</pre>")

    if weather.daily:
        lines.append("")
        rows = []
        for day in weather.daily[:3]:
            _, day_icon = describe(day.code, True, lang)
            chance = f"  ☔️ {day.probability}%" if day.probability >= 20 else ""
            rows.append(
                f"{day.label:<8}{day_icon} {_temp(day.high):>4} … {_temp(day.low):<4}{chance}"
            )
        lines.append("<pre>" + "\n".join(rows) + "</pre>")

    if weather.sunrise and weather.sunset:
        lines.append(f"🌅 {weather.sunrise}   🌇 {weather.sunset}")

    return "\n".join(lines)


async def forecast(session: aiohttp.ClientSession, lat: float, lon: float,
                    lang: str = "ru") -> str:
    """Совместимость: получить и сразу оформить."""
    return render(await fetch(session, lat, lon, lang=lang), lang=lang)


async def deliver(
    chat_id: int | str,
    data: Weather,
    title: str,
    markup: Any = None,
    user: dict[str, Any] | None = None,
) -> None:
    """Отправить сводку в том виде, который выбрал пользователь.

    Единая точка выдачи. Раньше выбор между картинкой и текстом жил только
    в фоновой рассылке, а кнопка «Обновить погоду» слала текст всегда —
    настройка «Вид погоды: картинка» при ручном запросе просто не работала.
    Любое новое место, откуда уходит погода, должно звать эту функцию,
    а не render() напрямую.

    Текст остаётся запасным вариантом на всех отказах: нет Pillow, не
    отрисовалось, не ушло в Telegram. Молчания быть не должно.
    """
    from . import features, i18n
    from .tg import send_html

    lang = i18n.language_of(user)

    picture = None
    if features.enabled("weather_image"):
        # Глобальное принуждение перекрывает личный выбор: администрация
        # может включить картинку всем разом, не трогая настройки людей.
        # Личный выбор при этом сохраняется и вернётся, когда флаг снимут.
        if features.enabled("weather_image_all"):
            wants_picture = True
        else:
            wants_picture = (user or {}).get("weather_format") != "text"

        if wants_picture:
            from . import weather_image

            picture = weather_image.render(data, title, lang)

    if picture is None:
        await send_html(chat_id, render(data, title, lang), markup)
        return

    from aiogram.types import BufferedInputFile

    from .tg import bot

    try:
        await bot.send_photo(
            int(chat_id),
            BufferedInputFile(picture, filename="weather.png"),
            caption=title,
            reply_markup=markup,
        )
    except Exception:  # noqa: BLE001
        log.exception("Картинка погоды не ушла, отправляю текстом")
        await send_html(chat_id, render(data, title, lang), markup)
