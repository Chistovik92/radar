"""Выбор языка интерфейса.

Спрашиваем один раз: при первом запуске у новых, при первом обращении
после обновления — у тех, кто пользовался ботом раньше. Признак «не
спрашивали» — пустое поле `lang`, поэтому обновление автоматически
ставит вопрос всем существующим пользователям, а не молча оставляет
их на русском.

Вопрос показывается на обоих языках сразу: человек, который не читает
по-русски, иначе не понял бы, что от него хотят.
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
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import i18n, keyboards, storage

log = logging.getLogger("radar.handlers.language")
router = Router(name="language")

ASK_TEXT = (
    "🌍 <b>Choose your language / Выберите язык</b>\n\n"
    "You can change it later in the menu.\n"
    "Изменить можно позже в меню."
)


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.TITLES[code], callback_data=f"lng:{code}")]
        for code in i18n.LANGUAGES
    ])


async def ask(message: Message) -> None:
    await message.answer(ASK_TEXT, reply_markup=language_keyboard())


@router.message(Command("language", "lang"))
async def cmd_language(message: Message) -> None:
    await ask(message)


@router.callback_query(F.data == "menu:lang")
async def menu_language(call: CallbackQuery) -> None:
    await call.answer()
    try:
        await call.message.edit_text(ASK_TEXT, reply_markup=language_keyboard())
    except Exception:  # noqa: BLE001
        await call.message.answer(ASK_TEXT, reply_markup=language_keyboard())


@router.callback_query(F.data.startswith("lng:"))
async def choose(call: CallbackQuery, user: dict, role: str) -> None:
    code = i18n.normalize(call.data.split(":", 1)[1])
    user["lang"] = code
    await storage.save()

    await call.answer(i18n.t("lang.saved", code, "Язык переключён на русский."))
    greeting = (
        "Language set to English." if code == i18n.EN
        else "Язык интерфейса — русский."
    )
    try:
        await call.message.edit_text(
            greeting, reply_markup=keyboards.main_menu(role, user)
        )
    except Exception:  # noqa: BLE001
        # Сообщение могло устареть — тогда просто присылаем новое,
        # молчать после нажатия нельзя.
        await call.message.answer(
            greeting, reply_markup=keyboards.main_menu(role, user)
        )
