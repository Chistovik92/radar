"""Управление RustDesk-сервером (hbbs/hbbr) из бота.

Открытая версия `rustdesk-server` не публикует API: число подключений
не узнать иначе, чем заглянув в `/proc/net/tcp{,6}` внутри контейнера
через `docker exec` (см. `radar/dockerapi.py`). Публичный ключ читается
проще — установщик монтирует каталог hbbs в бота отдельным, только для
чтения, томом (docker-compose.yml), так что это обычное чтение файла.

Управление (start/stop/restart) идёт через тот же сокет Docker, что
и «Обновление из панели» (`radar/updater.py`) — тот же уровень риска
(сокет внутри контейнера равносилен root на хосте), поэтому раздел
защищён отдельным флагом `rustdesk`, выключенным по умолчанию.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import re

from . import config, dockerapi, features

log = logging.getLogger("radar.rustdesk")

HBBS = config.RUSTDESK_HBBS_CONTAINER
HBBR = config.RUSTDESK_HBBR_CONTAINER
# Стандартные порты rustdesk-server: 21116 — служебный канал hbbs
# (по нему клиент числится «онлайн»), 21117 — релей hbbr (активная
# сессия управления). Это не настройка — если кто-то развернул
# RustDesk на нестандартных портах, подсчёт подключений будет неверным,
# но остальные функции (ключ, restart) от порта не зависят.
ID_PORT = 21116
RELAY_PORT = 21117

_ACTIONS = ("start", "stop", "restart")


def ready() -> tuple[bool, str]:
    """Можно ли обращаться к RustDesk отсюда. Второе — причина отказа."""
    if not features.enabled("rustdesk"):
        return False, "Возможность «RustDesk» выключена."
    if not os.path.exists(dockerapi.SOCKET):
        return False, ("Сокет Docker не проброшен в контейнер: управлять "
                       "RustDesk нечем.")
    if not os.access(dockerapi.SOCKET, os.W_OK):
        return False, ("Сокет Docker виден, но недоступен на запись: "
                       "контейнеру не хватает группы docker (DOCKER_GID).")
    return True, ""


async def deployed() -> tuple[bool, str]:
    """Развёрнуты ли контейнеры RustDesk на этом демоне.

    Отличает «ещё не разворачивали» от «развёрнуто, но не отвечает».
    Разница видна человеку: в первом случае нужна не кнопка перезапуска,
    которая заведомо ответит «No such container», а две строки в `.env`
    и один запуск профиля.
    """
    allowed, reason = ready()
    if not allowed:
        return False, reason

    try:
        session = await dockerapi.session()
    except Exception as exc:  # noqa: BLE001
        log.error("Сокет Docker недоступен: %s", exc)
        return False, "Сокет Docker недоступен."

    async with session:
        for name in (HBBS, HBBR):
            if not await dockerapi.container_exists(session, name):
                return False, (
                    f"Контейнер {name} не найден: RustDesk на этом сервере "
                    "ещё не разворачивали."
                )
    return True, ""


def client_info() -> tuple[bool, str | dict]:
    """Адрес и ключ для настройки клиента RustDesk.

    Ключ читается как обычный файл — том с данными hbbs смонтирован
    в бота отдельно, только для чтения (см. docker-compose.yml).
    """
    allowed, reason = ready()
    if not allowed:
        return False, reason
    if not config.RUSTDESK_PUBLIC_HOST:
        return False, ("Внешний адрес сервера не задан (RUSTDESK_PUBLIC_HOST "
                       "в .env) — без него клиенту некуда подключаться.")
    try:
        with open(config.RUSTDESK_KEY_PATH, "r", encoding="utf-8") as handle:
            key = handle.read().strip()
    except OSError as exc:
        log.warning("Публичный ключ RustDesk не прочитан: %s", exc)
        return False, ("Файл ключа не найден — сервер ещё не разворачивался "
                       "или не успел создать пару ключей при первом запуске.")
    if not key:
        return False, "Файл ключа пуст — подождите, пока hbbs его создаст."
    return True, {
        "host": config.RUSTDESK_PUBLIC_HOST,
        "id_port": ID_PORT,
        "relay_port": RELAY_PORT,
        "key": key,
    }


# /proc/net/tcp{,6}: поля разделены пробелами, местный адрес — второе поле
# в виде "HEXIP:HEXPORT" (IP — в порядке байт хоста, порт — в BE, поэтому
# порт читается напрямую), состояние — четвёртое поле, "01" = ESTABLISHED.
_TCP_LINE_RE = re.compile(r"^\s*\d+:\s+\S+:([0-9A-Fa-f]+)\s+\S+\s+([0-9A-Fa-f]{2})\b")


def _count_established(text: str, port: int) -> int:
    """Считает строки /proc/net/tcp{,6} в состоянии ESTABLISHED на порту."""
    target = f"{port:04X}"
    count = 0
    for line in text.splitlines():
        match = _TCP_LINE_RE.match(line)
        if not match:
            continue
        local_port, state = match.groups()
        if local_port.upper() == target and state == "01":
            count += 1
    return count


async def connection_counts() -> tuple[bool, str | dict]:
    """Число установленных соединений на hbbs (ID_PORT) и hbbr (RELAY_PORT).

    Это оценка по TCP-соединениям, а не официальная метрика RustDesk —
    открытая версия сервера её просто не публикует.
    """
    allowed, reason = ready()
    if not allowed:
        return False, reason

    cmd = ["sh", "-c", "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null"]
    try:
        session = await dockerapi.session()
    except Exception as exc:  # noqa: BLE001
        log.error("Сокет Docker недоступен: %s", exc)
        return False, "Сокет Docker недоступен."

    async with session:
        ok, out = await dockerapi.exec_run(session, HBBS, cmd)
        if not ok:
            return False, f"Не удалось прочитать состояние {HBBS}: {out}"
        hbbs_count = _count_established(out, ID_PORT)

        ok, out = await dockerapi.exec_run(session, HBBR, cmd)
        if not ok:
            return False, f"Не удалось прочитать состояние {HBBR}: {out}"
        relay_count = _count_established(out, RELAY_PORT)

    return True, {"hbbs": hbbs_count, "hbbr": relay_count}


async def control(action: str) -> tuple[bool, str]:
    """Применяет action (start/stop/restart) к hbbs и hbbr по очереди.

    Ошибка одного контейнера не прерывает попытку для второго — обе
    причины (если есть) попадают в итоговый текст.
    """
    if action not in _ACTIONS:
        return False, f"неизвестное действие: {action}"
    allowed, reason = ready()
    if not allowed:
        return False, reason

    try:
        session = await dockerapi.session()
    except Exception as exc:  # noqa: BLE001
        log.error("Сокет Docker недоступен: %s", exc)
        return False, "Сокет Docker недоступен."

    problems: list[str] = []
    async with session:
        for name in (HBBS, HBBR):
            ok, msg = await dockerapi.container_action(session, name, action)
            if not ok:
                problems.append(f"{name}: {msg}")

    if problems:
        return False, "; ".join(problems)
    return True, ""
