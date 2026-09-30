"""Приём присланных файлов: один вход для всех разделов бота.

До 5.9.0.1 у каждого раздела был свой обработчик `F.document`, и работал
только тот, что стоял в цепочке первым. Загрузка источников перехватывала
любой документ, поэтому cookies из `/cookies` молча уходили в список
каналов («Загрузка источников» отвечала «Список загружен» или разбирала
их как мусор). Тот же случай ждал любой следующий раздел, принимающий файл.

Теперь документ разбирается здесь, в три шага:

1. раздел, попросивший файл (`expect`), получает следующий файл человека
   в течение десяти минут — по имени файла не гадаем;
2. без ожидания вид определяет `classify` по имени и роли;
3. вид без обработчика не теряется: человеку отвечают, что делать.

Новый раздел подключается одним вызовом `register(kind, handler)`
и вызовом `expect` там, где просит файл.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import time
from typing import Awaitable, Callable

COOKIES = "cookies"
SOURCES = "sources"

# Сколько ждём файл после просьбы. Дольше — человек уже занят другим,
# и случайный документ не должен стать «ответом» на давний вопрос.
EXPECT_TTL = 600

Handler = Callable[..., Awaitable[None]]

_handlers: dict[str, Handler] = {}
_expected: dict[str, tuple[str, float]] = {}


def register(kind: str, handler: Handler) -> None:
    _handlers[kind] = handler


def handler_for(kind: str) -> Handler | None:
    return _handlers.get(kind)


def expect(user_key: str | int, kind: str, now: float | None = None) -> None:
    """Раздел просит файл: следующий документ человека — для него."""
    moment = now if now is not None else time.time()
    for owner in [owner for owner, (_, until) in _expected.items() if until < moment]:
        _expected.pop(owner, None)
    _expected[str(user_key)] = (kind, moment + EXPECT_TTL)


def expected(user_key: str | int, now: float | None = None) -> str | None:
    moment = now if now is not None else time.time()
    entry = _expected.get(str(user_key))
    if entry is None:
        return None
    if entry[1] < moment:
        _expected.pop(str(user_key), None)
        return None
    return entry[0]


def done(user_key: str | int) -> None:
    """Файл принят — ожидание снимается."""
    _expected.pop(str(user_key), None)


def looks_like_cookies(filename: str) -> bool:
    name = (filename or "").lower()
    return name.endswith(".txt") and "cookie" in name


def classify(user_key: str | int, filename: str, *, superadmin: bool,
             now: float | None = None) -> str:
    """Вид документа. Ожидание раздела сильнее догадки по имени."""
    waiting = expected(user_key, now)
    if waiting:
        return waiting
    if superadmin and looks_like_cookies(filename):
        return COOKIES
    # Прежнее поведение: непонятный документ — список источников
    # (простой текст каналов и db.json от 2.x называются как угодно).
    return SOURCES


def reset() -> None:
    _expected.clear()


__all__ = ["COOKIES", "SOURCES", "EXPECT_TTL", "register", "handler_for",
           "expect", "expected", "done", "classify", "looks_like_cookies", "reset"]
