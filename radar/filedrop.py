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

Никакой таблицы: всё, что нужно знать о файле, лежит в его имени —
`токен_имя.расширение`. Срок жизни считается по времени изменения.
Отдельная таблица означала бы расхождение между ней и диском ровно тогда,
когда оно опаснее всего: после падения посреди работы.
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
import secrets as secrets_module
import shutil
import time
from dataclasses import dataclass

from . import shortener

log = logging.getLogger("radar.filedrop")

DIRECTORY = "data/drop"

# Сутки. Больше держать незачем: человек забирает файл сразу или не
# забирает вовсе, а место на диске нужно оповещениям.
TTL_HOURS = 24

# Бюджет раздачи. При превышении убираются самые старые: диск, забитый
# чужими сериалами, останавливает систему целиком.
BUDGET_MB = 5000

# Токен в имени файла: 32 знака шестнадцатеричных — подобрать нельзя.
TOKEN_LENGTH = 16          # байт, то есть 32 знака в шестнадцатеричном виде
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

# Что оставляем в имени файла. Кириллицу сохраняем: человек скачивает
# файл и должен узнать его по имени.
_UNSAFE = re.compile(r"[^\w\-. ]+", re.U)


@dataclass(frozen=True)
class Drop:
    token: str
    path: str
    name: str
    size: int
    created: float

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


def listing() -> list[Drop]:
    """Всё, что сейчас лежит в раздаче, новое сверху."""
    items: list[Drop] = []
    try:
        names = os.listdir(directory())
    except OSError:
        return items

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
        items.append(Drop(token=token, path=path, name=name,
                          size=stat.st_size, created=stat.st_mtime))
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


def store(source: str, name: str = "") -> Drop | None:
    """Переносит готовый файл в раздачу. None — не вышло.

    Именно переносит, а не копирует: копия удвоила бы занятое место ровно
    в тот момент, когда файла и так слишком много для отправки.
    """
    if not enabled() or not source or not os.path.isfile(source):
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

    log.info("В раздачу помещён файл %s (%.1f МБ)", base, size / 1024 / 1024)
    purge()
    return Drop(token=token, path=target, name=base,
                size=size, created=time.time())


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
