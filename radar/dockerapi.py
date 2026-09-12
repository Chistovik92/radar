"""Общий клиент Docker Engine API поверх Unix-сокета.

Вынесено из `radar/updater.py` в 4.9.8.4: `radar/rustdesk.py` управляет
ЧУЖИМИ контейнерами (`hbbs`/`hbbr`) через тот же сокет и той же ценой
доступа (сокет внутри контейнера равносилен root на хосте), и второй
копии `_session()`/константы версии API проект бы не пережил безболезненно —
любая правка версии API пришлось бы вносить в двух местах и забывать
об одном.

Здесь же — операции, которых раньше в проекте не было: `exec` внутрь
чужого контейнера (нужен, чтобы прочитать `/proc/net/tcp` — открытая
версия RustDesk не отдаёт число подключений никаким API) и
`start`/`stop`/`restart` по имени контейнера.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

log = logging.getLogger("radar.dockerapi")

SOCKET = "/var/run/docker.sock"
API = "http://localhost/v1.41"


async def session():
    """Сессия к сокету Docker. Импорт внутри — офлайн-проверки без aiohttp."""
    import aiohttp

    return aiohttp.ClientSession(
        connector=aiohttp.UnixConnector(path=SOCKET),
        timeout=aiohttp.ClientTimeout(total=30),
    )


def _demux(raw: bytes) -> str:
    """Разбирает мультиплексированный поток `docker exec` без TTY.

    На каждый кусок — 8-байтный заголовок (1 байт тип потока: stdin
    не используется, stdout и stderr тут не различаются намеренно —
    для `cat` это не важно; 3 нуля; 4 байта BE-длины), затем сама
    полезная нагрузка. С включённым TTY заголовков нет вовсе, но здесь
    TTY всегда выключен — иначе стрим нельзя было бы разобрать однозначно.
    """
    out = bytearray()
    offset = 0
    while offset + 8 <= len(raw):
        length = int.from_bytes(raw[offset + 4:offset + 8], "big")
        start = offset + 8
        end = start + length
        out += raw[start:end]
        offset = end
    return out.decode("utf-8", errors="replace")


async def exec_run(session_, name: str, cmd: list[str]) -> tuple[bool, str]:
    """Выполняет команду внутри контейнера `name`, отдаёт (успех, вывод).

    Два запроса: `POST /containers/{name}/exec` создаёт исполнение,
    `POST /exec/{id}/start` его запускает и возвращает поток целиком
    (команды здесь короткие — `cat` файла или `/proc/net/tcp` — поэтому
    буферизация всего ответа, а не построчное чтение, оправдана).
    """
    try:
        async with session_.post(
            f"{API}/containers/{name}/exec",
            json={"AttachStdout": True, "AttachStderr": True, "Cmd": cmd, "Tty": False},
        ) as response:
            body = await response.json()
            if response.status not in (200, 201):
                message = str(body.get("message") or body) if isinstance(body, dict) else str(body)
                return False, message
            exec_id = body.get("Id") if isinstance(body, dict) else None
            if not exec_id:
                return False, "Docker не вернул идентификатор исполнения"

        async with session_.post(
            f"{API}/exec/{exec_id}/start",
            json={"Detach": False, "Tty": False},
        ) as response:
            raw = await response.read()
            if response.status != 200:
                return False, raw.decode("utf-8", errors="replace")[:200]
            return True, _demux(raw)
    except Exception as exc:  # noqa: BLE001
        log.exception("exec в контейнере %s не выполнен", name)
        return False, str(exc)


async def container_exists(session_, name: str) -> bool:
    """Есть ли такой контейнер у демона (хоть запущенный, хоть нет).

    Нужно, чтобы отличить «RustDesk ещё не разворачивали» от «развёрнут,
    но сломался»: в первом случае человеку нужна инструкция, а не кнопка
    перезапуска, которая заведомо ответит «No such container».
    """
    try:
        async with session_.get(f"{API}/containers/{name}/json") as response:
            return response.status == 200
    except Exception:  # noqa: BLE001
        log.debug("Проверка контейнера %s не удалась", name, exc_info=True)
        return False


async def container_action(session_, name: str, action: str) -> tuple[bool, str]:
    """`POST /containers/{name}/{start|stop|restart}` — по имени: Docker
    API принимает имя наравне с ID, отдельный поиск ID не нужен."""
    if action not in ("start", "stop", "restart"):
        return False, f"неизвестное действие: {action}"
    try:
        async with session_.post(f"{API}/containers/{name}/{action}") as response:
            if response.status in (204, 304):
                return True, ""
            if response.status == 404:
                return False, f"контейнер {name} не найден"
            body = await response.text()
            return False, body[:200]
    except Exception as exc:  # noqa: BLE001
        log.exception("Действие %s над контейнером %s не выполнено", action, name)
        return False, str(exc)
