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
    KeyboardButton,
    KeyboardButtonRequestUsers,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from .. import config, features, geocode, i18n, roles, sos, storage
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
    lang = i18n.language_of(user)
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
            InlineKeyboardButton(
                text=i18n.t("sos.add", lang, "➕ Добавить контакт"),
                callback_data="sos:add")
        ])

    if sos.confirmed_contacts(user) or contacts:
        rows.append([
            InlineKeyboardButton(
                text=i18n.t("sos.fire", lang, "🆘 Отправить сигнал"),
                callback_data="sos:fire")
        ])
    rows.append([InlineKeyboardButton(
        text=i18n.t("menu.home", lang, "🏠 В главное меню"),
        callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _overview(user: dict, lang: str = "ru") -> str:
    from .. import i18n

    def _(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    contacts = sos.contacts_of(user)
    lines = [f"<b>{_('sos.overview', '🆘 Экстренная помощь')}</b>", ""]

    if not contacts:
        lines.append(_(
            "sos.no_contacts",
            "Доверенные контакты не заданы. Добавьте человека, которому уйдёт "
            "ваша геопозиция, если вы нажмёте кнопку SOS.",
        ))
    else:
        lines.append(f"<b>{_('sos.contacts', 'Доверенные контакты')}:</b>")
        for contact in contacts:
            state = (
                _("sos.ready", "готов принимать сигнал") if contact.confirmed
                else _("sos.pending", "не подтверждён — не открывал бота")
            )
            mark = "✅" if contact.confirmed else "⏳"
            lines.append(f"{mark} {esc(contact.title)} — <i>{state}</i>")

        if not sos.confirmed_contacts(user):
            lines.append("")
            lines.append(_(
                "sos.none_confirmed",
                "⚠️ Ни один контакт не подтверждён. Telegram не даёт боту писать "
                "первым — контакт должен открыть бота по вашей ссылке. Пока этого "
                "не произошло, сигнал уйдёт администраторам системы.",
            ))

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
    await safe_edit(call, _overview(user, i18n.language_of(user)), _menu(user))


@router.message(Command("sos"))
async def cmd_sos(message: Message, state: FSMContext, user: dict) -> None:
    if not features.enabled("sos"):
        await message.answer("Функция SOS отключена.")
        return
    await state.clear()
    await message.answer(_overview(user, i18n.language_of(user)), reply_markup=_menu(user))


# --------------------------------------------------------------------------
#  Контакты
# --------------------------------------------------------------------------

def _picker_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка выбора контакта средствами самого Telegram.

    Это надёжнее пересылки: при закрытых настройках приватности пересланное
    сообщение не содержит идентификатора отправителя, а встроенный выбор
    возвращает его всегда.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text="👤 Выбрать контакт",
                request_users=KeyboardButtonRequestUsers(
                    request_id=1,
                    user_is_bot=False,
                    max_quantity=1,
                    request_name=True,
                    request_username=True,
                ),
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Или пришлите числовой ID",
    )


@router.callback_query(F.data == "sos:add")
async def ask_contact(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(Form.sos_contact)
    await safe_edit(
        call,
        "➕ <b>Доверенный контакт</b>\n\n"
        "Нажмите кнопку <b>«Выбрать контакт»</b> под полем ввода — Telegram "
        "предложит выбрать человека из списка.\n\n"
        "Другие способы: переслать сюда его сообщение или прислать "
        "<b>числовой ID</b> (узнать можно у @userinfobot).\n\n"
        "После добавления вы получите ссылку-приглашение: контакт откроет её "
        "и нажмёт «Старт». Без этого шага Telegram не позволит боту "
        "написать ему первым.\n\n<i>/cancel — отмена.</i>",
        back_kb("sos:menu", "Отмена"),
    )
    await call.message.answer(
        "Выберите способ:", reply_markup=_picker_keyboard()
    )


def _extract_contact(message: Message) -> tuple[str, str]:
    """Достаёт идентификатор контакта из сообщения любым доступным способом."""
    # 1. Встроенный выбор Telegram — самый надёжный путь
    shared = getattr(message, "users_shared", None)
    if shared is not None:
        people = getattr(shared, "users", None) or getattr(shared, "user_ids", None) or []
        for person in people:
            person_id = getattr(person, "user_id", None) or person
            if person_id:
                name = " ".join(
                    part for part in (
                        getattr(person, "first_name", "") or "",
                        getattr(person, "last_name", "") or "",
                    ) if part
                ).strip()
                username = getattr(person, "username", "") or ""
                title = name or (f"@{username}" if username else f"ID {person_id}")
                return str(person_id), title

    # 2. Пересланное сообщение. В aiogram 3.7+ поле forward_from удалено:
    #    сведения об источнике переехали в forward_origin.
    origin = getattr(message, "forward_origin", None)
    sender = getattr(origin, "sender_user", None) if origin is not None else None
    if sender is None:
        sender = getattr(message, "forward_from", None)   # совместимость со старыми версиями
    if sender is not None:
        title = getattr(sender, "full_name", "") or getattr(sender, "username", "") or ""
        return str(sender.id), title or f"ID {sender.id}"

    # 3. Скрытый отправитель: имя есть, идентификатора нет
    if origin is not None and getattr(origin, "sender_user_name", None):
        return "", str(origin.sender_user_name)

    # 4. Числовой идентификатор текстом
    text = (message.text or "").strip()
    if text.isdigit() and len(text) >= 5:
        return text, f"ID {text}"

    return "", ""


@router.message(Form.sos_contact)
async def save_contact(message: Message, state: FSMContext, user: dict) -> None:
    if (message.text or "").startswith("/"):
        return

    key, title = _extract_contact(message)

    if not key:
        hint = (
            "❌ Не удалось определить пользователя.\n\n"
            "Нажмите кнопку <b>«Выбрать контакт»</b> под полем ввода — это "
            "работает всегда."
        )
        if title:
            hint += (
                f"\n\n<i>У пользователя {esc(title)} закрыта пересылка "
                "в настройках приватности, поэтому его идентификатор скрыт.</i>"
            )
        else:
            hint += "\n\nИли пришлите числовой ID — узнать можно у @userinfobot."
        await message.answer(hint, reply_markup=_picker_keyboard())
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
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(invite, reply_markup=back_kb("sos:menu", "◀️ К настройкам"))


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
    await safe_edit(call, _overview(user, i18n.language_of(user)), _menu(user))


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
