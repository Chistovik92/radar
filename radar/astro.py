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
    (0.02, "новолуние"),
    (0.24, "растущий серп"),
    (0.27, "первая четверть"),
    (0.48, "растущая луна"),
    (0.52, "полнолуние"),
    (0.73, "убывающая луна"),
    (0.77, "последняя четверть"),
    (0.98, "убывающий серп"),
    (1.01, "новолуние"),
)


def moon(moment: datetime | None = None) -> Moon:
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

    name = PHASES[-1][1]
    for edge, title in PHASES:
        if phase < edge:
            name = title
            break

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
ROSE_SHORT = ("С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ")


def wind_sector(degrees: float | None) -> int | None:
    """Номер сектора розы ветров, 0 — север. None, если направления нет."""
    if degrees is None:
        return None
    return int((degrees % 360) / 45 + 0.5) % 8


def wind_name(degrees: float | None) -> str:
    sector = wind_sector(degrees)
    return ROSE[sector] if sector is not None else ""


def wind_short(degrees: float | None) -> str:
    sector = wind_sector(degrees)
    return ROSE_SHORT[sector] if sector is not None else ""


def beaufort(speed: float | None) -> str:
    """Словесная оценка силы ветра в м/с — понятнее голой цифры."""
    if speed is None:
        return ""
    if speed < 1.5:
        return "штиль"
    if speed < 3.3:
        return "лёгкий"
    if speed < 7.9:
        return "умеренный"
    if speed < 13.8:
        return "свежий"
    if speed < 20.7:
        return "сильный"
    return "штормовой"
