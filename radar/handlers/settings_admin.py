"""Настройки системы для суперадминистратора: ключи доступа и проверка ИИ.

Здесь же запускается сравнение провайдеров: раньше это был отдельный скрипт
в `bench/`, который на сервере никто не запускал. Теперь тот же набор
тест-кейсов прогоняется прямо из бота по кнопке.
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
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import ai, aibench, config, roles, secrets
from ..states import Form
from ..textutils import esc, split_text
from ..tg import back_kb, safe_edit, send_html

log = logging.getLogger("radar.handlers.settings_admin")
router = Router(name="admin_settings")


# --------------------------------------------------------------------------
#  Ключи доступа
# --------------------------------------------------------------------------

def _groups_menu() -> InlineKeyboardMarkup:
    rows = []
    for group in secrets.GROUPS:
        items = secrets.by_group()[group]
        rows.append([
            InlineKeyboardButton(
                text=f"{group} — {secrets.filled(group)}/{len(items)}",
                callback_data=f"key:group:{group}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="🧪 Сравнить провайдеров ИИ", callback_data="bench:menu")
    ])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _group_menu(group: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if secrets.get(item.key) else '➕'} {item.title}",
                callback_data=f"key:edit:{item.key}",
            )
        ]
        for item in secrets.by_group().get(group, [])
    ]
    rows.append([InlineKeyboardButton(text="◀️ К разделам", callback_data="key:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _overview() -> str:
    lines = [
        "🔑 <b>Ключи доступа</b>",
        f"Заполнено: <b>{secrets.filled()}</b> из {len(secrets.SETTINGS)}",
        "",
    ]
    if not secrets.writable():
        lines.append(
            "⚠️ Файл <code>.env</code> недоступен на запись — сохранить "
            "значения из бота не получится. Проверьте права на файл."
        )
        lines.append("")
    lines.append(
        "<i>Ключи хранятся в .env рядом с ботом. Значения показаны "
        "замаскированными.</i>"
    )
    return "\n".join(lines)


@router.message(Command("keys"))
async def cmd_keys(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Ключи доступа настраивает суперадминистратор.")
        return
    await message.answer(_overview(), reply_markup=_groups_menu())


@router.callback_query(F.data == "key:list")
async def show_groups(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, _overview(), _groups_menu())


@router.callback_query(F.data.startswith("key:group:"))
async def show_group(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    group = call.data.split(":", 2)[2]
    await call.answer()

    lines = [f"🔑 <b>{esc(group)}</b>", ""]
    for item in secrets.by_group().get(group, []):
        lines.append(f"<b>{esc(item.title)}</b> — {esc(secrets.display(item))}")
        lines.append(f"<i>{esc(item.hint)}</i>")
        if item.where:
            lines.append(f"<i>Получить: {esc(item.where)}</i>")
        if item.restart:
            lines.append("<i>Применится после перезапуска контейнера.</i>")
        lines.append("")
    await safe_edit(call, "\n".join(lines).strip(), _group_menu(group))


@router.callback_query(F.data.startswith("key:edit:"))
async def ask_value(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    key = call.data.split(":", 2)[2]
    setting = secrets.BY_KEY.get(key)
    if setting is None:
        await call.answer("Неизвестный параметр.", show_alert=True)
        return

    await call.answer()
    await state.set_state(Form.secret_value)
    await state.update_data(secret_key=key)

    lines = [
        f"🔑 <b>{esc(setting.title)}</b>",
        f"Сейчас: {esc(secrets.display(setting))}",
        "",
        esc(setting.hint),
    ]
    if setting.where:
        lines.append(f"\n<b>Где взять:</b> {esc(setting.where)}")
    if setting.restart:
        lines.append("\n⚠️ <i>Применится после перезапуска контейнера.</i>")
    lines.append("\nПришлите значение одним сообщением.")
    lines.append("<i>«-» очистит поле. /cancel — отмена.</i>")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"key:group:{setting.group}")]
    ])
    await safe_edit(call, "\n".join(lines), kb)


@router.message(Form.secret_value)
async def save_value(message: Message, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await state.clear()
        return

    data = await state.get_data()
    key = data.get("secret_key") or ""
    setting = secrets.BY_KEY.get(key)
    value = (message.text or "").strip()

    if value.startswith("/"):
        return
    if setting is None:
        await state.clear()
        await message.answer("❌ Параметр не найден.")
        return

    await state.clear()

    # Само сообщение с ключом лучше убрать из переписки
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass

    if value == "-":
        secrets.clear(key)
        await message.answer(
            f"🧹 <b>{esc(setting.title)}</b> очищено.",
            reply_markup=back_kb(f"key:group:{setting.group}", "◀️ Назад"),
        )
        return

    if not secrets.write(key, value):
        await message.answer(
            "❌ Не удалось записать в .env — проверьте права на файл.",
            reply_markup=back_kb("key:list", "◀️ Назад"),
        )
        return

    note = (
        "\n\n⚠️ <i>Изменение применится после перезапуска:</i> "
        "<code>docker compose restart</code>"
        if setting.restart else "\n\n<i>Применяется сразу.</i>"
    )
    await message.answer(
        f"✅ <b>{esc(setting.title)}</b> сохранено: {esc(secrets.display(setting))}{note}",
        reply_markup=back_kb(f"key:group:{setting.group}", "◀️ Назад"),
    )


# --------------------------------------------------------------------------
#  Сравнение провайдеров ИИ
# --------------------------------------------------------------------------

def _bench_menu() -> InlineKeyboardMarkup:
    ready = aibench.configured_providers()
    rows = [[
        InlineKeyboardButton(
            text=f"▶️ Запустить проверку ({len(ready)} провайдеров)",
            callback_data="bench:run",
        )
    ]]
    if aibench.last_report() is not None:
        rows.append([
            InlineKeyboardButton(text="📊 Последний отчёт", callback_data="bench:last")
        ])
    rows.append([InlineKeyboardButton(text="◀️ К ключам", callback_data="key:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _bench_overview() -> str:
    ready = aibench.configured_providers()
    lines = [
        "🧪 <b>Сравнение провайдеров ИИ</b>",
        "",
        "Одинаковые сообщения городских служб прогоняются через все "
        "провайдеры, у которых задан ключ. Сравнивается точность разбора: "
        "категории, улицы и дома, отсутствие ложных тревог.",
        "",
    ]
    if ready:
        lines.append("<b>Готовы к проверке:</b>")
        lines += [f"• {esc(item.title)}" for item in ready]
    else:
        lines.append(
            "⚠️ Ни у одного провайдера не задан ключ. Добавьте их "
            "в разделе «ИИ»."
        )
    lines.append("")
    lines.append(
        "<i>Важно: смотрите на колонку «военные темы». Провайдер, который "
        "срезает сообщения о БПЛА, для оповещений непригоден, каким бы "
        "точным он ни был в остальном.</i>"
    )
    return "\n".join(lines)


@router.message(Command("bench"))
async def cmd_bench(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Проверка провайдеров доступна суперадминистратору.")
        return
    await message.answer(_bench_overview(), reply_markup=_bench_menu())


@router.callback_query(F.data == "bench:menu")
async def bench_menu(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _bench_overview(), _bench_menu())


@router.callback_query(F.data == "bench:last")
async def bench_last(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    report = aibench.last_report()
    if report is None:
        await call.answer("Отчётов ещё нет.", show_alert=True)
        return
    await call.answer()
    for chunk in split_text(aibench.render(report)):
        await send_html(call.message.chat.id, chunk)


@router.callback_query(F.data == "bench:run")
async def bench_run(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    ready = aibench.configured_providers()
    if not ready:
        await call.answer("Нет провайдеров с ключами.", show_alert=True)
        return
    if aibench.is_running():
        await call.answer("Проверка уже идёт.", show_alert=True)
        return

    await call.answer("Запускаю проверку…")
    notice = await call.message.answer(
        f"🧪 Проверяю {len(ready)} провайдеров…\n"
        "<i>Займёт несколько минут: запросы идут с паузами.</i>"
    )

    async def progress(done: int, total: int, current: str) -> None:
        try:
            await notice.edit_text(
                f"🧪 Проверка: <b>{done}/{total}</b>\n<i>сейчас: {esc(current)}</i>"
            )
        except Exception:  # noqa: BLE001
            pass

    try:
        report = await aibench.run(progress=progress)
    except Exception as exc:  # noqa: BLE001
        log.exception("Проверка провайдеров не удалась")
        await notice.edit_text(f"❌ Проверка не удалась: {esc(exc)}")
        return

    try:
        await notice.delete()
    except Exception:  # noqa: BLE001
        pass

    for chunk in split_text(aibench.render(report)):
        await send_html(call.message.chat.id, chunk)
    await send_html(
        call.message.chat.id,
        "<i>Провайдер для разбора новостей задаётся переменной "
        "GEMINI_MODEL_ANALYSIS; смена провайдера по умолчанию появится "
        "в версии 4.3.</i>",
        back_kb("bench:menu", "◀️ Назад"),
    )
