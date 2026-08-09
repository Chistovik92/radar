"""Пользователи: список, карточка, смена роли, удаление, правка локаций и настроек."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from .. import keyboards, roles, storage
from ..textutils import esc
from ..tg import back_kb, bot, safe_edit, send_html
from .locations import locations_text

router = Router(name="users")

PAGE_SIZE = 8


def _page(page: int) -> tuple[list[tuple[str, str, int]], int]:
    records = sorted(
        storage.users().items(),
        key=lambda item: (-roles.level(item[1].get("role")), item[0]),
    )
    pages = max(1, (len(records) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = records[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    items = [
        (uid, user.get("role", "user"), len(user.get("locs") or []))
        for uid, user in chunk
    ]
    return items, pages


@router.callback_query(F.data.startswith("usr:list:"))
async def list_users(call: CallbackQuery, role: str) -> None:
    if not roles.is_moderator(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    try:
        page = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        page = 0
    items, pages = _page(page)
    page = max(0, min(page, pages - 1))
    lines = [f"👥 <b>Пользователи</b> — всего {len(storage.users())} (стр. {page + 1}/{pages})"]
    for uid, user_role, count in items:
        user = storage.get_user(uid) or {}
        username = f" @{esc(user.get('username'))}" if user.get("username") else ""
        lines.append(f"<code>{uid}</code>{username} — {roles.title(user_role)}, локаций: {count}")
    lines.append("\n<i>Нажмите на пользователя, чтобы открыть карточку.</i>")
    await safe_edit(call, "\n".join(lines), keyboards.users_page(items, page, pages))


def _card_text(uid: str) -> str:
    user = storage.get_user(uid) or {}
    settings = user.get("settings") or {}
    active = ", ".join(key for key, value in settings.items() if value) or "нет"
    username = f"@{esc(user.get('username'))}" if user.get("username") else "—"
    return "\n".join(
        [
            f"👤 <b>Пользователь</b> <code>{uid}</code>",
            f"Ник: {username}",
            f"Роль: {roles.title(user.get('role'))}",
            f"Локаций: <b>{len(user.get('locs') or [])}</b>",
            f"Категории оповещений: {esc(active)}",
            f"Погода: {esc(keyboards.weather_label(user))}",
        ]
    )


@router.callback_query(F.data.startswith("usr:card:"))
async def card(call: CallbackQuery, role: str) -> None:
    if not roles.is_moderator(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call, _card_text(target), keyboards.user_card(target, user.get("role", "user"), role)
    )


@router.callback_query(F.data.startswith("usr:locs:"))
async def user_locations(call: CallbackQuery, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_edit_user(role, user.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        locations_text(user, owner_label=f"<code>{target}</code>"),
        keyboards.locations_menu(user.get("locs") or [], owner=target),
    )


@router.callback_query(F.data.startswith("usr:sets:"))
async def user_settings(call: CallbackQuery, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_edit_user(role, user.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        f"⚙️ <b>Оповещения пользователя</b> <code>{target}</code>",
        keyboards.settings_menu(user, target),
    )


@router.callback_query(F.data.startswith("usr:role:"))
async def change_role(call: CallbackQuery, role: str) -> None:
    parts = call.data.split(":")
    target, new_role = parts[2], parts[3]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if target == str(call.from_user.id):
        await call.answer("Нельзя менять роль самому себе.", show_alert=True)
        return
    if not roles.can_assign(role, user.get("role"), new_role):
        await call.answer("Недостаточно прав для этой роли.", show_alert=True)
        return

    user["role"] = new_role
    await storage.save()
    await call.answer(f"Роль изменена: {new_role}")
    await safe_edit(call, _card_text(target), keyboards.user_card(target, new_role, role))
    await send_html(
        target, f"ℹ️ Ваша роль в системе «Радар» изменена на {roles.title(new_role)}."
    )


@router.callback_query(F.data.startswith("usr:del:"))
async def ask_delete(call: CallbackQuery, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_delete_user(role, user.get("role")):
        await call.answer("Удаление доступно администраторам.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        f"⚠️ Удалить пользователя <code>{target}</code> "
        f"({roles.title(user.get('role'))}) вместе со всеми локациями?",
        keyboards.confirm("usr:delok", target, f"usr:card:{target}"),
    )


@router.callback_query(F.data.startswith("usr:delok:"))
async def confirm_delete(call: CallbackQuery, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_delete_user(role, user.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    storage.users().pop(target, None)
    await storage.save()
    await call.answer("Пользователь удалён")
    items, pages = _page(0)
    await safe_edit(
        call,
        f"✅ Пользователь <code>{target}</code> удалён.",
        keyboards.users_page(items, 0, pages),
    )


@router.callback_query(F.data == "usr:invite")
async def invite(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    me = await bot.get_me()
    await safe_edit(
        call,
        "🔗 <b>Инвайт-ссылка</b>\n"
        f"https://t.me/{me.username}?start=join\n\n"
        "<i>Перешедший по ней получает роль «Пользователь».</i>",
        back_kb("menu:admin", "◀️ Назад"),
    )
