"""Ссылка на группу, где бот работает модератором.

Зачем отдельный модуль: ссылка нужна и боту, и веб-панели, а правило
получения у неё нетривиальное и ошибиться в нём дорого.

Порядок намеренно такой:

1. **Публичное имя** (`@name`) — лучшая ссылка: не отзывается, понятна
   на вид, работает для всех.
2. **Существующая постоянная ссылка** чата — если она уже есть, берём
   её. Именно этого просил автор: ссылка владельца уже разослана людям,
   и подменять её нельзя.
3. **Своя дополнительная ссылка** — только если первых двух нет.
   Создаётся `createChatInviteLink`, а НЕ `exportChatInviteLink`:
   второй отзывает прежнюю постоянную ссылку, и все, кому её раздали
   раньше, остаются с нерабочей. Разница в одном вызове, цена ошибки —
   сломанные приглашения у живых людей.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

log = logging.getLogger("radar.chatlink")

# Имя своей ссылки: по нему владелец в списке приглашений группы
# понимает, откуда она взялась.
LINK_TITLE = "Радар"

_cache: dict[int, str] = {}


def forget(chat_id: int) -> None:
    """Сбросить запомненную ссылку — например, когда бота выгнали."""
    _cache.pop(chat_id, None)


async def link_for(chat_id: int, bot=None) -> tuple[bool, str]:
    """Ссылка на чат. Возвращает (получилось, ссылка или причина)."""
    if chat_id in _cache:
        return True, _cache[chat_id]

    if bot is None:
        from .tg import bot as default_bot

        bot = default_bot

    try:
        chat = await bot.get_chat(chat_id)
    except Exception as exc:  # noqa: BLE001
        log.info("Чат %s недоступен: %s", chat_id, exc)
        return False, "Чат недоступен: бот удалён из группы или потерял права."

    username = getattr(chat, "username", "") or ""
    if username:
        link = f"https://t.me/{username}"
        _cache[chat_id] = link
        return True, link

    existing = getattr(chat, "invite_link", "") or ""
    if existing:
        # Ссылка владельца уже существует — используем её, а не свою.
        _cache[chat_id] = existing
        return True, existing

    try:
        created = await bot.create_chat_invite_link(chat_id, name=LINK_TITLE)
    except Exception as exc:  # noqa: BLE001
        log.info("Ссылка для %s не создана: %s", chat_id, exc)
        return False, ("Ссылки нет, и создать её не удалось: нужно право "
                       "«Пригласительные ссылки» у бота в этой группе.")

    link = getattr(created, "invite_link", "") or ""
    if not link:
        return False, "Telegram не вернул ссылку."
    _cache[chat_id] = link
    return True, link
