"""Привязка аккаунтов других мессенджеров к Telegram (с 5.6).

Открытый вопрос из разделов 6.0 (MAX) и 7.0 (ВКонтакте) дорожной карты:
без связи человек в MAX или ВК — не тот же человек, что в Telegram, а значит,
без локаций. Решение — одноразовый код:

1. в Telegram человек нажимает «Привязать» (`/link`) и получает шестизначный
   код, живущий 10 минут;
2. отправляет этот код боту в ВК или MAX;
3. связь записывается, и тревоги по его адресам начинают дублироваться туда
   (`radar/mirror.py`).

Почему код идёт из Telegram, а не наоборот. Адреса, роли и подписка живут
в Telegram-аккаунте; подтверждать связь должен тот, у кого они есть. Код,
выданный в ВК и введённый в Telegram, позволил бы любому, кто знает чужой
идентификатор ВК, направить туда чужие тревоги.

Перебор закрыт: не больше пяти неверных кодов с одного аккаунта за десять
минут. Кодов миллион, так что угадать за пять попыток — один шанс на 200 000.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import re
import secrets as pysecrets
import time
from typing import Any

log = logging.getLogger("radar.links")

META_KEY = "account_links"
CODE_TTL = 600
MAX_FAILURES = 5
PLATFORMS = ("vk", "max")
TITLES = {"vk": "ВКонтакте", "max": "MAX"}

_CODE_RE = re.compile(r"^\s*(?:/?link\s+)?(\d{6})\s*$", re.IGNORECASE)

# Коды живут в памяти: перезапуск бота обнуляет их, и это правильно —
# код на десять минут не стоит того, чтобы переживать перезапуск.
_codes: dict[str, tuple[str, float]] = {}          # код → (telegram uid, до)
_failures: dict[str, list[float]] = {}             # платформа:id → попытки
_lock = asyncio.Lock()


def extract_code(text: str) -> str:
    """Код из сообщения: «123456» или «/link 123456». Пусто — не код."""
    match = _CODE_RE.match(text or "")
    return match.group(1) if match else ""


def _clean(now: float) -> None:
    for code in [code for code, (_, until) in _codes.items() if until < now]:
        _codes.pop(code, None)
    for key in list(_failures):
        _failures[key] = [moment for moment in _failures[key] if now - moment < CODE_TTL]
        if not _failures[key]:
            _failures.pop(key)


def new_code(uid: str | int, now: float | None = None) -> str:
    """Выдаёт код привязки для Telegram-пользователя. Прежний код гасится."""
    moment = now if now is not None else time.time()
    _clean(moment)
    for code in [code for code, (owner, _) in _codes.items() if owner == str(uid)]:
        _codes.pop(code, None)
    while True:
        code = f"{pysecrets.randbelow(10 ** 6):06d}"
        if code not in _codes:
            break
    _codes[code] = (str(uid), moment + CODE_TTL)
    return code


async def _load() -> dict[str, dict[str, str]]:
    from . import storage

    value = await storage.meta_get(META_KEY, {})
    return dict(value) if isinstance(value, dict) else {}


async def _save(links: dict[str, dict[str, str]]) -> None:
    from . import storage

    await storage.meta_set(META_KEY, links)


async def redeem(platform: str, external_id: str | int, code: str,
                 now: float | None = None) -> tuple[str, str]:
    """Погасить код. Возвращает (telegram uid, причина отказа)."""
    moment = now if now is not None else time.time()
    if platform not in PLATFORMS:
        return "", "Эта площадка не привязывается."
    who = f"{platform}:{external_id}"
    async with _lock:
        _clean(moment)
        if len(_failures.get(who, [])) >= MAX_FAILURES:
            return "", "Слишком много неверных кодов. Подождите десять минут."
        entry = _codes.get(code)
        if entry is None:
            _failures.setdefault(who, []).append(moment)
            return "", "Код не подошёл или устарел. Получите новый в Telegram-боте."
        uid, _ = entry
        _codes.pop(code, None)
        links = await _load()
        # Один аккаунт площадки — один владелец: новая привязка снимает старую.
        for owner, mapping in links.items():
            if mapping.get(platform) == str(external_id) and owner != uid:
                mapping.pop(platform, None)
        links.setdefault(uid, {})[platform] = str(external_id)
        await _save({owner: mapping for owner, mapping in links.items() if mapping})
    log.info("Привязан %s к Telegram-аккаунту", platform)
    return uid, ""


async def links_of(uid: str | int) -> dict[str, str]:
    return dict((await _load()).get(str(uid)) or {})


async def owner_of(platform: str, external_id: str | int) -> str:
    for owner, mapping in (await _load()).items():
        if mapping.get(platform) == str(external_id):
            return owner
    return ""


async def unlink(uid: str | int, platform: str | None = None) -> list[str]:
    """Снять привязку (одну или все). Возвращает снятые площадки."""
    async with _lock:
        links = await _load()
        mapping = links.get(str(uid)) or {}
        removed = [key for key in list(mapping) if platform in (None, key)]
        for key in removed:
            mapping.pop(key, None)
        if mapping:
            links[str(uid)] = mapping
        else:
            links.pop(str(uid), None)
        await _save(links)
    return removed


async def unlink_external(platform: str, external_id: str | int) -> bool:
    """Отвязка со стороны площадки: «/unlink» в ВК или MAX."""
    owner = await owner_of(platform, external_id)
    if not owner:
        return False
    await unlink(owner, platform)
    return True


def reset() -> None:
    """Для тестов: забыть коды и попытки."""
    _codes.clear()
    _failures.clear()


def pending_codes() -> dict[str, Any]:
    return dict(_codes)


LINKED = ("✅ Аккаунт привязан к Telegram. Тревоги по вашим адресам теперь "
          "будут приходить и сюда. Адреса и настройки меняются в Telegram-боте. "
          "Отвязать — /unlink.")
UNLINKED = "Привязка снята: тревоги сюда больше не придут."
NOT_LINKED = "Этот аккаунт не привязан к Telegram."


async def handle_text(platform: str, external_id: str | int, text: str) -> str:
    """Ответ на код привязки или /unlink. Пусто — сообщение не об этом."""
    stripped = (text or "").strip()
    if stripped.lower() in ("/unlink", "unlink", "отвязать"):
        return UNLINKED if await unlink_external(platform, external_id) else NOT_LINKED
    code = extract_code(stripped)
    if not code:
        return ""
    uid, reason = await redeem(platform, external_id, code)
    return LINKED if uid else f"❌ {reason}"
