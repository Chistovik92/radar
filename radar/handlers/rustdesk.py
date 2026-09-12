"""Раздел «RustDesk»: адрес и ключ сервера, число подключений, управление.

Три уровня доступа в одном разделе:

* адрес и ключ — подписчикам и администрации (`subscription.active`);
* число подключений — только администрации (`roles.is_admin`);
* запуск/остановка/перезапуск — только суперадминистратору
  (`roles.is_superadmin`) — тот же риск-класс, что «Обновление из панели»:
  управление идёт через сокет Docker, который равносилен root на хосте.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .. import features, i18n, keyboards, roles, rustdesk, subscription
from ..textutils import esc
from ..tg import safe_edit

log = logging.getLogger("radar.handlers.rustdesk")
router = Router(name="rustdesk")

_ACTION_TITLES = {
    "restart": "🔄 Перезапустить",
    "stop": "⏹ Остановить",
    "start": "▶️ Запустить",
}

# Одно и то же на каждом устройстве, которое должно видеть остальные:
# и на том, откуда подключаются, и на том, к которому подключаются.
RUSTDESK_SETUP_STEPS = (
    "<b>Как подключить устройство:</b>\n"
    "1. Установите RustDesk (кнопка ниже).\n"
    "2. Значок ⚙️ → «Сеть» → «ID/Relay Server».\n"
    "3. Вставьте ID Server, Relay Server и Key из этого сообщения.\n"
    "4. Сохраните — то же самое нужно на обоих устройствах: и на том, "
    "с которого подключаются, и на том, к которому подключаются."
)


def _menu(role: str, lang: str = i18n.DEFAULT) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(
            text=i18n.t("rustdesk.info_button", lang, "📋 Адрес и ключ"),
            callback_data="rd:info",
        ),
    ]]
    if roles.is_admin(role):
        rows.append([InlineKeyboardButton(
            text=i18n.t("rustdesk.conn_button", lang, "🔌 Подключения сейчас"),
            callback_data="rd:conn",
        )])
    if roles.is_superadmin(role):
        rows.append([
            InlineKeyboardButton(text=_ACTION_TITLES["restart"],
                                 callback_data="rd:ask:restart"),
            InlineKeyboardButton(text=_ACTION_TITLES["stop"],
                                 callback_data="rd:ask:stop"),
            InlineKeyboardButton(text=_ACTION_TITLES["start"],
                                 callback_data="rd:ask:start"),
        ])
    rows.append([InlineKeyboardButton(
        text=i18n.t("menu.home", lang, "🏠 В главное меню"),
        callback_data="menu:main",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "rd:menu")
async def menu_rustdesk(call: CallbackQuery, user: dict, role: str) -> None:
    if not features.enabled("rustdesk"):
        await call.answer("Раздел выключен.", show_alert=True)
        return
    await call.answer()
    lang = i18n.language_of(user)
    await safe_edit(
        call,
        i18n.t("rustdesk.title", lang, "🖥 <b>RustDesk</b>"),
        _menu(role, lang),
    )


@router.callback_query(F.data == "rd:info")
async def show_info(call: CallbackQuery, user: dict, role: str) -> None:
    lang = i18n.language_of(user)
    if not subscription.active(user, role):
        await call.answer()
        await safe_edit(
            call,
            i18n.t(
                "rustdesk.no_subscription", lang,
                "⭐️ <b>Адрес и ключ — по подписке</b>\n\n"
                "Подписка открывает подключение к своему RustDesk-серверу, "
                "а также загрузку видео без предела и все тематики "
                "новостных подборок. Оповещения об опасности бесплатны "
                "всегда.",
            ),
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оформить подписку",
                                      callback_data="sub:menu")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="rd:menu")],
            ]),
        )
        return

    ok, payload = rustdesk.client_info()
    if not ok:
        await call.answer(str(payload), show_alert=True)
        return

    info = payload
    text = (
        f"{i18n.t('rustdesk.info_title', lang, '📋 <b>Данные для подключения</b>')}\n\n"
        f"ID Server: <code>{esc(info['host'])}:{info['id_port']}</code>\n"
        f"Relay Server: <code>{esc(info['host'])}:{info['relay_port']}</code>\n"
        f"Key:\n<code>{esc(info['key'])}</code>\n\n"
        f"{i18n.t('rustdesk.setup_steps', lang, RUSTDESK_SETUP_STEPS)}"
    )
    await call.answer()
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ Скачать клиент RustDesk",
                              url="https://rustdesk.com/")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="rd:menu")],
    ]))


@router.callback_query(F.data == "rd:conn")
async def show_connections(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Только для администрации.", show_alert=True)
        return

    ok, payload = await rustdesk.connection_counts()
    if not ok:
        await call.answer(str(payload), show_alert=True)
        return

    counts = payload
    text = (
        "🔌 <b>Подключения сейчас</b>\n\n"
        f"hbbs (устройства онлайн): <b>{counts['hbbs']}</b>\n"
        f"hbbr (активные сессии): <b>{counts['hbbr']}</b>\n\n"
        "<i>Это оценка по установленным TCP-соединениям — открытая "
        "версия RustDesk не публикует эти числа официально.</i>"
    )
    await call.answer()
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="rd:menu")],
    ]))


@router.callback_query(F.data.startswith("rd:ask:"))
async def ask_action(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    action = call.data.split(":", 2)[2]
    if action not in _ACTION_TITLES:
        await call.answer("Неизвестное действие.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        f"⚠️ {_ACTION_TITLES[action]} RustDesk (hbbs и hbbr)?",
        keyboards.confirm("rd:do", action, "rd:menu"),
    )


@router.callback_query(F.data.startswith("rd:do:"))
async def do_action(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    action = call.data.split(":", 2)[2]
    if action not in _ACTION_TITLES:
        await call.answer("Неизвестное действие.", show_alert=True)
        return

    await call.answer("Выполняю…")
    ok, reason = await rustdesk.control(action)
    log.warning("RustDesk: %s запрошен пользователем %s — %s",
               action, call.from_user.id, "успешно" if ok else reason)

    if ok:
        text = f"✅ {_ACTION_TITLES[action]} — готово."
    else:
        text = f"❌ {_ACTION_TITLES[action]} не удалось: {esc(reason)}"
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="rd:menu")],
    ]))
