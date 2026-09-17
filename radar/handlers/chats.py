"""Раздел «Чаты» в самой переписке с ботом.

Отсюда видно, где бот модерирует, и отсюда же можно перейти в группу:
кнопка ведёт по ссылке — публичному имени, существующей ссылке владельца
или, если ни того ни другого нет, по созданной ботом (см. `radar/chatlink.py`).

Раздел личный, а не групповой: список чатов и переходы — дело
администрации, а не участников группы.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import chatlink, features, roles
from ..db import repo
from ..textutils import esc
from ..tg import safe_edit, send_html

router = Router(name="chats")

ADD_HINT = (
    "🛡 <b>Чаты под модерацией</b>\n\n"
    "Пока ни одной группы.\n\n"
    "<b>Как добавить бота:</b>\n"
    "1. Откройте группу → «Участники» → «Добавить».\n"
    "2. Найдите бота по имени и добавьте.\n"
    "3. Там же сделайте его администратором и включите права "
    "<b>«Удаление сообщений»</b> и <b>«Блокировка участников»</b>.\n"
    "4. Напишите в группе <code>/modon</code> — чат появится здесь.\n\n"
    "<b>Бот уже в группе?</b> Тогда ничего добавлять не нужно: "
    "проверьте, что он администратор с этими правами, и напишите "
    "в группе <code>/modon</code>. Группы, куда бота добавили раньше, "
    "сами о себе не заявляют — Telegram сообщает боту только "
    "об изменениях.\n\n"
    "<i>Менять privacy mode у @BotFather не нужно: администратор "
    "получает все сообщения и так. Тем, кто уже в группе, бот ничего "
    "не пишет — проверка только для тех, кто войдёт после включения.</i>"
)


def _keyboard(rows: list[dict], links: dict[int, str]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for row in rows:
        chat_id = row["chat_id"]
        title = row["title"] or str(chat_id)
        mark = "🟢" if row["enabled"] else "⚪️"
        link = links.get(chat_id, "")
        if link:
            buttons.append([InlineKeyboardButton(
                text=f"{mark} {title}", url=link)])
        else:
            buttons.append([InlineKeyboardButton(
                text=f"{mark} {title}", callback_data=f"chat:why:{chat_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад",
                                         callback_data="menu:manage")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _render(role: str) -> tuple[str, InlineKeyboardMarkup]:
    rows = await repo.chat_list()
    if not rows:
        return ADD_HINT, InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Назад", callback_data="menu:manage")
        ]])

    links: dict[int, str] = {}
    lines = ["🛡 <b>Чаты под модерацией</b>", ""]
    for row in rows:
        ok, value = await chatlink.link_for(row["chat_id"])
        if ok:
            links[row["chat_id"]] = value
        state = "модерация включена" if row["enabled"] else "модерация выключена"
        lines.append(f"• <b>{esc(row['title'] or str(row['chat_id']))}</b> — {state}")
        if not ok:
            lines.append(f"  <i>{esc(value)}</i>")
    lines.append("")
    lines.append("<i>Нажмите на группу, чтобы перейти в неё.</i>")
    return "\n".join(lines), _keyboard(rows, links)


@router.message(Command("chats"))
async def cmd_chats(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        return
    if not features.enabled("moderation"):
        await send_html(message.chat.id,
                        "Модерация выключена — включите её в разделе "
                        "«Возможности».")
        return
    text, keyboard = await _render(role)
    await send_html(message.chat.id, text, keyboard)


@router.callback_query(F.data == "menu:chats")
async def menu_chats(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Только для администрации.", show_alert=True)
        return
    await call.answer()
    text, keyboard = await _render(role)
    await safe_edit(call, text, keyboard)


@router.callback_query(F.data.startswith("chat:why:"))
async def explain(call: CallbackQuery, role: str) -> None:
    """Почему у чата нет кнопки перехода."""
    if not roles.is_admin(role):
        await call.answer("Только для администрации.", show_alert=True)
        return
    chat_id = int(call.data.rsplit(":", 1)[1])
    _ok, reason = await chatlink.link_for(chat_id)
    await call.answer(reason, show_alert=True)
