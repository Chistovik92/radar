"""Discord как канал сообщества: сводки и статус системы (с 5.5).

⚠️ С ЖИВЫМ DISCORD НЕ ПРОВЕРЕН.

Замысел дорожной карты — «не оповещения по адресам, а канал для
сообщества». Поэтому здесь три вещи и ни одной тревоги:

* **ответчик на слеш-команды** `/about`, `/help`, `/status`, `/summary` —
  как встроенный ответчик MAX: говорит, что это за система, где живут
  оповещения, и жив ли мониторинг;
* **суточная сводка** в канал `DISCORD_CHANNEL_ID` в `DISCORD_SUMMARY_TIME`:
  сколько событий было по категориям и сколько отбоев. Без адресов,
  городов и текста — сводка публичная. Событие в прошлом — сводка,
  а не тревога, и так она и подписана;
* **смена статуса мониторинга**: цикл замолчал — сообщение в канал,
  поднялся снова — ещё одно. Это то же самое, что видит администрация,
  но без чисел, которые постороннему ничего не скажут.

Формулировка «не заменяет официальные каналы оповещения» есть
в каждом публичном сообщении — правило проекта.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from .base import Button, EventKind, InboundEvent, OutboundMessage

log = logging.getLogger("radar.platform.discordbot")

DISCLAIMER = "<i>Система не заменяет официальные каналы оповещения.</i>"

ABOUT = (
    "<b>Система «Радар»</b>\n\n"
    "Следит за городскими угрозами и авариями ЖКХ: читает каналы служб "
    "и ленты СМИ, разбирает сообщения и присылает оповещения по адресам "
    "тех, кто их задал.\n\n"
    "<b>Здесь, в Discord, — сводки и статус системы.</b> Оповещения "
    "по адресам живут в Telegram-боте: без подтверждённого адреса тревога "
    "не отправляется.\n\n" + DISCLAIMER
)

HELP = (
    "<b>Команды</b>\n"
    "/about — что это такое\n"
    "/status — работает ли мониторинг\n"
    "/summary — сводка за сутки\n"
    "/help — этот список"
)

COMMANDS = (
    ("about", "Что это за система"),
    ("status", "Работает ли мониторинг"),
    ("summary", "Сводка событий за сутки"),
    ("help", "Список команд"),
)

SUMMARY_META = "discord_summary_date"
CHECK_EVERY = 60


def _setting(key: str) -> str:
    from .. import secrets

    return str(secrets.get(key) or "").strip()


def enabled() -> bool:
    from .. import features

    return features.enabled("platform_discord") and bool(_setting("DISCORD_BOT_TOKEN"))


def telegram_button(username: str = "") -> list[list[Button]]:
    if not username:
        return []
    return [[Button(text="Оповещения — в Telegram", url=f"https://t.me/{username}")]]


def status_text(healthy: bool, silent: int) -> str:
    if healthy:
        return "✅ Мониторинг работает."
    minutes = max(1, silent // 60)
    return (f"🚨 Мониторинг молчит около {minutes} мин. Администрация "
            f"уведомлена, цикл поднимается заново.")


def summary_text(counts: dict[str, int], moment: datetime) -> str:
    """Сводка за сутки: категории и отбои. Ни адресов, ни текста."""
    from ..matching import CATEGORY_ICONS, CATEGORY_TITLES

    total = int(counts.get("_total") or 0)
    lines = [f"<b>Сводка за сутки</b> · {moment.strftime('%d.%m.%Y %H:%M')}", ""]
    if not total:
        lines.append("За сутки разобранных событий не было.")
    else:
        lines.append(f"Разобрано событий: <b>{total}</b>")
        for key, title in CATEGORY_TITLES.items():
            count = int(counts.get(key) or 0)
            if count:
                lines.append(f"{CATEGORY_ICONS.get(key, '•')} {title}: {count}")
        clear = int(counts.get("_all_clear") or 0)
        if clear:
            lines.append(f"✅ Отбоев: {clear}")
    lines.append("")
    lines.append("Это сводка о прошедшем, а не тревога. Оповещения по адресам "
                 "приходят в Telegram-боте.")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def answer_for(event: InboundEvent, *, status: str, summary: str = "",
               username: str = "") -> OutboundMessage:
    """Что ответить на команду. Отделено от сети — проверяется офлайн."""
    button = telegram_button(username)
    if event.kind is EventKind.COMMAND:
        if event.command in ("about", "start"):
            return OutboundMessage(text=ABOUT, keyboard=button)
        if event.command == "status":
            return OutboundMessage(text=status + "\n\n" + DISCLAIMER)
        if event.command == "summary":
            return OutboundMessage(text=summary or "Сводка пока недоступна.")
        return OutboundMessage(text=HELP, keyboard=button)
    return OutboundMessage(text=HELP, keyboard=button)


async def _counts() -> dict[str, int]:
    from ..db import repo

    try:
        return await repo.event_breakdown(24)
    except Exception:  # noqa: BLE001
        log.warning("Discord: сводка не собрана — база недоступна")
        return {}


def _status() -> tuple[bool, int]:
    from .. import monitor

    return monitor.alive()


async def reply(event: InboundEvent, transport: Any) -> None:
    """Обработчик взаимодействий: ответ — первым делом, у Discord 3 секунды.

    Сводка требует запроса к базе, поэтому по /summary она собирается
    после того, как Discord уже получил ответ «собираю».
    """
    from .maxbot import telegram_username

    healthy, silent = _status()
    status = status_text(healthy, silent)
    if event.kind is EventKind.COMMAND and event.command == "summary":
        await transport.respond(event, OutboundMessage(text="Собираю сводку…"))
        text = summary_text(await _counts(), datetime.now())
        await transport.send(event.chat_id, OutboundMessage(text=text))
        return
    message = answer_for(event, status=status, username=await telegram_username())
    await transport.respond(event, message, ephemeral=event.command == "help")


async def run(transport: Any) -> None:
    """Всё, что делает Discord: команды, Gateway и публикации в канал."""
    try:
        await transport.set_commands(COMMANDS)
    except Exception:  # noqa: BLE001
        log.warning("Discord: слеш-команды не заданы", exc_info=True)
    await asyncio.gather(transport.start(), community(transport))


def due(now: datetime, when: str, last_date: str) -> bool:
    """Пора ли публиковать сводку: время наступило, а сегодня её ещё не было."""
    try:
        hour, minute = (int(part) for part in (when or "20:00").split(":", 1))
    except ValueError:
        hour, minute = 20, 0
    today = now.strftime("%Y-%m-%d")
    return last_date != today and (now.hour, now.minute) >= (hour, minute)


async def community(transport: Any) -> None:
    """Публикации в канал: суточная сводка и смена статуса мониторинга.

    Отдельная задача с шагом в минуту. Цикл оповещений о ней не знает:
    Discord недоступен — сводка не выйдет, тревоги в Telegram пойдут как
    обычно.
    """
    from .. import storage

    channel = _setting("DISCORD_CHANNEL_ID")
    if not channel:
        log.info("Discord: DISCORD_CHANNEL_ID не задан — публикаций в канал не будет")
        return
    last_healthy = True
    while True:
        try:
            healthy, silent = _status()
            if healthy != last_healthy:
                await transport.send(channel, OutboundMessage(
                    text=status_text(healthy, silent) + "\n\n" + DISCLAIMER))
                last_healthy = healthy
            now = datetime.now()
            last = str(await storage.meta_get(SUMMARY_META, "") or "")
            if due(now, _setting("DISCORD_SUMMARY_TIME"), last):
                # Отметка — до отправки: лучше пропустить одну сводку при
                # сбое, чем прислать две после перезапуска.
                await storage.meta_set(SUMMARY_META, now.strftime("%Y-%m-%d"))
                await transport.send(channel, OutboundMessage(
                    text=summary_text(await _counts(), now), silent=True))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("Discord: публикация в канал не удалась", exc_info=True)
        await asyncio.sleep(CHECK_EVERY)
