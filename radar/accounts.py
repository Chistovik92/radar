"""Живые и мёртвые аккаунты в Telegram (с 5.9.4).

Три разные задачи, и важно не путать, на что способен Bot API:

* **Удалённые участники группы.** Bot API не умеет перечислять участников
  чата, поэтому чистка идёт по тем, кого бот видел сам (`ChatMember`:
  вступление, сообщение). Про каждого спрашивается `getChatMember`;
  удалённый аккаунт приходит как «Deleted Account». Тех, кто в чате давно
  и молчит, бот не знает — отчёт честно говорит, сколько из скольких
  участников проверено. Полный обход возможен только через MTProto
  (пользовательская сессия), и это сознательно не делается: такие сессии
  банят, а условия Telegram их не одобряют.
* **Мёртвые получатели оповещений.** Заблокировал бота или удалил аккаунт —
  `TelegramForbiddenError`. Отметка `dead` снимает повторные попытки: раньше
  тревога для такого человека уходила в API каждый цикл, и каждый раз —
  предупреждение в журнале. Снимается сама, когда человек пишет боту:
  разблокировать бота можно только заново нажав /start.
* **Новички по базе CAS** (Combot Anti-Spam). Это внешний сервис: ему
  отправляется числовой идентификатор человека. Поэтому — только по флагу
  `cas_check`, выключен по умолчанию, и об обмене сказано в README.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger("radar.accounts")

# Так Bot API называет удалённый аккаунт. Список, а не одна строка: бот
# видит имя в том виде, в каком его отдаёт сервер, и локализация иногда
# проскакивает.
DELETED_NAMES = {"deleted account", "удалённый аккаунт", "удаленный аккаунт"}

CAS_URL = "https://api.cas.chat/check"
CAS_TIMEOUT = 6

# Пауза между запросами getChatMember: у Bot API общий предел около 30
# запросов в секунду на бота, а чистка — не самое срочное, что он делает.
SCAN_PAUSE = 0.06
# Больше этого за один проход не проверяем: группа на десятки тысяч
# заблокировала бы бота для всего остального на несколько минут.
SCAN_LIMIT = 5000


def is_deleted_user(user: Any) -> bool:
    """Удалён ли аккаунт. У удалённого нет ни фамилии, ни имени пользователя."""
    name = str(getattr(user, "first_name", "") or "").strip().lower()
    if name not in DELETED_NAMES:
        return False
    return not getattr(user, "last_name", None) and not getattr(user, "username", None)


# --------------------------------------------------------------------------
#  Мёртвые получатели
# --------------------------------------------------------------------------

def _record(uid: int | str) -> dict[str, Any] | None:
    from . import storage

    return storage.get_user(uid)


def mark_dead(uid: int | str) -> bool:
    """Отмечает недоступного получателя. Только человек: у группы
    `Forbidden` значит другое (бота исключили), и её это не касается."""
    try:
        if int(uid) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    record = _record(uid)
    if record is None or record.get("dead"):
        return False
    record["dead"] = int(time.time())
    log.info("Получатель %s недоступен — отправки ему приостановлены", uid)
    return True


def mark_alive(uid: int | str) -> bool:
    record = _record(uid)
    if record is None or not record.get("dead"):
        return False
    record.pop("dead", None)
    log.info("Получатель %s снова на связи", uid)
    return True


def is_dead(uid: int | str) -> bool:
    record = _record(uid)
    return bool(record and record.get("dead"))


def stale() -> list[tuple[str, int]]:
    """Недоступные получатели: (ключ, когда отмечен)."""
    from . import storage

    return sorted(
        ((key, int(item["dead"])) for key, item in storage.users().items()
         if item.get("dead")),
        key=lambda pair: pair[1])


# --------------------------------------------------------------------------
#  CAS
# --------------------------------------------------------------------------

async def _fetch_cas(user_id: int) -> dict[str, Any] | None:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=CAS_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(CAS_URL, params={"user_id": str(user_id)}) as response:
            if response.status != 200:
                return None
            return await response.json(content_type=None)


async def cas_banned(
    user_id: int,
    fetch: Callable[[int], Awaitable[dict[str, Any] | None]] | None = None,
) -> bool | None:
    """True — в базе, False — нет, None — не удалось узнать.

    Недоступность сервиса — не повод ни банить, ни пускать «на всякий
    случай»: вызывающий решает по None сам (у нас — пропускает).
    """
    try:
        data = await (fetch or _fetch_cas)(user_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("CAS недоступен: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    return bool(data.get("ok"))


# --------------------------------------------------------------------------
#  Чистка удалённых аккаунтов в группе
# --------------------------------------------------------------------------

@dataclass
class Scan:
    chat_id: int
    members_total: int | None = None   # сколько участников в чате по данным Telegram
    known: int = 0                     # сколько из них бот видел
    checked: int = 0
    deleted: list[int] = field(default_factory=list)
    failed: int = 0
    truncated: bool = False

    @property
    def coverage(self) -> str:
        if not self.members_total:
            return f"{self.known}"
        return f"{self.known} / {self.members_total}"


async def scan_chat(bot: Any, chat_id: int, ids: list[int],
                    pause: float = SCAN_PAUSE) -> Scan:
    """Находит удалённые аккаунты среди известных боту участников."""
    result = Scan(chat_id=chat_id, known=len(ids))
    try:
        result.members_total = int(await bot.get_chat_member_count(chat_id))
    except Exception:  # noqa: BLE001
        result.members_total = None

    batch = ids[:SCAN_LIMIT]
    result.truncated = len(ids) > len(batch)
    for user_id in batch:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:  # noqa: BLE001
            # Вышел из чата или бот потерял права — не повод считать его
            # удалённым, но и проверенным он не стал.
            result.failed += 1
        else:
            result.checked += 1
            if is_deleted_user(getattr(member, "user", None)):
                result.deleted.append(user_id)
        await asyncio.sleep(pause)
    return result


async def remove_deleted(bot: Any, chat_id: int, ids: list[int],
                         pause: float = SCAN_PAUSE) -> int:
    """Исключает найденных. Бан сразу снимается: человека нет, а запись
    «заблокирован» в списке чата только засоряла бы его."""
    from .db import repo

    removed = 0
    for user_id in ids:
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        except Exception:  # noqa: BLE001
            log.debug("Не удалось исключить %s из %s", user_id, chat_id, exc_info=True)
            continue
        removed += 1
        await repo.member_drop(chat_id, user_id)
        await asyncio.sleep(pause)
    if removed:
        log.info("Чат %s: исключено удалённых аккаунтов — %d", chat_id, removed)
    return removed
