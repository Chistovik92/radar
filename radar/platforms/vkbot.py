"""Ответчик ВКонтакте (5.6; полноценный вход в общий аккаунт — 5.7).

⚠️ С ЖИВЫМ СООБЩЕСТВОМ НЕ ПРОВЕРЕН.

С 5.7 начать можно прямо здесь: адреса задаются командой `/address` или
геопозицией, тревоги по ним приходят сюда. Привязка к Telegram, MAX
и Discord — общим кодом (`radar/links.py`). Сама логика ответов общая
с MAX — `radar/platforms/textbot.py`.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from typing import Any

from . import textbot
from .base import EventKind, InboundEvent, OutboundMessage

log = logging.getLogger("radar.platform.vkbot")

DISCLAIMER = textbot.DISCLAIMER


def _setting(key: str) -> str:
    from .. import secrets

    return str(secrets.get(key) or "").strip()


def enabled() -> bool:
    from .. import features

    return (features.enabled("platform_vk") and bool(_setting("VK_BOT_TOKEN"))
            and _setting("VK_BOT_GROUP_ID").lstrip("-").isdigit())


def status_text() -> str:
    return textbot.status_text()


async def answer(event: InboundEvent) -> str:
    """Текст ответа. Отделён от сети — проверяется офлайн."""
    location = None
    if event.kind is EventKind.LOCATION and event.latitude is not None:
        location = (event.latitude, event.longitude)
    return await textbot.answer("vk", event.identity.external_id, event.text,
                                location=location)


async def reply(event: InboundEvent, transport: Any) -> None:
    text = await answer(event)
    if text and not await transport.send(event.chat_id, OutboundMessage(text=text)):
        log.warning("VK: ответ не доставлен")
