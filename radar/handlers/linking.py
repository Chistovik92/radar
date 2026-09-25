"""Общий аккаунт в Telegram-боте: привязка других сетей (5.6, в обе стороны — 5.7).

Здесь можно и выдать код (его вводят в ВК, MAX или Discord), и ввести код,
полученный в другой сети: `/link 123456`. Связь заключается после
подтверждения кнопкой. Сама логика — в `radar/links.py`.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import features, i18n, links
from ..textutils import esc
from ..tg import safe_edit

log = logging.getLogger("radar.handlers.linking")
router = Router(name="linking")

FLAGS = {"vk": "platform_vk", "max": "platform_max", "discord": "platform_discord"}


def _available() -> list[str]:
    return [platform for platform, flag in FLAGS.items() if features.enabled(flag)]


def _unavailable(user: dict) -> str:
    return i18n.t("link.unavailable", i18n.language_of(user), "Привязка сейчас недоступна.")


async def _view(uid: str, lang: str, code: str = "") -> tuple[str, InlineKeyboardMarkup]:
    current = await links.links_of(uid)
    lines = [i18n.t("link.title", lang, "🔗 <b>Привязка других сетей</b>"), "",
             i18n.t("link.intro", lang,
                    "Один аккаунт — во всех сетях: адреса и настройки общие, "
                    "тревоги приходят и туда. Привязать можно ВКонтакте, MAX "
                    "и Discord.")]
    rows = []
    for platform in ("vk", "max", "discord"):
        if platform in current:
            lines.append(f"\n✅ {links.TITLES[platform]} — "
                         + i18n.t("link.linked", lang, "привязан"))
            rows.append([InlineKeyboardButton(
                text=i18n.t("link.unlink", lang, "✖️ Отвязать") + f" {links.TITLES[platform]}",
                callback_data=f"lnk:off:{platform}")])
    if code:
        lines.append("")
        lines.append(esc(links.code_text(code, lang)))
    lines.append("")
    lines.append(i18n.t("link.enter_hint", lang,
                        "<i>Код получен в другой сети? Отправьте сюда</i> "
                        "<code>/link КОД</code>."))
    rows.append([InlineKeyboardButton(text=i18n.t("link.get_code", lang, "🔑 Получить код"),
                                      callback_data="lnk:code")])
    rows.append([InlineKeyboardButton(text=i18n.t("common.back", lang, "◀️ Назад"),
                                      callback_data="menu:settings")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "lnk:menu")
async def show(call: CallbackQuery, user: dict) -> None:
    if not _available():
        await call.answer(_unavailable(user), show_alert=True)
        return
    await call.answer()
    text, markup = await _view(str(call.from_user.id), i18n.language_of(user))
    await safe_edit(call, text, markup)


@router.callback_query(F.data == "lnk:code")
async def give_code(call: CallbackQuery, user: dict) -> None:
    if not _available():
        await call.answer(_unavailable(user), show_alert=True)
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
async def link_command(message: Message, user: dict, command: CommandObject) -> None:
    lang = i18n.language_of(user)
    if not _available():
        await message.answer(_unavailable(user))
        return
    uid = str(message.from_user.id)
    code = links.extract_code(command.args or "")
    if not code:
        text, markup = await _view(uid, lang, links.new_code(uid))
        await message.answer(text, reply_markup=markup)
        return
    theirs, reason = await links.propose(links.TELEGRAM, uid, code)
    if reason:
        await message.answer(f"❌ {esc(reason)}")
        return
    await message.answer(esc(links.proposal_text(theirs, lang)), reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=i18n.t("link.yes", lang, "✅ Связать"),
                                 callback_data="lnk:yes"),
            InlineKeyboardButton(text=i18n.t("link.no", lang, "✖️ Отказаться"),
                                 callback_data="lnk:no"),
        ]]))


@router.callback_query(F.data.in_({"lnk:yes", "lnk:no"}))
async def decide(call: CallbackQuery, user: dict) -> None:
    lang = i18n.language_of(user)
    uid = str(call.from_user.id)
    if call.data == "lnk:no":
        links.decline(links.TELEGRAM, uid)
        await call.answer()
        await safe_edit(call, esc(i18n.t("link.declined", lang, "Хорошо, аккаунты не связаны.")),
                        None)
        return
    owner, reason = await links.confirm(links.TELEGRAM, uid)
    if not owner:
        await call.answer(reason, show_alert=True)
        return
    await call.answer()
    asyncio.get_running_loop().create_task(links.announce(owner, links.TELEGRAM))
    await safe_edit(call, esc(links.linked_text(lang)), None)
