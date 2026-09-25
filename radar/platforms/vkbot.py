"""Ответчик ВКонтакте (с 5.6): привязка к Telegram и копии тревог.

⚠️ С ЖИВЫМ СООБЩЕСТВОМ НЕ ПРОВЕРЕН.

Что умеет бот в ВК:

* принять код привязки из Telegram-бота и с этого момента получать копии
  тревог по адресам привязанного человека (`radar/mirror.py`);
* `/unlink` — снять привязку;
* `/status` — работает ли мониторинг; на всё остальное — справка.

Адреса, подписки и настройки здесь не задаются намеренно: они живут
в Telegram-аккаунте, и вторая их реализация поверх другого API стоила бы
дороже, чем даёт. ВК — второй канал доставки для того, кто уже настроил
бота, и единственный способ получать тревоги тем, у кого Telegram
работает с перебоями.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from typing import Any

from .. import links
from .base import EventKind, InboundEvent, OutboundMessage

log = logging.getLogger("radar.platform.vkbot")

DISCLAIMER = "Система не заменяет официальные каналы оповещения."

ABOUT = (
    "Система «Радар» следит за городскими угрозами и авариями ЖКХ "
    "по вашим адресам.\n\n"
    "Здесь, во ВКонтакте, приходят копии тревог. Адреса задаются "
    "в Telegram-боте; чтобы связать аккаунты, нажмите там «🔗 Привязать "
    "ВК или MAX» и пришлите сюда шестизначный код.\n\n"
    "/status — работает ли мониторинг\n/unlink — отвязать аккаунт\n\n"
    + DISCLAIMER
)


def _setting(key: str) -> str:
    from .. import secrets

    return str(secrets.get(key) or "").strip()


def enabled() -> bool:
    from .. import features

    return (features.enabled("platform_vk") and bool(_setting("VK_BOT_TOKEN"))
            and _setting("VK_BOT_GROUP_ID").lstrip("-").isdigit())


def status_text() -> str:
    from .. import monitor

    healthy, silent = monitor.alive()
    if healthy:
        return "✅ Мониторинг работает."
    return f"🚨 Мониторинг молчит около {max(1, silent // 60)} мин. Администрация уведомлена."


async def answer(event: InboundEvent) -> str:
    """Текст ответа. Отделён от сети — проверяется офлайн."""
    external = event.identity.external_id
    linked = await links.handle_text("vk", external, event.text)
    if linked:
        return linked
    if event.kind is EventKind.COMMAND and event.command == "status":
        return status_text() + "\n\n" + DISCLAIMER
    return ABOUT


async def reply(event: InboundEvent, transport: Any) -> None:
    text = await answer(event)
    if text and not await transport.send(event.chat_id, OutboundMessage(text=text)):
        log.warning("VK: ответ не доставлен")
