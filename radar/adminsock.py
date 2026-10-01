"""Канал управления в работающий процесс бота (с 5.9.3).

**Поломка, ради которой он нужен.** Командная строка запускается через
`docker exec` — это отдельный процесс рядом с ботом, а не он сам. До 5.9.3
`radarctl.sh features on digest` менял флаг в базе и в памяти этого короткого
процесса, а бот читает флаги из базы один раз при старте: возможность
не включалась до перезапуска. Хуже того, источники и пользователи лежат
в памяти бота целиком (`storage`), и бот при очередном сохранении затирал
правку, сделанную из консоли.

**Как устроено.** Бот слушает Unix-сокет `data/admin.sock` (права 600,
владелец — тот, кто запустил бота). Командная строка отправляет ему свои
аргументы, бот разбирает их тем же `radar.cli` и выполняет у себя — в той
же памяти, с той же базой, — а вывод и код возврата отдаёт обратно. Второй
реализации нет: сокет не знает ни одной команды, он лишь переносит строку
запуска. Если бот не запущен, сокета нет, и командная строка работает
с базой напрямую, как раньше.

Почему сокет, а не порт. Терминала сервера в веб-панели нет и не будет:
канал не должен стать его обходом. Файл с правами 600 внутри каталога
данных недоступен ни из сети, ни другому пользователю хоста.

Протокол: одна строка JSON в обе стороны.
    →  {"argv": ["features", "on", "digest"]}
    ←  {"code": 0, "out": "…", "err": "…"}
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import socket
from contextlib import redirect_stderr, redirect_stdout

log = logging.getLogger("radar.adminsock")

# Запрос — это строка аргументов, больше нескольких килобайт не бывает.
MAX_REQUEST = 64 * 1024

# Команды идут по одной: вывод перехватывается через sys.stdout, а он один
# на процесс, и две одновременные команды перемешали бы ответы.
_lock: asyncio.Lock | None = None


def path() -> str:
    """Где лежит сокет: рядом с базой, в каталоге данных."""
    explicit = (os.getenv("ADMIN_SOCKET") or "").strip()
    if explicit:
        return explicit
    from . import config

    folder = os.path.dirname(os.path.abspath(config.DB_FILE)) or "data"
    return os.path.join(folder, "admin.sock")


def supported() -> bool:
    return hasattr(socket, "AF_UNIX") and hasattr(asyncio, "start_unix_server")


# --------------------------------------------------------------------------
#  Сторона бота
# --------------------------------------------------------------------------

def _worker(loop: asyncio.AbstractEventLoop, argv: list[str]) -> tuple[int, str, str]:
    """Выполняет команду в отдельном потоке: часть команд блокирует
    (копия, обслуживание базы), а бот не должен вставать из-за них."""
    from . import cli

    out, err = io.StringIO(), io.StringIO()
    cli.attach(loop)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                # argparse выходит сам при неверных аргументах.
                code = exc.code if isinstance(exc.code, int) else cli.FAILED
    finally:
        cli.attach(None)
    return int(code), out.getvalue(), err.getvalue()


async def execute(argv: list[str]) -> tuple[int, str, str]:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    loop = asyncio.get_running_loop()
    async with _lock:
        return await asyncio.to_thread(_worker, loop, argv)


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        raw = await reader.readline()
        if not raw or len(raw) > MAX_REQUEST:
            return
        request = json.loads(raw.decode("utf-8"))
        argv = request.get("argv")
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            reply = {"code": 1, "out": "", "err": "bad request\n"}
        else:
            code, out, err = await execute(argv)
            reply = {"code": code, "out": out, "err": err}
        writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
    except Exception:  # noqa: BLE001
        log.exception("Запрос к каналу управления не выполнен")
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


def _clear_stale(target: str) -> bool:
    """Убирает сокет, оставшийся от упавшего процесса. Живой не трогает."""
    if not os.path.exists(target):
        return True
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(1)
    try:
        probe.connect(target)
    except OSError:
        try:
            os.unlink(target)
            return True
        except OSError:
            return False
    finally:
        probe.close()
    return False   # слушает другой экземпляр


async def serve() -> None:
    """Запускается задачей рядом с ботом и живёт до его остановки."""
    if not supported():
        log.info("Канал управления недоступен на этой системе")
        return
    target = path()
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    if not _clear_stale(target):
        log.warning("Канал управления занят другим процессом: %s", target)
        return
    # Права назначаются при создании файла, а не после: между bind и chmod
    # сокет был бы открыт всем, кто успеет подключиться.
    old_mask = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(_handle, path=target)
    finally:
        os.umask(old_mask)
    log.info("Канал управления: %s", target)
    try:
        async with server:
            await server.serve_forever()
    finally:
        try:
            os.unlink(target)
        except OSError:
            pass


# --------------------------------------------------------------------------
#  Сторона командной строки
# --------------------------------------------------------------------------

def call(argv: list[str]) -> tuple[int, str, str] | None:
    """Отправляет команду работающему боту. None — бот недоступен."""
    if not supported():
        return None
    target = path()
    if not os.path.exists(target):
        return None
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(3)
        client.connect(target)
    except OSError:
        client.close()
        return None
    try:
        # Подключились — дальше ждём сколько нужно: проверка источников
        # занимает минуты.
        client.settimeout(None)
        client.sendall((json.dumps({"argv": argv}, ensure_ascii=False) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
        reply = json.loads(data.decode("utf-8"))
        return int(reply["code"]), str(reply.get("out", "")), str(reply.get("err", ""))
    except (OSError, ValueError, KeyError):
        # Команда уже отправлена и могла выполниться: повторять её
        # напрямую нельзя, иначе «add» или «prune» сработают дважды.
        return 1, "", "Связь с ботом прервалась; результат неизвестен — проверьте командой list.\n"
    finally:
        client.close()
