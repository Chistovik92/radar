"""Управление возможностями системы. Доступно только суперадминистратору.

Флаги переключаются на живой системе: изменение сразу попадает в память
и в базу, перезапуск контейнера не нужен.
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

from .. import features, roles
from ..db import repo
from ..textutils import esc
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.features")
router = Router(name="features")


def _menu(group: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if group is None:
        for name in features.GROUPS:
            items = features.by_group()[name]
            active = sum(1 for flag in items if features.enabled(flag.key))
            rows.append([
                InlineKeyboardButton(
                    text=f"{name} — {active}/{len(items)}",
                    callback_data=f"feat:group:{name}",
                )
            ])
        rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    for flag in features.by_group().get(group, []):
        if flag.locked:
            mark = "🔒"
        else:
            mark = "✅" if features.enabled(flag.key) else "❌"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {flag.title}",
                callback_data=f"feat:toggle:{flag.key}:{group}",
            )
        ])
    rows.append([InlineKeyboardButton(text="◀️ К разделам", callback_data="feat:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _group_text(group: str) -> str:
    lines = [f"⚙️ <b>{esc(group)}</b>", ""]
    for flag in features.by_group().get(group, []):
        state = "🔒 всегда включено" if flag.locked else (
            "✅ включено" if features.enabled(flag.key) else "❌ выключено"
        )
        since = f" <i>(с {flag.since})</i>" if flag.since else ""
        lines.append(f"<b>{esc(flag.title)}</b>{since} — {state}")
        lines.append(f"<i>{esc(flag.description)}</i>")
        lines.append("")
    return "\n".join(lines).strip()


@router.message(Command("features"))
async def cmd_features(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Управление возможностями доступно суперадминистратору.")
        return
    active = sum(1 for flag in features.FLAGS if features.enabled(flag.key))
    await message.answer(
        f"⚙️ <b>Возможности системы</b>\nВключено {active} из {len(features.FLAGS)}.\n\n"
        "<i>Изменения применяются сразу, перезапуск не нужен.</i>",
        reply_markup=_menu(),
    )


@router.callback_query(F.data == "feat:list")
async def show_groups(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    active = sum(1 for flag in features.FLAGS if features.enabled(flag.key))
    await safe_edit(
        call,
        f"⚙️ <b>Возможности системы</b>\nВключено {active} из {len(features.FLAGS)}.",
        _menu(),
    )


@router.callback_query(F.data.startswith("feat:group:"))
async def show_group(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    group = call.data.split(":", 2)[2]
    await call.answer()
    await safe_edit(call, _group_text(group), _menu(group))


@router.callback_query(F.data.startswith("feat:toggle:"))
async def toggle(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    parts = call.data.split(":")
    key, group = parts[2], parts[3]

    flag = features.resolve(key)
    if flag is None:
        await call.answer("Неизвестная возможность.", show_alert=True)
        return
    if flag.locked:
        await call.answer("Это ядро системы, выключить нельзя.", show_alert=True)
        return

    value = not features.enabled(flag.key)
    features.set_local(flag.key, value)
    await repo.set_feature(flag.key, value, call.from_user.id)

    if flag.key == "maintenance":
        # Тумблер, останавливающий рассылку оповещений, не должен выглядеть
        # как остальные: последствия видны не сразу, а по тишине.
        await call.answer(
            "🛠 Работы начаты: оповещения остановлены, "
            "бот отвечает всем, кроме вас."
            if value else
            "✅ Работы завершены: цикл возобновлён.",
            show_alert=True,
        )
        log.warning(
            "Режим обслуживания %s пользователем %s",
            "включён" if value else "выключен", call.from_user.id,
        )
    else:
        await call.answer(f"{flag.title}: {'включено' if value else 'выключено'}")
    await safe_edit(call, _group_text(group), _menu(group))
