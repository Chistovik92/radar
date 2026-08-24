"""Ответ тем, кто писал боту, пока он был выключен.

Зачем это нужно. При обновлении контейнер останавливается на несколько
минут: сборка образа, диагностика, запуск. Всё это время отвечать некому.
Дальше при старте выполняется

    await bot.delete_webhook(drop_pending_updates=True)

и накопившиеся сообщения **стираются без следа**. Человек написал во время
обновления — и не получил ответа никогда. Для системы оповещения это плохо
вдвойне: молчание неотличимо от поломки, а решение «написать ещё раз»
человек принимает, уже не доверяя боту.

Как это решено. Перед сбросом очереди мы один раз забираем накопившиеся
обновления, достаём из них идентификаторы чатов — и только их. Сами
обновления **не обрабатываются**: повторять нажатие SOS десятиминутной
давности или заново разбирать присланную геопозицию нельзя, это выглядело
бы как события, происходящие сейчас. Люди получают короткое сообщение
«были работы, повторите», очередь очищается как и раньше.

Ограничения, заложенные намеренно:

* пишем только **зарегистрированным** пользователям. Посторонний, наткнувшийся
  на бота в простой, и так получил бы «доступ закрыт» — писать ему нечего;
* не больше `MAX_NOTIFIED` человек за раз, с паузой между сообщениями:
  Telegram ограничивает частоту, а очередь после долгого простоя может быть
  большой;
* любая ошибка здесь не должна мешать запуску. Оповещения важнее вежливости:
  если уведомить не вышло, бот всё равно обязан подняться.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

log = logging.getLogger("radar.restartnotice")

# Сколько человек уведомляем за один запуск. Больше — уже похоже на рассылку,
# а Telegram ограничивает частоту отправки.
MAX_NOTIFIED = 50
# Пауза между сообщениями, как в рассылке changelog.
PAUSE = 0.2


def chat_ids(updates: Iterable[Any]) -> list[str]:
    """Идентификаторы чатов из накопившихся обновлений, без повторов.

    Порядок сохраняется: кто написал раньше, тот раньше и получит ответ.
    Разбираем и сообщения, и нажатия кнопок — во время простоя копится
    и то и другое.
    """
    found: list[str] = []
    seen: set[str] = set()

    for update in updates or []:
        source = getattr(update, "message", None) or getattr(update, "callback_query", None)
        if source is None:
            continue

        user = getattr(source, "from_user", None)
        uid = getattr(user, "id", None)
        if uid is None:
            continue

        key = str(uid)
        if key not in seen:
            seen.add(key)
            found.append(key)

    return found


async def notify(bot: Any, users: dict[str, Any], sender: Any,
                 lang_of: Any, text_for: Any) -> int:
    """Забирает очередь, отвечает написавшим и возвращает их число.

    Очередь после этого остаётся нетронутой: `get_updates` без `offset`
    не подтверждает обновления, а сбрасывает их прежний
    `delete_webhook(drop_pending_updates=True)` — он вызывается после.
    """
    try:
        updates = await bot.get_updates(timeout=0, limit=100)
    except Exception as exc:  # noqa: BLE001
        log.info("Очередь обновлений не прочитана: %s", exc)
        return 0

    candidates = [uid for uid in chat_ids(updates) if uid in users]
    if not candidates:
        return 0

    if len(candidates) > MAX_NOTIFIED:
        log.info("Писали %d человек, уведомлю первых %d",
                 len(candidates), MAX_NOTIFIED)
        candidates = candidates[:MAX_NOTIFIED]

    sent = 0
    for uid in candidates:
        try:
            await sender(uid, text_for(lang_of(users.get(uid))))
            sent += 1
        except Exception as exc:  # noqa: BLE001
            # Заблокировал бота, удалил чат — обычное дело, не ошибка.
            log.debug("Уведомление %s не доставлено: %s", uid, exc)
        await asyncio.sleep(PAUSE)

    if sent:
        log.info("Уведомлено о технических работах: %d", sent)
    return sent
