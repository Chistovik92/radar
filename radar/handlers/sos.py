"""Кнопка SOS в интерфейсе бота."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import config, features, geocode, roles, sos, storage
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, bot, safe_edit, send_html

log = logging.getLogger("radar.handlers.sos")
router = Router(name="sos")


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20),
        headers={"User-Agent": config.USER_AGENT},
    )


def _menu(user: dict) -> InlineKeyboardMarkup:
    contacts = sos.contacts_of(user)
    rows: list[list[InlineKeyboardButton]] = []

    for contact in contacts:
        mark = "✅" if contact.confirmed else "⏳"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {contact.title[:30]}",
                callback_data=f"sos:contact:{contact.key}",
            )
        ])

    if len(contacts) < sos.MAX_CONTACTS:
        rows.append([
            InlineKeyboardButton(text="➕ Добавить контакт", callback_data="sos:add")
        ])

    if sos.confirmed_contacts(user) or contacts:
        rows.append([
            InlineKeyboardButton(text="🆘 Отправить сигнал", callback_data="sos:fire")
        ])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _overview(user: dict) -> str:
    contacts = sos.contacts_of(user)
    lines = ["🆘 <b>Экстренная помощь</b>", ""]

    if not contacts:
        lines.append(
            "Доверенные контакты не заданы. Добавьте человека, которому уйдёт "
            "ваша геопозиция, если вы нажмёте кнопку SOS."
        )
    else:
        lines.append("<b>Доверенные контакты:</b>")
        for contact in contacts:
            state = "готов принимать сигнал" if contact.confirmed else (
                "не подтверждён — не открывал бота"
            )
            mark = "✅" if contact.confirmed else "⏳"
            lines.append(f"{mark} {esc(contact.title)} — <i>{state}</i>")

        if not sos.confirmed_contacts(user):
            lines.append("")
            lines.append(
                "⚠️ Ни один контакт не подтверждён. Telegram не даёт боту писать "
                "первым — контакт должен открыть бота по вашей ссылке. Пока этого "
                "не произошло, сигнал уйдёт администраторам системы."
            )

    lines.append("")
    lines.append(
        "<b>Бот не заменяет экстренные службы.</b> При угрозе жизни звоните 112."
    )
    return "\n".join(lines)


@router.callback_query(F.data == "sos:menu")
async def show_menu(call: CallbackQuery, state: FSMContext, user: dict) -> None:
    if not features.enabled("sos"):
        await call.answer("Функция отключена суперадминистратором.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, _overview(user), _menu(user))


@router.message(Command("sos"))
async def cmd_sos(message: Message, state: FSMContext, user: dict) -> None:
    if not features.enabled("sos"):
        await message.answer("Функция SOS отключена.")
        return
    await state.clear()
    await message.answer(_overview(user), reply_markup=_menu(user))


# --------------------------------------------------------------------------
#  Контакты
# --------------------------------------------------------------------------

@router.callback_query(F.data == "sos:add")
async def ask_contact(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(Form.sos_contact)
    await safe_edit(
        call,
        "➕ <b>Доверенный контакт</b>\n\n"
        "Пришлите <b>числовой ID</b> человека в Telegram — его можно узнать "
        "у @userinfobot, — либо перешлите сюда любое его сообщение.\n\n"
        "После этого вы получите ссылку-приглашение: контакт откроет её "
        "и нажмёт «Старт». Без этого шага Telegram не позволит боту "
        "написать ему первым.\n\n<i>/cancel — отмена.</i>",
        back_kb("sos:menu", "Отмена"),
    )


@router.message(Form.sos_contact)
async def save_contact(message: Message, state: FSMContext, user: dict) -> None:
    key = ""
    title = ""

    forwarded = getattr(message, "forward_from", None)
    if forwarded is not None:
        key = str(forwarded.id)
        title = forwarded.full_name or forwarded.username or key
    else:
        text = (message.text or "").strip()
        if text.startswith("/"):
            return
        if text.isdigit() and len(text) >= 5:
            key = text
            title = f"ID {text}"
        else:
            await message.answer(
                "❌ Нужен числовой ID или пересланное сообщение.\n"
                "<i>Если пересылка не сработала — у человека закрыт профиль "
                "в настройках приватности, попросите у него ID через @userinfobot.</i>"
            )
            return

    if key == str(message.from_user.id):
        await message.answer("❌ Нельзя указать самого себя.")
        return

    contact, error = sos.add_contact(user, key, title)
    await state.clear()
    if contact is None:
        await message.answer(f"❌ {esc(error)}", reply_markup=back_kb("sos:menu", "◀️ Назад"))
        return

    await storage.save(message.from_user.id)

    me = await bot.get_me()
    sender = message.from_user.full_name or "Пользователь"
    invite = sos.build_invite_text(sender, me.username, contact.invite)

    await message.answer(
        f"✅ Контакт <b>{esc(contact.title)}</b> добавлен.\n\n"
        "Перешлите ему сообщение ниже — без подтверждения сигнал не дойдёт.",
        reply_markup=back_kb("sos:menu", "◀️ К настройкам"),
    )
    await message.answer(invite)


@router.callback_query(F.data.startswith("sos:contact:"))
async def contact_card(call: CallbackQuery, user: dict) -> None:
    key = call.data.split(":", 2)[2]
    contact = next((item for item in sos.contacts_of(user) if item.key == key), None)
    if contact is None:
        await call.answer("Контакт не найден.", show_alert=True)
        return

    await call.answer()
    me = await bot.get_me()
    lines = [
        f"👤 <b>{esc(contact.title)}</b>",
        f"Состояние: {'подтверждён' if contact.confirmed else 'ожидает подтверждения'}",
    ]
    if not contact.confirmed:
        lines.append("")
        lines.append(
            f"Ссылка-приглашение:\nhttps://t.me/{me.username}?start=sos_{contact.invite}"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить контакт", callback_data=f"sos:drop:{key}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sos:menu")],
    ])
    await safe_edit(call, "\n".join(lines), kb)


@router.callback_query(F.data.startswith("sos:drop:"))
async def drop_contact(call: CallbackQuery, user: dict) -> None:
    key = call.data.split(":", 2)[2]
    if sos.remove_contact(user, key):
        await storage.save(call.from_user.id)
        await call.answer("Контакт удалён")
    else:
        await call.answer("Контакт не найден", show_alert=True)
    await safe_edit(call, _overview(user), _menu(user))


# --------------------------------------------------------------------------
#  Отправка сигнала
# --------------------------------------------------------------------------

@router.callback_query(F.data == "sos:fire")
async def ask_location(call: CallbackQuery, state: FSMContext) -> None:
    if not features.enabled("sos"):
        await call.answer("Функция отключена.", show_alert=True)
        return
    await call.answer()
    await state.set_state(Form.sos_location)
    await safe_edit(
        call,
        "🆘 <b>Отправка сигнала</b>\n\n"
        "Пришлите <b>геопозицию</b>: Скрепка → Геопозиция.\n"
        "Лучше выбрать «Транслировать» — тогда контакт будет видеть перемещение.\n\n"
        "Можно добавить подпись к геопозиции — она уйдёт вместе с сигналом.\n\n"
        "<i>/cancel — отмена. При угрозе жизни звоните 112.</i>",
        back_kb("sos:menu", "Отмена"),
    )


@router.message(Form.sos_location, F.location)
async def fire_alert(message: Message, state: FSMContext, user: dict) -> None:
    await state.clear()
    lat = message.location.latitude
    lon = message.location.longitude
    note = (message.caption or "").strip()

    address = ""
    try:
        async with _session() as session:
            info = await geocode.reverse(session, lat, lon)
            address = ", ".join(
                part for part in (info.get("name"), info.get("city")) if part
            )
    except Exception:  # noqa: BLE001
        log.warning("Адрес для SOS не определён", exc_info=True)

    owner = str(message.from_user.id)
    sender = message.from_user.full_name or "Пользователь"
    link = f"@{message.from_user.username}" if message.from_user.username else ""

    text = sos.build_alert(sender, link, lat, lon, address, note)
    contacts = sos.confirmed_contacts(user)
    failed: list[str] = []

    for contact in contacts:
        delivered = await send_html(contact.key, text)
        if delivered:
            try:
                await bot.send_location(int(contact.key), lat, lon)
            except Exception:  # noqa: BLE001
                pass
        else:
            failed.append(contact.title)

    # Запасной адресат: если подтверждённых контактов нет или не дошло
    if not contacts or len(failed) == len(contacts):
        admins = [
            uid for uid, data in storage.users().items()
            if roles.is_admin(data.get("role")) and uid != owner
        ]
        for uid in admins:
            await send_html(
                uid,
                "⚠️ <b>Сигнал SOS без доверенных контактов</b>\n\n" + text,
            )
        if admins:
            log.warning("SOS от %s ушёл администраторам: контактов нет", owner)

    sos.start_alert(owner, lat, lon, address, note)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я в порядке — отбой", callback_data="sos:cancel")],
    ])
    await message.answer(sos.build_receipt(contacts, failed), reply_markup=kb)


@router.message(Form.sos_location)
async def need_location(message: Message) -> None:
    if (message.text or "").startswith("/"):
        return
    await message.answer(
        "Нужна именно геопозиция: Скрепка → Геопозиция.\n"
        "<i>/cancel — отмена.</i>"
    )


@router.callback_query(F.data == "sos:cancel")
async def cancel_alert(call: CallbackQuery, user: dict) -> None:
    owner = str(call.from_user.id)
    if not sos.stop_alert(owner):
        await call.answer("Активных сигналов нет.")
        return

    await call.answer("Отбой отправлен")
    sender = call.from_user.full_name or "Пользователь"
    notice = sos.build_cancel_notice(sender)
    for contact in sos.confirmed_contacts(user):
        await send_html(contact.key, notice)

    await safe_edit(
        call,
        "✅ <b>Отбой</b>\n\nПовторные сигналы прекращены, контакты уведомлены.",
        back_kb(),
    )
