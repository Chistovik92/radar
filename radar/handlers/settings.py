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

from .. import keyboards, roles, storage
from ..matching import CATEGORY_TITLES
from ..states import Form
from ..tg import back_kb, safe_edit

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


@router.callback_query(F.data == "set:weather")
async def weather_menu(call: CallbackQuery) -> None:
    await call.answer()
    await safe_edit(
        call,
        "⏱ <b>Режим погоды</b>\nВыберите интервал или задайте своё значение.",
        keyboards.weather_menu(),
    )


@router.callback_query(F.data.startswith("set:wth:"))
async def set_interval(call: CallbackQuery, user: dict[str, Any]) -> None:
    try:
        minutes = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return
    user["weather_mode"] = "interval"
    user["weather_interval"] = minutes
    user["last_weather"] = 0
    await storage.save()
    await call.answer("Погода отключена" if minutes == 0 else f"Интервал: {minutes} мин")
    await safe_edit(call, "⚙️ <b>Оповещения</b>", keyboards.settings_menu(user))


@router.callback_query(F.data == "set:wthtime")
async def ask_time(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await safe_edit(
        call,
        "⏰ Введите время в формате <code>HH:MM</code> (например, 08:30):",
        back_kb("set:weather", "Отмена"),
    )
    await state.set_state(Form.weather_time)


@router.message(Form.weather_time)
async def save_time(message: Message, state: FSMContext, user: dict[str, Any]) -> None:
    value = (message.text or "").strip()
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
        await message.answer("❌ Неверный формат. Пример: <code>08:30</code>. /cancel — отмена.")
        return
    hour, minute = value.split(":")
    value = f"{int(hour):02d}:{minute}"
    user["weather_mode"] = "time"
    user["weather_time"] = value
    user["last_fixed_date"] = ""
    await storage.save()
    await state.clear()
    await message.answer(
        f"✅ Погода будет приходить ежедневно в <b>{value}</b>.",
        reply_markup=keyboards.settings_menu(user),
    )


@router.callback_query(F.data == "set:wthint")
async def ask_interval(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await safe_edit(
        call,
        "⏱ Введите интервал: <code>45</code> (минут) или <code>2ч</code> (часа):",
        back_kb("set:weather", "Отмена"),
    )
    await state.set_state(Form.weather_interval)


@router.message(Form.weather_interval)
async def save_interval(message: Message, state: FSMContext, user: dict[str, Any]) -> None:
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
    user["weather_mode"] = "interval"
    user["weather_interval"] = minutes
    user["last_weather"] = 0
    await storage.save()
    await state.clear()
    await message.answer(
        f"✅ Интервал: <b>{minutes} мин</b>.", reply_markup=keyboards.settings_menu(user)
    )
