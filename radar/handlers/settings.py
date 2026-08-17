"""Настройки: категории оповещений и режим отправки погоды."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import features, keyboards, roles, storage
from ..matching import CATEGORY_TITLES
from ..states import Form
from ..tg import back_kb, safe_edit, send_html

router = Router(name="settings")

@router.callback_query(F.data.startswith("set:toggle:"))
async def toggle_category(call: CallbackQuery, user: dict[str, Any], role: str) -> None:
    parts = call.data.split(":")
    key = parts[2]
    target_id = parts[3] if len(parts) > 3 else ""
    if key not in CATEGORY_TITLES:
        await call.answer()
        return

    subject = user
    if target_id:
        subject = storage.get_user(target_id)
        if subject is None:
            await call.answer("Пользователь не найден.", show_alert=True)
            return
        if not roles.can_edit_user(role, subject.get("role")):
            await call.answer("Недостаточно прав.", show_alert=True)
            return

    settings = subject.setdefault("settings", storage.default_settings())
    settings[key] = not settings.get(key, True)
    await storage.save()
    await call.answer("Включено" if settings[key] else "Выключено")
    try:
        await call.message.edit_reply_markup(
            reply_markup=keyboards.settings_menu(subject, target_id)
        )
    except TelegramBadRequest:
        pass


def _subject(call: CallbackQuery, user: dict[str, Any], role: str,
             target: str) -> dict[str, Any] | None:
    """Чьи настройки правим: свои или чужие (для администрации)."""
    if not target:
        return user
    other = storage.get_user(target)
    if other is None or not roles.can_edit_user(role, other.get("role")):
        return None
    return other


@router.callback_query(F.data == "set:weather")
async def weather_menu(call: CallbackQuery) -> None:
    await call.answer()
    await safe_edit(
        call,
        "⏱ <b>Режим погоды</b>\nВыберите интервал или задайте своё значение.",
        keyboards.weather_menu(),
    )


@router.callback_query(F.data.startswith("usr:wth:"))
async def weather_for_user(call: CallbackQuery, role: str) -> None:
    """Администрация задаёт пользователю режим погоды так же, как он сам."""
    target = call.data.split(":")[2]
    other = storage.get_user(target)
    if other is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_edit_user(role, other.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    await call.answer()
    locations = len(other.get("locs") or [])
    await safe_edit(
        call,
        f"🌤 <b>Погода пользователя</b> <code>{target}</code>\n"
        f"Сейчас: {keyboards.weather_label(other)}, локаций: {locations}\n\n"
        "<i>Настройка применится так же, как если бы её сделал сам пользователь.</i>",
        keyboards.weather_menu(target),
    )


@router.callback_query(F.data.startswith("set:wth:"))
async def set_interval(call: CallbackQuery, user: dict[str, Any], role: str) -> None:
    parts = call.data.split(":")
    try:
        minutes = int(parts[2])
    except (IndexError, ValueError):
        await call.answer()
        return
    target = parts[3] if len(parts) > 3 else ""

    subject = _subject(call, user, role, target)
    if subject is None:
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    subject["weather_mode"] = "interval"
    subject["weather_interval"] = minutes
    subject["last_weather"] = 0
    await storage.save(target or call.from_user.id)
    await call.answer("Погода отключена" if minutes == 0 else f"Интервал: {minutes} мин")

    if target:
        await send_html(
            target,
            "🌤 Администратор изменил режим погоды: "
            f"<b>{keyboards.weather_label(subject)}</b>.",
        )
        await safe_edit(
            call,
            f"✅ Погода пользователя <code>{target}</code>: "
            f"{keyboards.weather_label(subject)}",
            keyboards.weather_menu(target),
        )
    else:
        await safe_edit(call, "⚙️ <b>Оповещения</b>", keyboards.settings_menu(user))


@router.callback_query(F.data.startswith("set:wthtime"))
async def ask_time(call: CallbackQuery, state: FSMContext, role: str) -> None:
    parts = call.data.split(":")
    target = parts[2] if len(parts) > 2 else ""
    if target and not roles.can_edit_user(role, (storage.get_user(target) or {}).get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    await call.answer()
    await state.update_data(weather_target=target)
    await state.set_state(Form.weather_time)
    who = f" для <code>{target}</code>" if target else ""
    await safe_edit(
        call,
        f"⏰ Введите время{who} в формате <code>HH:MM</code> (например, 08:30):",
        back_kb(f"usr:wth:{target}" if target else "set:weather", "Отмена"),
    )


@router.message(Form.weather_time)
async def save_time(message: Message, state: FSMContext, user: dict[str, Any],
                    role: str) -> None:
    value = (message.text or "").strip()
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
        await message.answer("❌ Неверный формат. Пример: <code>08:30</code>. /cancel — отмена.")
        return
    hour, minute = value.split(":")
    value = f"{int(hour):02d}:{minute}"

    target = (await state.get_data()).get("weather_target") or ""
    subject = user
    if target:
        subject = storage.get_user(target)
        if subject is None or not roles.can_edit_user(role, subject.get("role")):
            await state.clear()
            await message.answer("❌ Недостаточно прав или пользователь не найден.")
            return

    subject["weather_mode"] = "time"
    subject["weather_time"] = value
    subject["last_fixed_date"] = ""
    await storage.save(target or message.from_user.id)
    await state.clear()

    if target:
        await send_html(target, f"🌤 Администратор установил доставку погоды в <b>{value}</b>.")
        await message.answer(
            f"✅ Пользователю <code>{target}</code> погода будет приходить в <b>{value}</b>.",
            reply_markup=back_kb(f"usr:card:{target}", "◀️ К пользователю"),
        )
    else:
        await message.answer(
            f"✅ Погода будет приходить ежедневно в <b>{value}</b>.",
            reply_markup=keyboards.settings_menu(user),
        )


@router.callback_query(F.data.startswith("set:wthint"))
async def ask_interval(call: CallbackQuery, state: FSMContext, role: str) -> None:
    parts = call.data.split(":")
    target = parts[2] if len(parts) > 2 else ""
    if target and not roles.can_edit_user(role, (storage.get_user(target) or {}).get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    await call.answer()
    await state.update_data(weather_target=target)
    await state.set_state(Form.weather_interval)
    await safe_edit(
        call,
        "⏱ Введите интервал: <code>45</code> (минут) или <code>2ч</code> (часа):",
        back_kb(f"usr:wth:{target}" if target else "set:weather", "Отмена"),
    )


@router.message(Form.weather_interval)
async def save_interval(message: Message, state: FSMContext, user: dict[str, Any],
                        role: str) -> None:
    raw = (message.text or "").strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)(ч|h|мин|м|min|m)?", raw)
    if not match:
        await message.answer("❌ Введите число минут или, например, <code>2ч</code>.")
        return
    number = int(match.group(1))
    minutes = number * 60 if match.group(2) in ("ч", "h") else number
    if not 15 <= minutes <= 1440:
        await message.answer("❌ Допустимый интервал — от 15 минут до 24 часов.")
        return
    target = (await state.get_data()).get("weather_target") or ""
    subject = user
    if target:
        subject = storage.get_user(target)
        if subject is None or not roles.can_edit_user(role, subject.get("role")):
            await state.clear()
            await message.answer("❌ Недостаточно прав или пользователь не найден.")
            return

    subject["weather_mode"] = "interval"
    subject["weather_interval"] = minutes
    subject["last_weather"] = 0
    await storage.save(target or message.from_user.id)
    await state.clear()

    if target:
        await send_html(target, f"🌤 Администратор установил интервал погоды: <b>{minutes} мин</b>.")
        await message.answer(
            f"✅ Пользователю <code>{target}</code> интервал: <b>{minutes} мин</b>.",
            reply_markup=back_kb(f"usr:card:{target}", "◀️ К пользователю"),
        )
    else:
        await message.answer(
            f"✅ Интервал: <b>{minutes} мин</b>.", reply_markup=keyboards.settings_menu(user)
        )


# --------------------------------------------------------------------------
#  Вид сводки погоды и тихие часы
# --------------------------------------------------------------------------

@router.callback_query(F.data == "set:wformat")
async def weather_format(call: CallbackQuery, user: dict[str, Any]) -> None:
    if not features.enabled("weather_image"):
        await call.answer("Погода картинкой отключена.", show_alert=True)
        return

    await call.answer()
    current = "текстом" if user.get("weather_format") == "text" else "картинкой"
    await safe_edit(
        call,
        f"🖼 <b>Вид сводки погоды</b>\nСейчас: <b>{current}</b>\n\n"
        "Картинка нагляднее, но не прогрузится при ограничениях мобильного "
        "интернета — а это ровно тот случай, ради которого система "
        "и существует. Текст дойдёт всегда.",
        keyboards.weather_format_menu(),
    )


@router.callback_query(F.data.startswith("set:wfmt:"))
async def set_weather_format(call: CallbackQuery, user: dict[str, Any]) -> None:
    value = call.data.split(":")[2]
    if value not in ("text", "image"):
        await call.answer()
        return

    user["weather_format"] = value
    await storage.save(call.from_user.id)
    await call.answer("Текстом" if value == "text" else "Картинкой")
    await safe_edit(call, "⚙️ <b>Оповещения</b>", keyboards.settings_menu(user))


@router.callback_query(F.data == "set:quiet")
async def ask_quiet(call: CallbackQuery, state: FSMContext) -> None:
    if not features.enabled("quiet_hours"):
        await call.answer("Тихие часы отключены.", show_alert=True)
        return

    await call.answer()
    await state.set_state(Form.quiet_hours)
    await safe_edit(
        call,
        "🌙 <b>Тихие часы</b>\n\n"
        "Пришлите интервал, например <code>23:00-07:00</code>.\n"
        "«-» отключит тихие часы.\n\n"
        "<b>Военные угрозы и МЧС проходят всегда</b> — придерживаются "
        "только ЖКХ и погода.\n\n<i>/cancel — отмена.</i>",
        back_kb("menu:settings", "Отмена"),
    )


@router.message(Form.quiet_hours)
async def save_quiet(message: Message, state: FSMContext, user: dict[str, Any]) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    if text == "-":
        user["quiet_from"] = ""
        user["quiet_to"] = ""
        await storage.save(message.from_user.id)
        await state.clear()
        await message.answer(
            "✅ Тихие часы отключены.", reply_markup=keyboards.settings_menu(user)
        )
        return

    match = re.fullmatch(
        r"\s*([01]?\d|2[0-3]):([0-5]\d)\s*[-–—]\s*([01]?\d|2[0-3]):([0-5]\d)\s*", text
    )
    if not match:
        await message.answer(
            "❌ Формат: <code>23:00-07:00</code>. «-» отключит. /cancel — отмена."
        )
        return

    user["quiet_from"] = f"{int(match.group(1)):02d}:{match.group(2)}"
    user["quiet_to"] = f"{int(match.group(3)):02d}:{match.group(4)}"
    await storage.save(message.from_user.id)
    await state.clear()

    await message.answer(
        f"✅ Тихие часы: <b>{user['quiet_from']} — {user['quiet_to']}</b>\n"
        "<i>Военные угрозы и МЧС будут приходить в любое время.</i>",
        reply_markup=keyboards.settings_menu(user),
    )
