"""Язык командной строки: русский и английский (с 5.9.3.1).

Строки консоли не идут через `radar/i18n.py`: тот словарь — для бота и
привязан к языку пользователя из базы, а у консоли пользователя нет. Здесь
язык выбирает оператор, и пара «русский — английский» лежит прямо в вызове:
перевод нельзя забыть, потому что без него вызов не написать, и нельзя
рассинхронизировать — обе строки видны рядом.

Порядок выбора: `--lang` в командной строке, затем `RADAR_LANG`, затем
`LANG`/`LC_ALL` (начинается с `ru` — русский, иначе английский), иначе
русский — язык проекта по умолчанию.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os

RU, EN = "ru", "en"
LANGUAGES = (RU, EN)

_current = RU


def detect(argv: list[str], env: dict[str, str] | None = None) -> str:
    """Язык по аргументам и окружению. Аргументы не разбираются целиком —
    справка и ошибки argparse тоже должны выйти на нужном языке, а парсер
    ещё не построен."""
    env = os.environ if env is None else env
    for index, item in enumerate(argv):
        if item == "--lang" and index + 1 < len(argv):
            value = argv[index + 1].lower()
            if value in LANGUAGES:
                return value
        if item.startswith("--lang="):
            value = item.split("=", 1)[1].lower()
            if value in LANGUAGES:
                return value
    explicit = (env.get("RADAR_LANG") or "").strip().lower()
    if explicit in LANGUAGES:
        return explicit
    system = (env.get("LC_ALL") or env.get("LANG") or "").strip().lower()
    if system and system not in ("c", "posix") and not system.startswith("c."):
        return RU if system.startswith("ru") else EN
    return RU


def set_lang(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else RU


def current() -> str:
    return _current


def L(ru: str, en: str) -> str:  # noqa: N802 — короткое имя нужно ради читаемости вызовов
    """Строка на языке консоли."""
    return ru if _current == RU else en
