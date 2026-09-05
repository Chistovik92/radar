"""Файл cookies для закрытых площадок — приём и подключение.

Некоторые записи («закрыта настройками приватности», возрастные
ограничения) yt-dlp открывает только с cookies вошедшего человека.
До 4.9.4.5 файл требовалось принести на сервер руками — SCP, путь
в `.env`, перезапуск. Теперь суперадминистратор просто присылает
`cookies.txt` в чат: бот проверяет формат, кладёт файл и подключает.

Формат — Netscape (те же строки, что делают расширения-экспортёры
и параметр `--cookies` самого yt-dlp). Ничего экзотического.

Файл держит сессию аккаунта, поэтому прав у него как у секрета:
600, и скачивание его назад из бота не предусмотрено — отдал файл,
отдал вход.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("radar.cookies")

PATH = "data/cookies.txt"

# Ограничения приёма: файл cookies — текст, и 512 КБ хватает с запасом
# на сотни доменов. Больше — не cookies, а что-то перепутали.
MAX_BYTES = 512 * 1024

# Минимум строк с куками, ниже которого файл кукой быть не может.
# Заголовок с "# HTTP Cookie File" не считается.
MIN_COOKIE_LINES = 3


def parse_errors(text: str) -> list[str]:
    """Чем файл не похож на cookies в формате Netscape. Пусто — похож.

    Разбор нарочно придирчивый: файл попадает в загрузчик видео,
    и молча подсунуть ему мусор значило бы получить загадочные отказы
    yt-dlp вместо понятного «файл не тот».
    """
    problems: list[str] = []

    if not text.strip():
        return ["файл пуст"]

    lines = [line.rstrip("\r\n") for line in text.splitlines()]
    cookie_lines = [
        line for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(cookie_lines) < MIN_COOKIE_LINES:
        problems.append(
            f"кук в файле меньше {MIN_COOKIE_LINES} — похоже, это не "
            "выгрузка cookies"
        )

    wellformed = 0
    for line in cookie_lines[:50]:
        # Домен, флаг, путь, безопасность, срок, имя, значение —
        # семь полей табуляцией.
        if len(line.split("\t")) >= 7:
            wellformed += 1
    if cookie_lines and wellformed == 0:
        problems.append(
            "строки не похожи на формат Netscape: ожидается семь полей "
            "через табуляцию (расширения «Get cookies.txt LOCALLY» "
            "выгружают именно так)"
        )

    return problems


def store(data: bytes) -> tuple[bool, str]:
    """Сохраняет файл и подключает его. (ok, пояснение)."""
    if not data:
        return False, "файл пуст"
    if len(data) > MAX_BYTES:
        return False, f"файл больше {MAX_BYTES // 1024} КБ — это не cookies"

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False, "файл не текстовый: cookies выгружаются текстом"

    problems = parse_errors(text)
    if problems:
        return False, "; ".join(problems)

    os.makedirs(os.path.dirname(PATH) or ".", exist_ok=True)
    with open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.chmod(PATH, 0o600)

    # Подключаем путь в .env: до правки MEDIA_COOKIES ни на что
    # не указывал, и человеку пришлось бы лезть в файл руками.
    from . import secrets

    secrets.write("MEDIA_COOKIES", PATH)
    log.info("Файл cookies обновлён: %d байт", len(data))
    return True, ""


def connected() -> bool:
    """Подключён ли файл и существует ли он."""
    from . import config, secrets

    value = (secrets.get("MEDIA_COOKIES") or config.MEDIA_COOKIES).strip()
    if not value:
        return False
    # Путь, заданный вручную, может быть любым — чей он, не проверяем.
    return os.path.isfile(value) or value == PATH


def describe() -> str:
    """Состояние для сообщения: подключён ли файл и когда обновлён."""
    if not connected():
        return "Cookies не подключены."
    try:
        stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(os.path.getmtime(PATH)))
    except OSError:
        return "Cookies подключены."
    return f"Cookies подключены, обновлены {stamp}."
