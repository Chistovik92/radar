#!/usr/bin/env python3
"""Часовой пояс пользователя.

До 4.8.4.4 время было общим на всю систему: тихие часы, погода в заданный
час и время доставки подборок считались по часовому поясу сервера. Пока
все пользователи жили в одном городе, это работало. С появлением людей из
других поясов «погода в 8:00» стала означать восемь утра у сервера — то
есть пять утра у одного и одиннадцать у другого.

Хранится **смещение от UTC**, а не имя зоны IANA. Причина прагматичная:
человек выбирает пояс из списка, и список из смещений короче и понятнее
списка из трёхсот зон. Плата за это — переход на летнее время: смещение
его не отслеживает. Для России это безразлично (перевода стрелок нет
с 2014 года), для Европы и США пользователь раз в полгода уедет на час
и поправит выбор сам.

Подпись зависит от языка. По-русски отсчёт идёт от Москвы («МСК+2»):
так на русскоязычном пространстве говорят о времени, и «UTC+5» человеку
из Саратова ничего не сообщает. По-английски — от Гринвича («UTC+5»).

Пустое значение означает «не выбран»: тогда берётся часовой пояс сервера,
и поведение остаётся ровно прежним. Так обновление никому ничего не ломает.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

# Москва — точка отсчёта русских подписей.
MOSCOW = 180

# Хранимый вид: «+03:00», «-05:30». Знак обязателен, чтобы «03:00» нельзя
# было спутать со временем суток при чтении .env или базы глазами.
_STORED = re.compile(r"^([+-])(\d{1,2}):([0-5]\d)$")

# Пределы настоящих часовых поясов: от UTC−12 до UTC+14.
MIN_OFFSET = -12 * 60
MAX_OFFSET = 14 * 60

# Целые часы — их выбирает подавляющее большинство.
WHOLE_HOURS: tuple[int, ...] = tuple(
    range(MIN_OFFSET, MAX_OFFSET + 1, 60)
)

# Пояса с половиной и четвертью часа. Вынесены на второй экран: в общем
# списке они удлиняют его в полтора раза ради нескольких стран.
FRACTIONAL: tuple[int, ...] = (
    -9 * 60 - 30,      # Маркизские острова
    3 * 60 + 30,       # Иран
    4 * 60 + 30,       # Афганистан
    5 * 60 + 30,       # Индия, Шри-Ланка
    5 * 60 + 45,       # Непал
    6 * 60 + 30,       # Мьянма
    8 * 60 + 45,       # Юго-запад Австралии
    9 * 60 + 30,       # Центральная Австралия
    10 * 60 + 30,      # Лорд-Хау
    12 * 60 + 45,      # Чатем
)


def parse(value: Any) -> int | None:
    """Смещение в минутах из хранимой строки. None — не задано или мусор."""
    match = _STORED.match(str(value or "").strip())
    if not match:
        return None
    sign = -1 if match.group(1) == "-" else 1
    minutes = sign * (int(match.group(2)) * 60 + int(match.group(3)))
    if not MIN_OFFSET <= minutes <= MAX_OFFSET:
        return None
    return minutes


def render(minutes: int) -> str:
    """Хранимый вид смещения: «+03:00»."""
    sign = "-" if minutes < 0 else "+"
    total = abs(int(minutes))
    return f"{sign}{total // 60:02d}:{total % 60:02d}"


def _suffix(minutes: int) -> str:
    """Хвост подписи: «», «+2», «−3:30»."""
    if minutes == 0:
        return ""
    sign = "-" if minutes < 0 else "+"
    total = abs(int(minutes))
    hours, rest = divmod(total, 60)
    if rest:
        return f"{sign}{hours}:{rest:02d}"
    return f"{sign}{hours}"


def label(minutes: int, lang: str = "ru") -> str:
    """Подпись пояса: «МСК+2» по-русски, «UTC+5» по-английски."""
    if (lang or "ru").lower().startswith("en"):
        return f"UTC{_suffix(minutes)}"
    return f"МСК{_suffix(minutes - MOSCOW)}"


def server_offset() -> int:
    """Смещение часового пояса сервера — запасной вариант."""
    shift = datetime.now().astimezone().utcoffset()
    if shift is None:
        return 0
    return int(shift.total_seconds() // 60)


def offset_of(user: dict[str, Any] | None) -> int:
    """Смещение пользователя. Не выбрано — берём серверное, как раньше."""
    chosen = parse((user or {}).get("tz"))
    return server_offset() if chosen is None else chosen


def chosen(user: dict[str, Any] | None) -> bool:
    """Выбирал ли пользователь пояс сам."""
    return parse((user or {}).get("tz")) is not None


def local_now(user: dict[str, Any] | None, now_utc: datetime) -> datetime:
    """Наивное местное время пользователя.

    Наивное намеренно: весь код вокруг — тихие часы, погода, подборки —
    сравнивает часы и минуты, и осведомлённая о поясе дата там только
    мешала бы. Часовой пояс уже учтён смещением.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return (now_utc.astimezone(timezone.utc)
            + timedelta(minutes=offset_of(user))).replace(tzinfo=None)


def user_label(user: dict[str, Any] | None, lang: str = "ru") -> str:
    """Подпись пояса пользователя для кнопок и сводок."""
    return label(offset_of(user), lang)
