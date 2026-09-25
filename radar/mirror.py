"""Дублирование тревог на привязанные площадки (с 5.6).

Тревога, уже доставленная в Telegram, уходит копией на аккаунты ВК и MAX,
привязанные к этому человеку (`radar/links.py`). География подтверждена
в Telegram — там заданы адреса, — поэтому правило «без подтверждённой
географии тревога не отправляется» соблюдено: зеркало не выбирает
получателей само, оно повторяет уже принятое решение.

Три свойства, которые нельзя нарушить:

* **Telegram не ждёт зеркала.** Копии отправляются фоновой задачей;
  медленный или упавший ВК не задерживает следующую тревогу;
* **зеркало не решает, что слать.** Антиспам, тихие часы и отметка
  о доставке уже отработали для Telegram; сюда приходит только то,
  что действительно ушло;
* **сбой зеркала не роняет цикл оповещений.** Любая ошибка — строка
  в журнале, не исключение наружу.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger("radar.mirror")

Sender = Callable[[str, str], Awaitable[bool]]

_senders: dict[str, Sender] = {}
_tasks: set[asyncio.Task] = set()


def register(platform: str, sender: Sender) -> None:
    """Площадка сообщает, как отправить текст её пользователю."""
    _senders[platform] = sender


def unregister(platform: str) -> None:
    _senders.pop(platform, None)


def active() -> list[str]:
    return sorted(_senders)


async def _send_all(uid: str, text: str) -> None:
    from . import links

    try:
        targets = await links.links_of(uid)
    except Exception:  # noqa: BLE001
        log.warning("Зеркало: привязки не прочитаны")
        return
    for platform, external_id in targets.items():
        sender = _senders.get(platform)
        if sender is None:
            continue
        try:
            if not await sender(external_id, text):
                log.warning("Зеркало: копия тревоги в %s не доставлена", platform)
        except Exception:  # noqa: BLE001
            log.warning("Зеркало: сбой отправки в %s", platform, exc_info=True)


def alert(uid: str | int, text: str) -> None:
    """Отправить копию тревоги на привязанные площадки. Не ждёт отправки."""
    if not _senders:
        return
    try:
        task = asyncio.get_running_loop().create_task(_send_all(str(uid), text))
    except RuntimeError:
        return
    # Ссылку держим до завершения: иначе задачу может собрать сборщик мусора.
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain() -> None:
    """Дождаться отправленных копий — для тестов и корректной остановки."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
