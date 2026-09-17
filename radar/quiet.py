"""Тихие часы и антиспам оповещений.

Две разные задачи с общей целью — чтобы сигналы бота оставались значимыми.

**Тихие часы** придерживают несрочное до утра. Военные угрозы и МЧС проходят
всегда: смысл системы в том, чтобы разбудить, когда это действительно нужно.
Авария с водой в три часа ночи такой ценности не имеет — она подождёт.

**Антиспам** не даёт отправить одно и то же событие дважды по одной локации.
Городские каналы дублируют сообщения друг за другом, и без этого пользователь
получал бы одну аварию пятью разными формулировками.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger("radar.quiet")

# Категории, которые проходят тихие часы в любом случае
URGENT = frozenset({"bpla", "mchs"})

# Сколько часов помнить отправленное, чтобы не повторяться
MEMORY_HOURS = 12

_WORD = re.compile(r"[а-яёa-z0-9]+")


# --------------------------------------------------------------------------
#  Тихие часы
# --------------------------------------------------------------------------

def parse_time(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (value or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def in_quiet_hours(user: dict[str, Any], now: datetime) -> bool:
    """Идут ли сейчас тихие часы у пользователя."""
    start = parse_time(str(user.get("quiet_from") or ""))
    end = parse_time(str(user.get("quiet_to") or ""))
    if start is None or end is None:
        return False

    minutes = now.hour * 60 + now.minute
    begin = start[0] * 60 + start[1]
    finish = end[0] * 60 + end[1]

    if begin == finish:
        return False
    if begin < finish:
        return begin <= minutes < finish
    # Интервал через полночь — обычный случай для ночного режима
    return minutes >= begin or minutes < finish


def should_hold(categories: set[str] | list[str], user: dict[str, Any],
                now: datetime) -> bool:
    """Придержать ли оповещение до окончания тихих часов."""
    if not in_quiet_hours(user, now):
        return False
    return not (URGENT & set(categories))


def quiet_summary(user: dict[str, Any], lang: str = "") -> str:
    from . import i18n

    start = str(user.get("quiet_from") or "")
    end = str(user.get("quiet_to") or "")
    if not start or not end:
        return i18n.t("settings.quiet.none", lang or i18n.language_of(user), "не заданы")
    return f"{start} — {end}"


# --------------------------------------------------------------------------
#  Антиспам
# --------------------------------------------------------------------------

def _stem(word: str) -> str:
    """Грубая основа слова: обрезка до четырёх букв.

    Полноценная морфология здесь не нужна и была бы лишней зависимостью.
    Задача узкая — понять, что «на улице Чапаева» и «улица Чапаева»
    описывают одно и то же. Обрезка снимает падежные окончания, а слова
    короче пяти букв остаются как есть.
    """
    return word if len(word) <= 4 else word[:4]


def fingerprint(text: str) -> str:
    """Отпечаток сообщения, устойчивый к различиям формулировок.

    Городские каналы пересказывают одно событие по-разному: меняются
    вводные слова, порядок предложений, падежи. Сравнение по набору
    основ значимых слов ловит такие повторы, а точное сравнение — нет.
    """
    words = _WORD.findall((text or "").lower().replace("ё", "е"))
    significant = sorted({_stem(word) for word in words if len(word) > 3})[:24]
    return hashlib.sha1(" ".join(significant).encode("utf-8")).hexdigest()[:16]


@dataclass
class Deliveries:
    """Что и когда уже отправлено. Хранится в памяти процесса."""

    seen: dict[str, float] = field(default_factory=dict)

    def key(self, user_key: str, location_id: str, text: str) -> str:
        return f"{user_key}:{location_id}:{fingerprint(text)}"

    def already(self, user_key: str, location_id: str, text: str,
                now: float | None = None) -> bool:
        moment = now if now is not None else time.time()
        self._forget(moment)
        return self.key(user_key, location_id, text) in self.seen

    def remember(self, user_key: str, location_id: str, text: str,
                 now: float | None = None) -> None:
        moment = now if now is not None else time.time()
        self.seen[self.key(user_key, location_id, text)] = moment

    def _forget(self, moment: float) -> None:
        edge = moment - MEMORY_HOURS * 3600
        stale = [key for key, stamp in self.seen.items() if stamp < edge]
        for key in stale:
            self.seen.pop(key, None)

    def __len__(self) -> int:
        return len(self.seen)


deliveries = Deliveries()


def merge_similar(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Убирает из пачки сообщения, повторяющие друг друга по смыслу.

    Работает внутри одного цикла: несколько источников часто сообщают
    об одном событии почти одновременно.
    """
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind, text in messages:
        mark = fingerprint(text)
        if mark in seen:
            continue
        seen.add(mark)
        result.append((kind, text))
    return result


# --------------------------------------------------------------------------
#  Отложенные сообщения
# --------------------------------------------------------------------------

@dataclass
class Held:
    """Оповещение, придержанное до конца тихих часов."""

    user_key: str
    text: str
    created: float = field(default_factory=time.time)
    # Сколько раз пытались отдать и не смогли. Придержанное отличается
    # от обычной тревоги тем, что второго источника у неё нет: событие
    # давно вымылось из `seen`, и не отданное здесь потеряно навсегда.
    # Поэтому промах возвращает запись в очередь — но не бесконечно:
    # у заблокировавшего бота отправка не удастся никогда.
    attempts: int = 0


# Пределы очереди. Раньше был один общий на 200 записей, и при обрезке
# страдал не тот, кто её переполнил: активный получатель вытеснял чужие
# придержанные тревоги. Теперь предел свой у каждого, а общий остаётся
# только защитой от разрастания памяти на одноплатнике.
PER_USER = 30
TOTAL = 300

# Сколько держать невостребованное. Тихие часы длятся ночь; запись,
# пролежавшая сутки, относится к человеку, который у бота больше
# не появляется, — отдавать её через неделю бессмысленно.
HOLD_TTL_HOURS = 24

_held: list[Held] = []
# Очередь изменилась и не сохранена. Хранение вынесено наружу: этот
# модуль обязан оставаться без зависимостей от базы, иначе офлайн-тесты
# тянут за собой половину бота.
_dirty = False


def _trim(user_key: str) -> None:
    """Держит очередь в пределах: сначала свой, потом общий."""
    mine = [item for item in _held if item.user_key == user_key]
    if len(mine) > PER_USER:
        drop = {id(item) for item in mine[:-PER_USER]}
        _held[:] = [item for item in _held if id(item) not in drop]
    del _held[:-TOTAL]


# Сколько раз пробовать отдать придержанное, прежде чем признать
# получателя недостижимым.
MAX_ATTEMPTS = 3


def hold(user_key: str, text: str, created: float | None = None,
         attempts: int = 0) -> bool:
    """Ставит оповещение в очередь. False — запись отброшена."""
    global _dirty

    if attempts >= MAX_ATTEMPTS:
        log.warning("Придержанное для %s отброшено: получатель недостижим",
                    user_key)
        return False
    _held.append(Held(
        user_key=user_key,
        text=text,
        created=created if created is not None else time.time(),
        attempts=attempts,
    ))
    _trim(user_key)
    _dirty = True
    return True


def release_items(user_key: str, user: dict[str, Any],
                  now: datetime) -> list[Held]:
    """Забирает придержанные записи целиком, со счётчиком попыток."""
    global _dirty

    if in_quiet_hours(user, now):
        return []

    mine = [item for item in _held if item.user_key == user_key]
    if not mine:
        return []
    _held[:] = [item for item in _held if item.user_key != user_key]
    _dirty = True
    return mine


def release(user_key: str, user: dict[str, Any], now: datetime) -> list[str]:
    """Забирает придержанные сообщения, если тихие часы закончились."""
    return [item.text for item in release_items(user_key, user, now)]


def held_count() -> int:
    return len(_held)


# --------------------------------------------------------------------------
#  Сохранение очереди между перезапусками (с 4.9.8.14)
# --------------------------------------------------------------------------
#
# До 4.9.8.14 очередь жила только в памяти процесса: перезапуск среди ночи
# — и всё придержанное исчезало молча. Для системы оповещения это потеря
# тревог, пусть и несрочных, поэтому очередь переживает рестарт. Сам модуль
# базы не знает: он отдаёт и принимает обычные списки словарей, а пишет
# их тот, у кого база уже под рукой.

def dirty() -> bool:
    """Есть ли несохранённые изменения."""
    return _dirty


def mark_saved() -> None:
    global _dirty
    _dirty = False


def snapshot() -> list[dict[str, Any]]:
    """Очередь в виде, пригодном для записи в базу."""
    return [
        {
            "user": item.user_key,
            "text": item.text,
            "created": item.created,
            "attempts": item.attempts,
        }
        for item in _held
    ]


def restore(rows: Any, now: float | None = None) -> int:
    """Поднимает очередь из снимка. Возвращает число восстановленных.

    Данные приходят из базы и могли быть записаны прежней версией,
    поэтому каждая строка проверяется: битый снимок не должен мешать
    боту подняться.
    """
    global _dirty
    moment = now if now is not None else time.time()
    edge = moment - HOLD_TTL_HOURS * 3600

    restored: list[Held] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        user_key = str(row.get("user") or "")
        text = str(row.get("text") or "")
        if not user_key or not text:
            continue
        try:
            created = float(row.get("created") or 0.0)
        except (TypeError, ValueError):
            created = moment
        if created < edge:
            continue
        try:
            attempts = int(row.get("attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts >= MAX_ATTEMPTS:
            continue
        restored.append(Held(user_key=user_key, text=text, created=created,
                             attempts=attempts))

    _held[:] = restored
    for user_key in {item.user_key for item in restored}:
        _trim(user_key)
    _dirty = False
    return len(_held)
