"""Управляющее API rclone: подключение облаков без терминала (с 4.9.9.1).

В 4.9.9 облако подключалось руками на сервере: `rclone config`, потом
правка `.env`. Здесь то же самое делается из веб-панели — но не через
запуск команд, а через **rc API** самого rclone: отдельный HTTP-интерфейс,
который он поднимает по `--rc`. Тот же путь, которым пользуется соседний
проект opendisk из своего GUI.

Разница принципиальная и её стоит назвать прямо: панель не выполняет
команд на сервере и не получит такой возможности — терминала в ней нет
и не будет. Здесь вызывается чужой сервис по сети, с заранее известным
списком действий, и всё, что он умеет, — заводить и убирать записи
о хранилищах в своём конфиге.

**Чего это не может.** Провайдеры с входом через браузер (Яндекс.Диск,
Google Drive, Dropbox) требуют OAuth: человек нажимает «разрешить»
на странице провайдера, и токен без этого не появится. Панель такого
сделать не может — нужен браузер на стороне того, кто входит. Для них
остаётся `rclone authorize` на любой машине с браузером и вставка
готового токена сюда, полем. Хранилища, которым хватает адреса и пароля
(WebDAV, S3, FTP, SFTP), заводятся целиком отсюда.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("radar.rclonerc")

TIMEOUT = 30

# Имя хранилища попадает в конфиг rclone и в строку `имя:путь`.
# Двоеточие, слэш и пробел в нём ломают эту строку, поэтому набор узкий.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@dataclass(frozen=True)
class Field:
    """Поле формы для одного вида хранилища."""

    key: str
    title: str
    hint: str = ""
    secret: bool = False
    required: bool = True


@dataclass(frozen=True)
class Kind:
    """Вид хранилища: что показать в форме и что послать rclone."""

    key: str
    title: str
    note: str
    fields: tuple[Field, ...] = field(default_factory=tuple)


# Виды, которые заводятся без браузера. Список намеренно короткий:
# у rclone их семь десятков, но у большинства своя обвязка, и «показать
# все» означало бы форму, в которой нельзя не ошибиться.
KINDS: tuple[Kind, ...] = (
    Kind(
        "webdav", "WebDAV",
        "Подходит для Nextcloud, ownCloud и любого сервера WebDAV. "
        "Для Яндекс.Диска — https://webdav.yandex.ru и пароль приложения "
        "вместо основного.",
        (
            Field("url", "Адрес", "https://webdav.yandex.ru"),
            Field("user", "Логин"),
            Field("pass", "Пароль", "Для Яндекса — пароль приложения",
                  secret=True),
            Field("vendor", "Вид сервера",
                  "other, nextcloud, owncloud — если не знаете, оставьте other",
                  required=False),
        ),
    ),
    Kind(
        "s3", "S3",
        "Любое объектное хранилище с S3-совместимым API: Selectel, "
        "Timeweb, MinIO, Backblaze. Ключи выдаются в личном кабинете "
        "провайдера.",
        (
            Field("provider", "Провайдер",
                  "Other подходит почти всем; для MinIO — Minio",
                  required=False),
            Field("access_key_id", "Ключ доступа"),
            Field("secret_access_key", "Секретный ключ", secret=True),
            Field("endpoint", "Адрес", "s3.example.com", required=False),
            Field("region", "Регион", required=False),
        ),
    ),
    Kind(
        "sftp", "SFTP",
        "Обычный доступ по SSH к другому серверу. Пароль хранится "
        "в конфиге rclone, поэтому лучше отдельный ограниченный "
        "пользователь, а не тот, под которым живёт всё.",
        (
            Field("host", "Хост"),
            Field("user", "Логин"),
            Field("pass", "Пароль", secret=True),
            Field("port", "Порт", "22", required=False),
        ),
    ),
    Kind(
        "ftp", "FTP",
        "Старый добрый FTP. Без TLS пароль идёт открытым текстом — "
        "годится для хранилища в своей сети, но не через интернет.",
        (
            Field("host", "Хост"),
            Field("user", "Логин"),
            Field("pass", "Пароль", secret=True),
            Field("port", "Порт", "21", required=False),
        ),
    ),
)

BY_KIND: dict[str, Kind] = {item.key: item for item in KINDS}


def base_url() -> str:
    """Адрес rc API. Пусто — управление облаками из панели недоступно."""
    from . import secrets

    return str(secrets.get("RCLONE_RC_URL") or "").strip().rstrip("/")


def configured() -> bool:
    return bool(base_url())


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.fullmatch(name or ""))


def _auth() -> Any:
    import aiohttp

    from . import secrets

    user = str(secrets.get("RCLONE_RC_USER") or "")
    if not user:
        return None
    return aiohttp.BasicAuth(user, str(secrets.get("RCLONE_RC_PASS") or ""))


async def call(method: str, payload: dict[str, Any] | None = None
               ) -> tuple[bool, Any]:
    """Вызов метода rc API. Возвращает (получилось, ответ или причина).

    Причина пишется для человека: страницу с ней увидит администратор,
    а не разработчик, и «ClientConnectorError» ему ничего не объясняет.
    """
    import aiohttp

    if not configured():
        return False, "Управление облаками не настроено: пуст RCLONE_RC_URL."

    url = f"{base_url()}/{method.lstrip('/')}"
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload or {},
                                    auth=_auth()) as response:
                body = await response.json(content_type=None)
                if response.status == 401:
                    return False, "rclone не принял логин или пароль."
                if response.status >= 400:
                    detail = ""
                    if isinstance(body, dict):
                        detail = str(body.get("error") or "")
                    return False, detail or f"rclone ответил HTTP {response.status}"
                return True, body
    except aiohttp.ClientError as exc:
        log.warning("rclone rc недоступен (%s): %s", method, exc)
        return False, "rclone не отвечает — проверьте, что он запущен с --rc."
    except Exception as exc:  # noqa: BLE001
        log.warning("Сбой вызова rclone rc (%s): %s", method, exc)
        return False, "Обращение к rclone не удалось."


async def remotes() -> tuple[bool, Any]:
    """Список заведённых хранилищ."""
    ok, body = await call("config/listremotes")
    if not ok:
        return False, body
    names = body.get("remotes") if isinstance(body, dict) else None
    return True, sorted(names or [])


async def describe(name: str) -> dict[str, Any]:
    """Тип и настройки хранилища. Пустой словарь — не удалось."""
    if not valid_name(name):
        return {}
    ok, body = await call("config/get", {"name": name})
    return body if ok and isinstance(body, dict) else {}


def clean_params(kind: str, values: dict[str, str]) -> tuple[dict[str, str], str]:
    """Отбирает поля вида и проверяет обязательные.

    Возвращает (параметры, причина отказа). Отбор, а не доверие форме:
    в конфиг rclone уходит только то, что мы сами перечислили.
    """
    item = BY_KIND.get(kind)
    if item is None:
        return {}, "Неизвестный вид хранилища."

    params: dict[str, str] = {}
    for spec in item.fields:
        value = str(values.get(spec.key) or "").strip()
        if not value:
            if spec.required:
                return {}, f"Не заполнено поле «{spec.title}»."
            continue
        params[spec.key] = value
    return params, ""


async def create(name: str, kind: str, values: dict[str, str]
                 ) -> tuple[bool, str]:
    """Заводит хранилище. Возвращает (получилось, причина отказа)."""
    if not valid_name(name):
        return False, ("Имя может состоять из латиницы, цифр, дефиса "
                       "и подчёркивания, до 32 знаков.")

    params, reason = clean_params(kind, values)
    if reason:
        return False, reason

    ok, body = await call("config/create", {
        "name": name,
        "type": kind,
        "parameters": params,
        # Без этого rclone на некоторых видах пытается спросить человека
        # и виснет в ожидании ответа, которого из панели не придёт.
        "opt": {"nonInteractive": True, "obscure": True},
    })
    if not ok:
        return False, str(body)
    log.info("Заведено хранилище rclone: %s (%s)", name, kind)
    return True, ""


async def forget(name: str) -> tuple[bool, str]:
    """Убирает хранилище из конфига rclone.

    Данные в самом облаке не трогаются: это забытая запись о доступе,
    а не удаление файлов. Сказать об этом человеку — дело страницы.
    """
    if not valid_name(name):
        return False, "Недопустимое имя."
    ok, body = await call("config/delete", {"name": name})
    if not ok:
        return False, str(body)
    log.info("Убрано хранилище rclone: %s", name)
    return True, ""


async def about(name: str) -> tuple[bool, str]:
    """Сколько места в хранилище. Вторым значением — готовая строка."""
    if not valid_name(name):
        return False, "Недопустимое имя."

    ok, body = await call("operations/about", {"fs": f"{name}:"})
    if not ok:
        return False, str(body)
    if not isinstance(body, dict):
        return False, "Непонятный ответ rclone."

    from .music import format_size

    total = body.get("total")
    used = body.get("used")
    free = body.get("free")
    if free is None and total is None:
        return True, "объём не сообщается"
    parts = []
    if used is not None and total is not None:
        parts.append(f"занято {format_size(used)} из {format_size(total)}")
    elif used is not None:
        parts.append(f"занято {format_size(used)}")
    if free is not None:
        parts.append(f"свободно {format_size(free)}")
    return True, ", ".join(parts) or "объём не сообщается"


async def check() -> tuple[bool, str]:
    """Отвечает ли rclone. Для страницы и для диагностики."""
    if not configured():
        return False, "RCLONE_RC_URL не задан"
    ok, body = await call("rc/noop")
    if not ok:
        return False, str(body)
    return True, "управляющее API отвечает"
