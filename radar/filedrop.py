#!/usr/bin/env python3
"""Выдача крупных файлов по ссылке.

Зачем это есть
--------------

Telegram принимает от ботов не больше 50 МБ. Серия с Rutube весит 1190 МБ,
и до 4.8.5 разговор на этом заканчивался: «выберите качество ниже — или
поднимите собственный Bot API Server». Оба совета верные и оба неуместные:
качества ниже может не быть, а поднимать второй сервер ради одного файла
никто не станет.

Если у системы есть внешний адрес — тот же, на котором открыта панель
и работают короткие ссылки, — файл можно отдать по нему. Предел Telegram
это не обходит, а именно объезжает: файл не отправляется в мессенджер
вовсе, человек скачивает его сам.

Кому достаётся ссылка
---------------------

Только пользователю бота. Ссылку выдаёт бот в переписке, и получить её
может лишь тот, кто с ботом уже разговаривает. Это осознанное условие,
а не побочный эффект: раздача файлов посторонним превращает домен
в файлопомойку, и вместе с ним в списки блокировок уезжают ссылки
из оповещений.

Честная оговорка о безопасности: сама ссылка — секрет, и кто её получил,
тот скачает. Проверить у скачивающего учётную запись Telegram при обычном
запросе из браузера невозможно. Поэтому имя файла непредсказуемо, срок
жизни ограничен сутками, а место — бюджетом.

Устройство хранения
-------------------

Всё, без чего раздача не работает, лежит в имени файла —
`токен_имя.расширение`, а срок жизни считается по времени изменения.
Таблица здесь означала бы расхождение между ней и диском ровно тогда,
когда оно опаснее всего: после падения посреди работы.

Рядом лежит `index.json` — кому выдана ссылка и сколько раз по ней
скачали. Эти сведения нужны администрации в панели, но не нужны самой
раздаче, поэтому они **необязательные**: потеря файла с пометками
оставляет панель без подписей и ничего больше не ломает. Отсюда правило
для кода ниже — любая ошибка чтения пометок продолжает работу с пустыми
сведениями, а не останавливает её.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import os
import re
import secrets as secrets_module
import shutil
import time
from dataclasses import dataclass

from . import config, shortener

log = logging.getLogger("radar.filedrop")

DIRECTORY = "data/drop"

# Сутки. Больше держать незачем: человек забирает файл сразу или не
# забирает вовсе, а место на диске нужно оповещениям.
TTL_HOURS = config.FILEDROP_TTL_HOURS

# Бюджет раздачи целиком. При превышении убираются самые старые: диск,
# забитый чужими сериалами, останавливает систему целиком. Больше предела
# на один файл — иначе первый же файл занял бы всю раздачу.
BUDGET_MB = config.FILEDROP_BUDGET_MB

# Предел на ОДИН файл. Подписка его не снимает: она про доступ
# к возможности, а не про место на диске. Мегабайты двоичные — 5120 МБ
# это ровно 5 ГБ; на 5000 подпись «до 5 ГБ» превращалась в «до 4 ГБ».
MAX_FILE_MB = config.FILEDROP_MAX_MB

# Токен в имени файла: 32 знака шестнадцатеричных — подобрать нельзя.
TOKEN_LENGTH = 16          # байт, то есть 32 знака в шестнадцатеричном виде
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

# Что оставляем в имени файла. Кириллицу сохраняем: человек скачивает
# файл и должен узнать его по имени.
_UNSAFE = re.compile(r"[^\w\-. ]+", re.U)


# Пометки о выдаче: кому выдана ссылка и сколько раз по ней скачали.
# Хранятся отдельным файлом и намеренно считаются НЕОБЯЗАТЕЛЬНЫМИ: сами
# файлы остаются источником правды, а потеря пометок теряет только
# подписи в панели, но не раздачу. Поэтому любая ошибка чтения здесь —
# повод продолжить с пустыми сведениями, а не остановиться.
INDEX_NAME = "index.json"


@dataclass(frozen=True)
class Drop:
    token: str
    path: str
    name: str
    size: int
    created: float
    owner: str = ""
    hits: int = 0

    @property
    def size_mb(self) -> float:
        return self.size / 1024 / 1024

    @property
    def hours_left(self) -> float:
        return max(0.0, TTL_HOURS - (time.time() - self.created) / 3600)


def enabled() -> bool:
    """Есть ли внешний адрес, по которому файл вообще можно забрать.

    Тот же адрес, что у коротких ссылок: он и есть внешний адрес панели.
    Без него ссылка вела бы в никуда, и предлагать её нельзя.
    """
    return bool(shortener.base_url())


def directory() -> str:
    os.makedirs(DIRECTORY, exist_ok=True)
    return DIRECTORY


def safe_name(name: str) -> str:
    """Имя файла, безопасное для файловой системы и заголовка ответа."""
    cleaned = _UNSAFE.sub("_", (name or "").strip()).strip("._ ")
    return (cleaned or "file")[:80]


def valid_token(token: str) -> bool:
    return bool(_TOKEN_RE.match((token or "").strip().lower()))


def _parse(filename: str) -> tuple[str, str] | None:
    token, _, rest = filename.partition("_")
    if not valid_token(token) or not rest:
        return None
    return token, rest


def _index_path() -> str:
    return os.path.join(directory(), INDEX_NAME)


def _read_index() -> dict:
    try:
        with open(_index_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(data: dict) -> None:
    try:
        with open(_index_path(), "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
    except OSError as exc:
        log.debug("Пометки раздачи не сохранены: %s", exc)


def note_download(token: str) -> None:
    """Отмечает, что по ссылке скачали. Ошибка здесь ничего не ломает."""
    if not valid_token(token):
        return
    data = _read_index()
    entry = data.get(token)
    if not isinstance(entry, dict):
        entry = {}
    entry["hits"] = int(entry.get("hits") or 0) + 1
    entry["last"] = time.time()
    data[token] = entry
    _write_index(data)


def listing() -> list[Drop]:
    """Всё, что сейчас лежит в раздаче, новое сверху."""
    items: list[Drop] = []
    try:
        names = os.listdir(directory())
    except OSError:
        return items

    marks = _read_index()
    for filename in names:
        parsed = _parse(filename)
        if parsed is None:
            continue
        token, name = parsed
        path = os.path.join(DIRECTORY, filename)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if not os.path.isfile(path):
            continue
        entry = marks.get(token) if isinstance(marks.get(token), dict) else {}
        items.append(Drop(token=token, path=path, name=name,
                          size=stat.st_size, created=stat.st_mtime,
                          owner=str(entry.get("owner") or ""),
                          hits=int(entry.get("hits") or 0)))
    items.sort(key=lambda item: item.created, reverse=True)
    return items


def find(token: str) -> Drop | None:
    """Файл по токену. Просроченный не отдаём, даже если ещё на диске."""
    if not valid_token(token):
        return None
    token = token.strip().lower()
    for item in listing():
        if item.token == token:
            return item if item.hours_left > 0 else None
    return None


def url_for(drop: Drop) -> str:
    return f"{shortener.base_url()}/d/{drop.token}/{drop.name}"


def too_large(size_bytes: int) -> bool:
    """Не влезает ли файл в предел одной ссылки."""
    return size_bytes > MAX_FILE_MB * 1024 * 1024


def store(source: str, name: str = "", owner: str = "") -> Drop | None:
    """Переносит готовый файл в раздачу. None — не вышло.

    Именно переносит, а не копирует: копия удвоила бы занятое место ровно
    в тот момент, когда файла и так слишком много для отправки.

    `owner` — ключ пользователя, которому выдана ссылка. Он не проверяется
    при скачивании (браузер не несёт учётной записи Telegram) и нужен
    администрации: видеть в панели, чей это файл и забрали ли его.
    """
    if not enabled() or not source or not os.path.isfile(source):
        return None

    try:
        if too_large(os.path.getsize(source)):
            log.info("Файл больше предела ссылки (%d МБ) — не раздаём",
                     MAX_FILE_MB)
            return None
    except OSError:
        return None

    token = secrets_module.token_hex(TOKEN_LENGTH)
    extension = os.path.splitext(source)[1]
    base = safe_name(name or os.path.basename(source))
    if extension and not base.lower().endswith(extension.lower()):
        base = f"{base}{extension}"

    target = os.path.join(directory(), f"{token}_{base}")
    try:
        shutil.move(source, target)
    except OSError as exc:
        log.warning("Файл не помещён в раздачу: %s", exc)
        return None

    try:
        size = os.path.getsize(target)
    except OSError:
        size = 0

    if owner:
        data = _read_index()
        data[token] = {"owner": owner, "hits": 0, "issued": time.time()}
        _write_index(data)

    log.info("В раздачу помещён файл %s (%.1f МБ)", base, size / 1024 / 1024)
    purge()
    return Drop(token=token, path=target, name=base,
                size=size, created=time.time(), owner=owner)


def remove(token: str) -> bool:
    """Гасит ссылку досрочно: файл удаляется, пометка тоже.

    Нужно администрации: выдал не тому, файл оказался лишним, место
    понадобилось раньше срока. Ждать сутки в таких случаях незачем.
    """
    drop = None
    for item in listing():
        if item.token == token:
            drop = item
            break
    if drop is None:
        return False
    try:
        os.remove(drop.path)
    except OSError:
        return False
    data = _read_index()
    if data.pop(token, None) is not None:
        _write_index(data)
    log.info("Ссылка погашена досрочно: %s", drop.name)
    return True


def purge() -> int:
    """Убирает просроченное и лишнее сверх бюджета. Возвращает число файлов."""
    items = listing()
    doomed = [item for item in items if item.hours_left <= 0]

    # Бюджет считаем по тому, что переживёт срок: удалять свежее ради
    # просроченного было бы наоборот.
    alive = [item for item in items if item.hours_left > 0]
    total = sum(item.size for item in alive)
    budget = BUDGET_MB * 1024 * 1024
    for item in sorted(alive, key=lambda value: value.created):
        if total <= budget:
            break
        doomed.append(item)
        total -= item.size

    removed = 0
    for item in doomed:
        try:
            os.remove(item.path)
            removed += 1
        except OSError:
            continue

    if removed:
        # Пометки об исчезнувших файлах не нужны: индекс не должен расти
        # вечно, а восстановить его не из чего — файла уже нет.
        alive_tokens = {item.token for item in listing()}
        data = _read_index()
        trimmed = {key: value for key, value in data.items()
                   if key in alive_tokens}
        if len(trimmed) != len(data):
            _write_index(trimmed)
        log.info("Из раздачи убрано файлов: %d", removed)
    return removed


def summary() -> str:
    """Состояние раздачи для сообщения администратору."""
    items = [item for item in listing() if item.hours_left > 0]
    if not items:
        return "📦 <b>Раздача файлов</b>\n\nСейчас пусто."
    total_mb = sum(item.size for item in items) / 1024 / 1024
    lines = [
        "📦 <b>Раздача файлов</b>", "",
        f"Файлов: <b>{len(items)}</b> · занято <b>{total_mb:.0f} МБ</b> "
        f"из {BUDGET_MB} МБ", "",
    ]
    for item in items[:10]:
        lines.append(f"• {item.name} — {item.size_mb:.0f} МБ, "
                     f"осталось {item.hours_left:.0f} ч")
    return "\n".join(lines)
