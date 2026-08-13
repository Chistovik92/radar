"""Журналы в интерфейсе бота. Доступно только суперадминистратору.

Журналы содержат идентификаторы пользователей, адреса и внутренние ошибки,
поэтому выдаются исключительно владельцу системы — ни администраторам,
ни модераторам.
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
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import logs, roles
from ..textutils import esc, split_text
from ..tg import back_kb, safe_edit, send_html

log = logging.getLogger("radar.handlers.logs")
router = Router(name="logs")

KIND_TITLES = {
    "bot": "🤖 Журналы бота",
    "installer": "📦 Журналы установки",
    "doctor": "🩺 Отчёты диагностики",
    "other": "📄 Прочее",
}


def _menu() -> InlineKeyboardMarkup:
    grouped = logs.by_kind()
    rows: list[list[InlineKeyboardButton]] = []

    for kind, title in KIND_TITLES.items():
        items = grouped.get(kind)
        if not items:
            continue
        rows.append([
            InlineKeyboardButton(
                text=f"{title} ({len(items)})", callback_data=f"log:kind:{kind}"
            )
        ])

    if grouped:
        rows.append([
            InlineKeyboardButton(text="📥 Скачать всё архивом", callback_data="log:all"),
        ])
        rows.append([
            InlineKeyboardButton(text="🧹 Очистить журналы", callback_data="log:purge"),
        ])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _overview() -> str:
    items = logs.collect()
    if not items:
        return (
            "📋 <b>Журналы</b>\n\nПока пусто. Журнал бота появится после запуска, "
            "журнал установки — после ближайшего обновления."
        )

    total = logs.total_size()
    lines = [
        "📋 <b>Журналы</b>",
        f"Файлов: <b>{len(items)}</b>, общий объём: <b>{total // 1024} КБ</b>",
        "",
    ]
    for item in items[:12]:
        lines.append(
            f"• <code>{esc(item.name)}</code> — {item.size_human}, {item.age_human}"
        )
    if len(items) > 12:
        lines.append(f"…и ещё {len(items) - 12}")
    return "\n".join(lines)


def _files_menu(kind: str) -> InlineKeyboardMarkup:
    items = logs.by_kind().get(kind, [])
    rows = [
        [
            InlineKeyboardButton(
                text=f"📄 {item.name[:38]} ({item.size_human})",
                callback_data=f"log:get:{item.name}",
            )
        ]
        for item in items[:15]
    ]
    rows.append([
        InlineKeyboardButton(text="📥 Скачать группой", callback_data=f"log:pack:{kind}"),
        InlineKeyboardButton(text="🧹 Удалить группу", callback_data=f"log:clear:{kind}"),
    ])
    rows.append([InlineKeyboardButton(text="◀️ К журналам", callback_data="log:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------
#  Команды
# --------------------------------------------------------------------------

@router.message(Command("logs"))
async def cmd_logs(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Журналы доступны только суперадминистратору.")
        return
    await message.answer(_overview(), reply_markup=_menu())


@router.message(Command("logtail"))
async def cmd_logtail(message: Message, role: str) -> None:
    """Последние строки журнала бота прямо в чат — без скачивания файла."""
    if not roles.is_superadmin(role):
        return
    items = logs.by_kind().get("bot", [])
    if not items:
        await message.answer("Журнал бота ещё не создан.")
        return

    parts = (message.text or "").split()
    try:
        count = min(200, max(10, int(parts[1]))) if len(parts) > 1 else 60
    except ValueError:
        count = 60

    text = logs.tail(items[0], count)
    for chunk in split_text(f"<pre>{esc(text)}</pre>"):
        await message.answer(chunk)


@router.message(Command("logclear"))
async def cmd_logclear(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        return
    removed, freed = logs.purge()
    await message.answer(
        f"🧹 Удалено файлов: <b>{removed}</b>, освобождено <b>{freed // 1024} КБ</b>.\n"
        "<i>Текущий журнал бота сохранён — он открыт на запись.</i>"
    )


# --------------------------------------------------------------------------
#  Меню
# --------------------------------------------------------------------------

@router.callback_query(F.data == "log:list")
async def show_logs(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _overview(), _menu())


@router.callback_query(F.data.startswith("log:kind:"))
async def show_kind(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    kind = call.data.split(":")[2]
    items = logs.by_kind().get(kind, [])
    await call.answer()
    lines = [KIND_TITLES.get(kind, kind), ""]
    lines += [
        f"• <code>{esc(item.name)}</code> — {item.size_human}, {item.age_human}"
        for item in items[:15]
    ] or ["— пусто —"]
    await safe_edit(call, "\n".join(lines), _files_menu(kind))


@router.callback_query(F.data.startswith("log:get:"))
async def send_one(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    name = call.data.split(":", 2)[2]
    item = logs.find(name)
    if item is None:
        await call.answer("Файл не найден.", show_alert=True)
        return

    await call.answer("Готовлю файл…")
    payload = logs.read_bytes(item)
    if payload is None:
        await send_html(call.message.chat.id, "❌ Не удалось прочитать файл.")
        return
    await call.message.answer_document(
        BufferedInputFile(payload, filename=item.name),
        caption=f"📄 <code>{esc(item.name)}</code> — {item.size_human}",
        reply_markup=back_kb("log:list", "◀️ К журналам"),
    )


@router.callback_query(F.data.startswith("log:pack:"))
async def send_group(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    kind = call.data.split(":")[2]
    await _send_archive(call, {kind})


@router.callback_query(F.data == "log:all")
async def send_all(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await _send_archive(call, None)


async def _send_archive(call: CallbackQuery, kinds: set[str] | None) -> None:
    await call.answer("Собираю архив…")
    result = logs.archive(kinds)
    if result is None:
        await send_html(call.message.chat.id, "Журналов для выгрузки нет.")
        return
    payload, filename, count = result
    await call.message.answer_document(
        BufferedInputFile(payload, filename=filename),
        caption=(
            f"📥 <b>Журналы системы</b>\nФайлов: {count}, "
            f"размер архива: {len(payload) // 1024} КБ\n\n"
            "<i>Журналы контейнеров Docker сюда не входят — соберите их "
            "на сервере: <code>bash ~/radar_bot/collect-logs.sh</code></i>"
        ),
        reply_markup=back_kb("log:list", "◀️ К журналам"),
    )


@router.callback_query(F.data == "log:purge")
async def confirm_purge(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Удалить", callback_data="log:purgeok"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="log:list"),
            ]
        ]
    )
    await safe_edit(
        call,
        "🧹 <b>Очистка журналов</b>\n\nБудут удалены все файлы, кроме текущего "
        "журнала бота — он открыт на запись.\n\nПродолжить?",
        kb,
    )


@router.callback_query(F.data == "log:purgeok")
async def do_purge(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    removed, freed = logs.purge()
    await call.answer(f"Удалено файлов: {removed}")
    await safe_edit(
        call,
        f"🧹 Удалено: <b>{removed}</b>, освобождено <b>{freed // 1024} КБ</b>.\n\n"
        + _overview(),
        _menu(),
    )


@router.callback_query(F.data.startswith("log:clear:"))
async def clear_kind(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    kind = call.data.split(":")[2]
    removed, freed = logs.purge({kind})
    await call.answer(f"Удалено файлов: {removed}")
    await safe_edit(call, _overview(), _menu())
