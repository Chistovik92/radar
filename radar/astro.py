"""Фаза луны и роза ветров.

Расчёты вынесены отдельно: они чистые, не зависят ни от сети, ни от
Pillow, и потому проверяются тестами без заглушек.

Фаза считается по среднему синодическому месяцу от известного новолуния.
Точность такого приближения — около суток на горизонте десятилетий, чего
для картинки с погодой более чем достаточно; астрономическая библиотека
ради подписи «растущая луна» в образ не тянется.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# Новолуние 6 января 2000, 18:14 UTC — общепринятая опорная точка.
_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
SYNODIC = 29.530588853          # средний синодический месяц, суток


@dataclass(frozen=True)
class Moon:
    """Состояние луны на момент времени."""

    age: float                  # возраст в сутках от новолуния
    phase: float                # 0.0 — новолуние, 0.5 — полнолуние
    illumination: float         # доля освещённого диска, 0…1
    name: str                   # название фазы по-русски
    waxing: bool                # растёт ли


PHASES = (
    (0.02, "новолуние", "moon.new"),
    (0.24, "растущий серп", "moon.waxing_crescent"),
    (0.27, "первая четверть", "moon.first_quarter"),
    (0.48, "растущая луна", "moon.waxing_gibbous"),
    (0.52, "полнолуние", "moon.full"),
    (0.73, "убывающая луна", "moon.waning_gibbous"),
    (0.77, "последняя четверть", "moon.last_quarter"),
    (0.98, "убывающий серп", "moon.waning_crescent"),
    (1.01, "новолуние", "moon.new"),
)


def moon(moment: datetime | None = None, lang: str = "ru") -> Moon:
    """Фаза луны на указанный момент (по умолчанию — сейчас)."""
    if moment is None:
        moment = datetime.now(timezone.utc)
    elif moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    days = (moment - _NEW_MOON).total_seconds() / 86400.0
    age = days % SYNODIC
    phase = age / SYNODIC

    # Освещённость меняется по косинусу: ноль в новолуние, единица в полнолуние.
    from math import cos, pi

    illumination = (1 - cos(2 * pi * phase)) / 2

    from . import i18n

    russian, key = PHASES[-1][1], PHASES[-1][2]
    for edge, title, phase_key in PHASES:
        if phase < edge:
            russian, key = title, phase_key
            break
    name = i18n.t(key, lang, russian)

    return Moon(
        age=age,
        phase=phase,
        illumination=illumination,
        name=name,
        waxing=phase < 0.5,
    )


# --- ветер ----------------------------------------------------------------

ROSE = (
    "северный", "северо-восточный", "восточный", "юго-восточный",
    "южный", "юго-западный", "западный", "северо-западный",
)
ROSE_KEYS = ("wind.n", "wind.ne", "wind.e", "wind.se",
             "wind.s", "wind.sw", "wind.w", "wind.nw")
ROSE_SHORT = ("С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ")
ROSE_SHORT_EN = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# Границы шкалы Бофорта в м/с и названия: русское — запасной вариант.
FORCE = (
    (1.5, "штиль", "wind.calm"),
    (3.3, "лёгкий", "wind.light"),
    (7.9, "умеренный", "wind.moderate"),
    (13.8, "свежий", "wind.fresh"),
    (20.7, "сильный", "wind.strong"),
)
FORCE_TOP = ("штормовой", "wind.storm")


def wind_sector(degrees: float | None) -> int | None:
    """Номер сектора розы ветров, 0 — север. None, если направления нет."""
    if degrees is None:
        return None
    return int((degrees % 360) / 45 + 0.5) % 8


def wind_name(degrees: float | None, lang: str = "ru") -> str:
    from . import i18n

    sector = wind_sector(degrees)
    if sector is None:
        return ""
    return i18n.t(ROSE_KEYS[sector], lang, ROSE[sector])


def wind_short(degrees: float | None, lang: str = "ru") -> str:
    from . import i18n

    sector = wind_sector(degrees)
    if sector is None:
        return ""
    table = ROSE_SHORT_EN if i18n.normalize(lang) == i18n.EN else ROSE_SHORT
    return table[sector]


def beaufort(speed: float | None, lang: str = "ru") -> str:
    """Словесная оценка силы ветра в м/с — понятнее голой цифры."""
    from . import i18n

    if speed is None:
        return ""
    for limit, russian, key in FORCE:
        if speed < limit:
            return i18n.t(key, lang, russian)
    return i18n.t(FORCE_TOP[1], lang, FORCE_TOP[0])
