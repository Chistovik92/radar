"""Облачное хранилище музыки по WebDAV (с 4.9.9).

Продолжение внешнего носителя из 4.9.5.4: там каталог музыки выносился
на флешку или диск, здесь — в облако. Ёмкость перестаёт упираться
в карту памяти одноплатника, а платная ёмкость из таблицы монетизации
становится возможной: продавать место, которого физически нет
на устройстве, нельзя.

**Почему WebDAV, а не FUSE.** Разбор соседнего проекта
[opendisk](https://github.com/Chistovik92/opendisk) показал, что брать
надо не его самого — он GUI на Kotlin без headless-режима и без сборок
под aarch64, — а то, поверх чего он сделан: rclone. У rclone два способа
отдать облако боту:

* `rclone mount` — облако видно каталогом, и `MUSIC_DIR` заработал бы
  без единой правки. Но это FUSE внутри контейнера: `--device /dev/fuse`
  и `--cap-add SYS_ADMIN`, то есть заметно более широкие права
  у процесса, который ходит в интернет за новостями;
* `rclone serve webdav` рядом — прав не требует вовсе, ценой своего
  клиента. Он перед вами, и он умещается в один файл.

Второй путь выбран сознательно: цена ошибки в правах контейнера выше,
чем стоимость сотни строк HTTP.

**Что здесь намеренно не делается.** Ни кэша, ни решений «качать или
нет» — это дело `radar/music.py`. Здесь только четыре действия над
удалённым файлом и вопрос о свободном месте. Модуль не знает ни про
пользователей, ни про треки, и проверяется без сети.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

log = logging.getLogger("radar.cloudstore")

# Таймауты. Отдача трека идёт через чужую сеть, и она может быть
# медленной, но не бесконечной: раздел музыки не должен висеть.
CONNECT_TIMEOUT = 15
TRANSFER_TIMEOUT = 180

# Имя файла в хранилище: идентификатор трека плюс расширение. Всё,
# что не похоже на это, до сети не доходит — путь в WebDAV строится
# склейкой, и постороннему символу там взяться неоткуда.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}(?:\.[A-Za-z0-9]{1,8})?$")

# Свойства, которыми WebDAV отвечает на вопрос о месте. Их поддерживают
# не все серверы: rclone отдаёт, если их отдаёт нижележащее облако.
_USED_RE = re.compile(r"<[^>]*quota-used-bytes[^>]*>(\d+)<", re.I)
_AVAIL_RE = re.compile(r"<[^>]*quota-available-bytes[^>]*>(-?\d+)<", re.I)

_QUOTA_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop>'
    "<d:quota-available-bytes/><d:quota-used-bytes/>"
    "</d:prop></d:propfind>"
)


def base_url() -> str:
    """Адрес хранилища без завершающего слэша. Пусто — не настроено."""
    from . import secrets

    return str(secrets.get("MUSIC_CLOUD_URL") or "").strip().rstrip("/")


def credentials() -> tuple[str, str]:
    from . import secrets

    return (
        str(secrets.get("MUSIC_CLOUD_USER") or ""),
        str(secrets.get("MUSIC_CLOUD_PASSWORD") or ""),
    )


def configured() -> bool:
    """Задан ли адрес. Логин и пароль необязательны: rclone умеет
    отдавать WebDAV без проверки, когда слушает только localhost."""
    return bool(base_url())


def enabled() -> bool:
    """Включено ли облако: флаг плюс настройка."""
    from . import features

    return features.enabled("music_cloud") and configured()


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.fullmatch(name or ""))


def url_for(name: str) -> str:
    """Полный адрес файла. Пусто — имя не годится или адрес не задан."""
    if not configured() or not valid_name(name):
        return ""
    return f"{base_url()}/{quote(name)}"


def _auth() -> Any:
    """Проверка подлинности для aiohttp или None, если её не задали."""
    import aiohttp

    user, password = credentials()
    if not user:
        return None
    return aiohttp.BasicAuth(user, password)


def _timeout(total: int) -> Any:
    import aiohttp

    return aiohttp.ClientTimeout(total=total, connect=CONNECT_TIMEOUT)


async def _request(method: str, name: str, *, data: bytes | None = None,
                   total: int = TRANSFER_TIMEOUT,
                   url: str = "") -> tuple[int, bytes, str]:
    """Один запрос к хранилищу. Возвращает (код, тело, причина отказа).

    Код 0 означает, что до сервера не дошли вовсе: сеть, адрес, таймаут.
    Причина при этом заполнена и написана для человека, а не для журнала.
    """
    import aiohttp

    target = url or url_for(name)
    if not target:
        return 0, b"", "Облачное хранилище не настроено."

    try:
        async with aiohttp.ClientSession(timeout=_timeout(total)) as session:
            async with session.request(
                method, target, data=data, auth=_auth(),
                headers={"User-Agent": "radar-cloudstore"},
            ) as response:
                body = await response.read()
                return response.status, body, ""
    except aiohttp.ClientError as exc:
        log.warning("Хранилище недоступно (%s %s): %s", method, name, exc)
        return 0, b"", "Хранилище не отвечает."
    except Exception as exc:  # noqa: BLE001
        # В том числе TimeoutError: он приходит из asyncio, а не из aiohttp.
        log.warning("Сбой обращения к хранилищу (%s %s): %s", method, name, exc)
        return 0, b"", "Обращение к хранилищу не удалось."


def _ok(status: int) -> bool:
    return 200 <= status < 300


async def put(name: str, payload: bytes) -> tuple[bool, str]:
    """Кладёт файл в хранилище. Возвращает (получилось, причина отказа)."""
    if not valid_name(name):
        return False, "Недопустимое имя файла."

    status, _body, reason = await _request("PUT", name, data=payload)
    if reason:
        return False, reason
    if not _ok(status):
        log.warning("Загрузка %s отклонена: HTTP %s", name, status)
        return False, f"Хранилище отказало (HTTP {status})."
    return True, ""


async def fetch(name: str) -> tuple[bool, bytes | str]:
    """Забирает файл. При неудаче вторым значением идёт причина."""
    if not valid_name(name):
        return False, "Недопустимое имя файла."

    status, body, reason = await _request("GET", name)
    if reason:
        return False, reason
    if status == 404:
        return False, "Файла нет в хранилище."
    if not _ok(status):
        return False, f"Хранилище отказало (HTTP {status})."
    return True, body


async def delete(name: str) -> bool:
    """Убирает файл. 404 считается успехом: его и так нет."""
    if not valid_name(name):
        return False

    status, _body, reason = await _request("DELETE", name, total=CONNECT_TIMEOUT * 2)
    if reason:
        return False
    return _ok(status) or status == 404


async def exists(name: str) -> bool:
    if not valid_name(name):
        return False
    status, _body, reason = await _request("HEAD", name, total=CONNECT_TIMEOUT * 2)
    return not reason and _ok(status)


def parse_quota(body: bytes) -> tuple[int, int]:
    """Разбирает ответ PROPFIND. Возвращает (занято, доступно) в байтах.

    -1 в любом из значений означает «сервер не сказал»: часть облаков
    не сообщает объём вовсе, и делать вид, что место известно, нельзя.
    """
    text = body.decode("utf-8", "replace")
    used_match = _USED_RE.search(text)
    avail_match = _AVAIL_RE.search(text)

    used = int(used_match.group(1)) if used_match else -1
    available = int(avail_match.group(1)) if avail_match else -1
    # По стандарту отрицательные значения — это «не ограничено»
    # и «неизвестно». Для отчёта и то и другое означает одно: не показывать.
    if available < 0:
        available = -1
    return used, available


async def space() -> tuple[int, int]:
    """Сколько занято и сколько доступно. (-1, -1) — узнать не удалось."""
    if not configured():
        return -1, -1

    status, body, reason = await _request(
        "PROPFIND", "", data=_QUOTA_BODY.encode("utf-8"),
        total=CONNECT_TIMEOUT * 2, url=base_url() + "/",
    )
    if reason or not _ok(status):
        return -1, -1
    return parse_quota(body)


async def check() -> tuple[bool, str]:
    """Проверка для диагностики: доступно ли хранилище и что в нём с местом."""
    if not configured():
        return False, "MUSIC_CLOUD_URL не задан"

    status, body, reason = await _request(
        "PROPFIND", "", data=_QUOTA_BODY.encode("utf-8"),
        total=CONNECT_TIMEOUT * 2, url=base_url() + "/",
    )
    if reason:
        return False, reason
    if status in (401, 403):
        return False, "хранилище не приняло логин или пароль"
    if not _ok(status):
        return False, f"хранилище ответило HTTP {status}"

    used, available = parse_quota(body)
    if available < 0:
        return True, "доступно, объём не сообщается"

    from .music import format_size

    return True, f"доступно, свободно {format_size(available)}"
