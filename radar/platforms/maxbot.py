"""Встроенный ответчик MAX: что бот умеет, пока ядро живёт в Telegram.

⚠️ НА ЖИВОМ СЕРВЕРЕ НЕ ПРОВЕРЕН — как и весь адаптер MAX.

До 4.9.9.4 адаптер получал события и **ничего с ними не делал**:
обработчик в `main.py` не передавался, события разбирались и молча
выбрасывались. Человек, написавший боту в MAX, не получал ответа вовсе —
худший из исходов: снаружи это неотличимо от сломанного бота.

Почему ответчик отдельный и маленький. Ядро «Радара» — команды, роли,
локации, оповещения — написано на aiogram и привязано к Telegram.
Перенести его на MAX означает вторую реализацию всего, поверх API,
который не проверен ни одним живым запросом. Пока MAX отвечает честно:
рассказывает, что есть, и уводит туда, где всё работает.

Что здесь есть: `/start`, `/help`, `/status` и ответ на любое другое
сообщение. Оповещения отсюда **не** рассылаются: без подтверждённой
географии тревога не отправляется, а локации живут в Telegram-аккаунте.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from .. import config
from .base import Button, EventKind, InboundEvent, OutboundMessage

log = logging.getLogger("radar.platform.maxbot")

ABOUT = (
    "<b>Система «Радар»</b>\n\n"
    "Следит за городскими угрозами и авариями ЖКХ по вашим адресам: "
    "читает каналы служб и ленты СМИ, разбирает сообщения и присылает "
    "только то, что касается ваших локаций.\n\n"
    "<b>Здесь, в MAX, бот пока только отвечает.</b> Локации, оповещения, "
    "погода и всё остальное живут в Telegram-боте — адаптер MAX написан, "
    "но ещё не проверен в работе.\n\n"
    "<i>Система не заменяет официальные каналы оповещения.</i>"
)

HELP = (
    "<b>Команды</b>\n"
    "/start — что это такое\n"
    "/help — этот список\n"
    "/status — жив ли мониторинг\n\n"
    "Оповещения приходят в Telegram-боте: там задаются адреса, "
    "без подтверждённого адреса тревога не отправляется."
)


# Имя Telegram-бота узнаём один раз: оно не меняется, а лишний запрос
# к Telegram на каждое сообщение в MAX — это чужая квота впустую.
_username = ""


async def telegram_username() -> str:
    """Имя Telegram-бота. Пусто — узнать не удалось."""
    global _username

    if _username:
        return _username
    try:
        from ..tg import bot

        me = await bot.get_me()
        _username = str(getattr(me, "username", "") or "")
    except Exception:  # noqa: BLE001
        log.debug("Имя Telegram-бота не определено", exc_info=True)
    return _username


def telegram_button(username: str = "") -> list[list[Button]]:
    """Кнопка перехода в Telegram-бота, если его имя известно."""
    if not username:
        return []
    return [[Button(text="Открыть бота в Telegram",
                    url=f"https://t.me/{username}")]]


def status_text() -> str:
    """Короткая сводка состояния — та же, что в метриках, но без чисел,
    которые постороннему ничего не скажут."""
    from .. import monitor

    healthy, silent = monitor.alive()
    if healthy:
        return "✅ Мониторинг работает."
    return (f"🚨 Мониторинг молчит {silent} с — администрация уведомлена, "
            f"сторож поднимает цикл заново.")


def answer_for(event: InboundEvent, username: str = "") -> OutboundMessage:
    """Что ответить на событие. Отделено от отправки — проверяется офлайн."""
    if event.kind is EventKind.JOINED:
        return OutboundMessage(text=ABOUT, keyboard=telegram_button(username))

    if event.kind is EventKind.COMMAND:
        if event.command in ("start", "about"):
            return OutboundMessage(text=ABOUT, keyboard=telegram_button(username))
        if event.command == "help":
            return OutboundMessage(text=HELP, keyboard=telegram_button(username))
        if event.command == "status":
            return OutboundMessage(text=status_text())
        return OutboundMessage(
            text="Такой команды нет. /help — что бот умеет.")

    if event.kind is EventKind.LOCATION:
        # Геопозиция здесь ничего не даёт: локации привязаны к учётной
        # записи Telegram. Сказать об этом прямо честнее, чем принять
        # точку и ничего по ней не прислать.
        return OutboundMessage(
            text="Адреса пока задаются только в Telegram-боте — "
                 "здесь геопозиция ни к чему не привяжется.",
            keyboard=telegram_button(username))

    return OutboundMessage(text=HELP, keyboard=telegram_button(username))


async def reply(event: InboundEvent, transport) -> None:
    """Обработчик, который адаптер зовёт на каждое событие."""
    if event.kind is EventKind.CALLBACK and event.args:
        # Сначала гасим «часики» у нажатой кнопки, потом отвечаем.
        await transport.answer_callback(event.args)

    message = answer_for(event, await telegram_username())
    if not message.text:
        return
    sent = await transport.send(event.chat_id, message)
    if not sent:
        log.warning("MAX: ответ %s не доставлен", event.chat_id)


def enabled() -> bool:
    """Включён ли адаптер: флаг возможности плюс заданный токен."""
    from .. import features

    return features.enabled("platform_max") and bool(config.MAX_BOT_TOKEN)
