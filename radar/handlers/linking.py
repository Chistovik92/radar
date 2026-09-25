"""Привязка ВК и MAX к Telegram-аккаунту (с 5.6).

Код выдаётся здесь, в Telegram, где у человека адреса и настройки,
а вводится в боте ВК или MAX. После привязки тревоги по адресам
дублируются туда (`radar/mirror.py`). Сама логика — в `radar/links.py`.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import features, i18n, links
from ..textutils import esc
from ..tg import safe_edit

log = logging.getLogger("radar.handlers.linking")
router = Router(name="linking")


def _available() -> list[str]:
    platforms = []
    if features.enabled("platform_vk"):
        platforms.append("vk")
    if features.enabled("platform_max"):
        platforms.append("max")
    return platforms


async def _view(uid: str, lang: str, code: str = "") -> tuple[str, InlineKeyboardMarkup]:
    current = await links.links_of(uid)
    lines = [i18n.t("link.title", lang, "🔗 <b>Привязка ВК и MAX</b>"), "",
             i18n.t("link.intro", lang,
                    "Тревоги по вашим адресам будут приходить и туда — "
                    "копией того, что приходит здесь. Адреса и настройки "
                    "остаются в Telegram.")]
    rows = []
    for platform in ("vk", "max"):
        if platform in current:
            lines.append(f"\n✅ {links.TITLES[platform]} — "
                         + i18n.t("link.linked", lang, "привязан"))
            rows.append([InlineKeyboardButton(
                text=i18n.t("link.unlink", lang, "✖️ Отвязать") + f" {links.TITLES[platform]}",
                callback_data=f"lnk:off:{platform}")])
    if code:
        lines.append("")
        lines.append(i18n.t("link.code", lang,
                            "Ваш код: <code>{code}</code>\nОтправьте его боту во ВКонтакте "
                            "или в MAX. Код действует 10 минут.").format(code=esc(code)))
    rows.append([InlineKeyboardButton(text=i18n.t("link.get_code", lang, "🔑 Получить код"),
                                      callback_data="lnk:code")])
    rows.append([InlineKeyboardButton(text=i18n.t("common.back", lang, "◀️ Назад"),
                                      callback_data="menu:settings")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "lnk:menu")
async def show(call: CallbackQuery, user: dict) -> None:
    if not _available():
        await call.answer("Привязка сейчас недоступна.", show_alert=True)
        return
    await call.answer()
    text, markup = await _view(str(call.from_user.id), i18n.language_of(user))
    await safe_edit(call, text, markup)


@router.callback_query(F.data == "lnk:code")
async def give_code(call: CallbackQuery, user: dict) -> None:
    if not _available():
        await call.answer("Привязка сейчас недоступна.", show_alert=True)
        return
    await call.answer()
    uid = str(call.from_user.id)
    text, markup = await _view(uid, i18n.language_of(user), links.new_code(uid))
    await safe_edit(call, text, markup)


@router.callback_query(F.data.startswith("lnk:off:"))
async def unlink(call: CallbackQuery, user: dict) -> None:
    platform = call.data.split(":", 2)[2]
    await links.unlink(str(call.from_user.id), platform)
    await call.answer(i18n.t("link.unlinked", i18n.language_of(user), "Привязка снята."))
    text, markup = await _view(str(call.from_user.id), i18n.language_of(user))
    await safe_edit(call, text, markup)


@router.message(Command("link"))
async def link_command(message: Message, user: dict) -> None:
    if not _available():
        await message.answer("Привязка сейчас недоступна.")
        return
    uid = str(message.from_user.id)
    text, markup = await _view(uid, i18n.language_of(user), links.new_code(uid))
    await message.answer(text, reply_markup=markup)
