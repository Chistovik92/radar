"""Ответчик MAX (4.9.9.4; полноценный вход в общий аккаунт — 5.7).

⚠️ НА ЖИВОМ СЕРВЕРЕ НЕ ПРОВЕРЕН — как и весь адаптер MAX.

До 4.9.9.4 адаптер получал события и **ничего с ними не делал**. До 5.7
ответчик только рассказывал, что адреса живут в Telegram. С общим
аккаунтом (`radar/links.py`) начать можно и здесь: адрес задаётся
командой `/address` или геопозицией, тревоги по нему приходят сюда,
а Telegram, ВК и Discord привязываются общим кодом. Логика ответов
общая с ВКонтакте — `radar/platforms/textbot.py`; здесь остаётся
приветствие при добавлении бота и кнопка перехода в Telegram.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from .. import config
from ..textutils import esc
from .base import Button, EventKind, InboundEvent, OutboundMessage

log = logging.getLogger("radar.platform.maxbot")

ABOUT = (
    "<b>Система «Радар»</b>\n\n"
    "Следит за городскими угрозами и авариями ЖКХ по вашим адресам: "
    "читает каналы служб и ленты СМИ, разбирает сообщения и присылает "
    "только то, что касается ваших адресов.\n\n"
    "Добавьте адрес: /address улица, дом, город — или отправьте геопозицию. "
    "Уже пользуетесь ботом в Telegram или ВК? /link — и аккаунт станет общим. "
    "Адаптер MAX написан, но ещё не проверен в работе.\n\n"
    "<i>Система не заменяет официальные каналы оповещения.</i>"
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
    """Приветствие при добавлении бота. Остальное отвечает `textbot`."""
    return OutboundMessage(text=ABOUT, keyboard=telegram_button(username))


async def reply(event: InboundEvent, transport) -> None:
    """Обработчик, который адаптер зовёт на каждое событие."""
    from . import textbot

    if event.kind is EventKind.CALLBACK and event.args:
        # Сначала гасим «часики» у нажатой кнопки, потом отвечаем.
        await transport.answer_callback(event.args)

    if event.kind is EventKind.JOINED:
        message = answer_for(event, await telegram_username())
    elif event.kind in (EventKind.MESSAGE, EventKind.COMMAND, EventKind.LOCATION):
        location = None
        if event.kind is EventKind.LOCATION and event.latitude is not None:
            location = (event.latitude, event.longitude)
        text = event.text or (f"/{event.command} {event.args}".strip() if event.command else "")
        message = OutboundMessage(text=esc(await textbot.answer(
            "max", event.identity.external_id, text, location=location)))
    else:
        return
    if not message.text:
        return
    sent = await transport.send(event.chat_id, message)
    if not sent:
        log.warning("MAX: ответ %s не доставлен", event.chat_id)


def enabled() -> bool:
    """Включён ли адаптер: флаг возможности плюс заданный токен."""
    from .. import features

    return features.enabled("platform_max") and bool(config.MAX_BOT_TOKEN)
