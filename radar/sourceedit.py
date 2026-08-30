#!/usr/bin/env python3
"""Правка списка источников: добавление, удаление, проверка формата.

Вынесено из обработчиков бота в 4.8.4.5, когда те же действия понадобились
веб-панели. Дублировать разбор было нельзя: правила «что считается каналом»
разъехались бы между ботом и панелью, и человек получил бы источник,
который бот принимает, а панель показывает как ошибку. Здесь одно место,
куда смотрят оба.

Опознаётся три вида источников — Telegram-каналы, RSS-ленты и сообщества
ВКонтакте. Очередь модерации трогается отдельно: попадание в неё означает
предложение от пользователя, а не решение администрации.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re

from . import storage

log = logging.getLogger("radar.sourceedit")

# Ограничения Telegram: латиница, цифры и подчёркивание, от пяти знаков.
CHANNEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")

# Сообщество ВКонтакте: короткое имя либо club/public с числом.
VK_RE = re.compile(r"^[A-Za-z0-9_.]{2,64}$")

# Разделители в присланном списке: запятая, точка с запятой, перевод строки.
_SPLIT = re.compile(r"[,\n;]+")

TELEGRAM = "tg"
RSS = "rss"
VK = "vk"

KINDS: tuple[str, ...] = (TELEGRAM, RSS, VK)

TITLES: dict[str, str] = {
    TELEGRAM: "Telegram-каналы",
    RSS: "RSS-ленты",
    VK: "Сообщества VK",
}


def _bucket(kind: str) -> list[str] | None:
    if kind == TELEGRAM:
        return storage.channels()
    if kind == RSS:
        return storage.rss_feeds()
    if kind == VK:
        return storage.vk_groups()
    return None


def normalize_channel(raw: str) -> str:
    """Юзернейм канала из чего угодно: ссылки, @имени, голого имени."""
    value = raw.strip()
    value = re.sub(r"^(https?://)?(t\.me/|telegram\.me/)?@?", "", value, flags=re.I)
    return value.strip("/ ").split("/")[0].split("?")[0]


def normalize_vk(raw: str) -> str:
    """Короткое имя сообщества из ссылки или голого имени."""
    value = raw.strip()
    value = re.sub(r"^(https?://)?(m\.)?vk\.com/", "", value, flags=re.I)
    return value.strip("/ ").split("/")[0].split("?")[0]


def normalize_feed(raw: str) -> str:
    return raw.strip()


def valid(kind: str, value: str) -> bool:
    """Годится ли значение как источник этого вида."""
    if kind == TELEGRAM:
        return bool(CHANNEL_RE.match(value))
    if kind == RSS:
        # Схему проверяем строго: без неё адрес не откроется, а «ошибка
        # раз в три минуты в журнале» — худший способ об этом узнать.
        return value.startswith(("http://", "https://")) and len(value) > 11
    if kind == VK:
        return bool(VK_RE.match(value))
    return False


def normalize(kind: str, raw: str) -> str:
    if kind == TELEGRAM:
        return normalize_channel(raw)
    if kind == VK:
        return normalize_vk(raw)
    return normalize_feed(raw)


def add(kind: str, text: str) -> tuple[list[str], list[str]]:
    """Добавляет источники из присланного текста.

    Возвращает (добавленные, пропущенные). Пропущенные — это и мусор,
    и уже имеющиеся: человеку важно увидеть, что его строка не потерялась,
    а не молча получить «добавлено 0».
    """
    bucket = _bucket(kind)
    if bucket is None:
        return [], []

    added: list[str] = []
    skipped: list[str] = []
    for raw in _SPLIT.split(text or ""):
        if not raw.strip():
            continue
        value = normalize(kind, raw)
        if valid(kind, value) and value not in bucket:
            bucket.append(value)
            added.append(value)
        else:
            skipped.append(raw.strip())
    if added:
        log.info("Добавлено источников (%s): %d", kind, len(added))
    return added, skipped


def remove(kind: str, value: str) -> bool:
    """Убирает один источник. False — такого не было."""
    bucket = _bucket(kind)
    if bucket is None or value not in bucket:
        return False
    bucket.remove(value)
    log.info("Удалён источник (%s): %s", kind, value)
    return True


def listing(kind: str) -> list[str]:
    return list(_bucket(kind) or [])


def counts() -> dict[str, int]:
    return {kind: len(_bucket(kind) or []) for kind in KINDS}
