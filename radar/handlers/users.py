"""Пользователи: список, карточка, смена роли, удаление, правка локаций и настроек.

Переведено на английский в 4.9.9.3 (ROADMAP, п.20: «модераторские экраны —
кандидаты»). Два разных языка в одном файле, и путать их нельзя:

* экраны модератора — на языке **модератора** (`user` из middleware);
* уведомления, которые уходят человеку, чью карточку правят, — на языке
  **этого человека** (`storage.get_user(target)`): модератор-англичанин
  не должен сообщать русскоязычному пользователю по-английски.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import aiohttp
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import config, geocode, i18n, keyboards, roles, storage
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, bot, safe_edit, send_html
from .locations import locations_text

router = Router(name="users")

PAGE_SIZE = 8


def _t(who: dict | None, key: str, russian: str) -> str:
    """Строка на языке человека `who`."""
    return i18n.t(key, i18n.language_of(who), russian)


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


def _no_rights(user: dict | None) -> str:
    return _t(user, "users.no_rights", "Недостаточно прав.")


def _not_found(user: dict | None) -> str:
    return _t(user, "users.not_found", "Пользователь не найден.")


@router.callback_query(F.data.startswith("usr:list:"))
async def list_users(call: CallbackQuery, role: str, user: dict) -> None:
    if not roles.is_moderator(role):
        await call.answer(_no_rights(user), show_alert=True)
        return
    await call.answer()
    try:
        page = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        page = 0
    items, pages = _page(page)
    page = max(0, min(page, pages - 1))
    lang = i18n.language_of(user)
    lines = [
        _t(user, "users.list_title", "👥 <b>Пользователи</b> — всего {total} "
           "(стр. {page}/{pages})").format(
            total=len(storage.users()), page=page + 1, pages=pages)
    ]
    for uid, user_role, count in items:
        record = storage.get_user(uid) or {}
        username = f" @{esc(record.get('username'))}" if record.get("username") else ""
        lines.append(
            f"<code>{uid}</code>{username} — {roles.title(user_role, lang)}, "
            + _t(user, "users.locations_count", "локаций: {count}").format(count=count)
        )
    lines.append("\n<i>" + _t(user, "users.open_hint",
                             "Нажмите на пользователя, чтобы открыть карточку.") + "</i>")
    await safe_edit(call, "\n".join(lines),
                    keyboards.users_page(items, page, pages, lang))


def _card_text(uid: str, viewer: dict | None = None) -> str:
    record = storage.get_user(uid) or {}
    lang = i18n.language_of(viewer)
    settings = record.get("settings") or {}
    active = ", ".join(key for key, value in settings.items() if value) or \
        _t(viewer, "users.none", "нет")
    username = f"@{esc(record.get('username'))}" if record.get("username") else "—"
    return "\n".join([
        _t(viewer, "users.card_title", "👤 <b>Пользователь</b>") + f" <code>{uid}</code>",
        _t(viewer, "users.nick", "Ник") + f": {username}",
        _t(viewer, "users.role", "Роль") + f": {roles.title(record.get('role'), lang)}",
        _t(viewer, "users.locations", "Локаций") + f": <b>{len(record.get('locs') or [])}</b>",
        _t(viewer, "users.categories", "Категории оповещений") + f": {esc(active)}",
        _t(viewer, "users.weather", "Погода") + f": "
        f"{esc(keyboards.weather_label(record, lang))}",
    ])


@router.callback_query(F.data.startswith("usr:card:"))
async def card(call: CallbackQuery, role: str, user: dict) -> None:
    if not roles.is_moderator(role):
        await call.answer(_no_rights(user), show_alert=True)
        return
    target = call.data.split(":")[2]
    record = storage.get_user(target)
    if record is None:
        await call.answer(_not_found(user), show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call, _card_text(target, user),
        keyboards.user_card(target, record.get("role", "user"), role,
                            i18n.language_of(user)),
    )


@router.callback_query(F.data.startswith("usr:locs:"))
async def user_locations(call: CallbackQuery, role: str, user: dict) -> None:
    target = call.data.split(":")[2]
    record = storage.get_user(target)
    if record is None:
        await call.answer(_not_found(user), show_alert=True)
        return
    if not roles.can_edit_user(role, record.get("role")):
        await call.answer(_no_rights(user), show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        locations_text(record, owner_label=f"<code>{target}</code>"),
        keyboards.locations_menu(record.get("locs") or [], owner=target),
    )


@router.callback_query(F.data.startswith("usr:sets:"))
async def user_settings(call: CallbackQuery, role: str, user: dict) -> None:
    target = call.data.split(":")[2]
    record = storage.get_user(target)
    if record is None:
        await call.answer(_not_found(user), show_alert=True)
        return
    if not roles.can_edit_user(role, record.get("role")):
        await call.answer(_no_rights(user), show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        _t(user, "users.settings_title", "⚙️ <b>Оповещения пользователя</b>")
        + f" <code>{target}</code>",
        keyboards.settings_menu(record, target),
    )


@router.callback_query(F.data.startswith("usr:role:"))
async def change_role(call: CallbackQuery, role: str, user: dict) -> None:
    parts = call.data.split(":")
    target, new_role = parts[2], parts[3]
    record = storage.get_user(target)
    if record is None:
        await call.answer(_not_found(user), show_alert=True)
        return
    if target == str(call.from_user.id):
        await call.answer(_t(user, "users.self_role", "Нельзя менять роль самому себе."),
                          show_alert=True)
        return
    if not roles.can_assign(role, record.get("role"), new_role):
        await call.answer(_t(user, "users.role_denied",
                             "Недостаточно прав для этой роли."), show_alert=True)
        return

    record["role"] = new_role
    await storage.save()
    await call.answer(_t(user, "users.role_changed", "Роль изменена: {role}").format(
        role=roles.title(new_role, i18n.language_of(user))))
    await safe_edit(call, _card_text(target, user),
                    keyboards.user_card(target, new_role, role, i18n.language_of(user)))
    # Уведомление — на языке того, чью роль поменяли, а не модератора.
    await send_html(
        target,
        _t(record, "users.role_notice",
           "ℹ️ Ваша роль в системе «Радар» изменена на {role}.").format(
            role=roles.title(new_role, i18n.language_of(record))),
    )


@router.callback_query(F.data.startswith("usr:del:"))
async def ask_delete(call: CallbackQuery, role: str, user: dict) -> None:
    target = call.data.split(":")[2]
    record = storage.get_user(target)
    if record is None:
        await call.answer(_not_found(user), show_alert=True)
        return
    if not roles.can_delete_user(role, record.get("role")):
        await call.answer(_t(user, "users.delete_admins",
                             "Удаление доступно администраторам."), show_alert=True)
        return
    await call.answer()
    lang = i18n.language_of(user)
    await safe_edit(
        call,
        _t(user, "users.delete_ask",
           "⚠️ Удалить пользователя {id} ({role}) вместе со всеми локациями?").format(
            id=f"<code>{target}</code>", role=roles.title(record.get("role"), lang)),
        keyboards.confirm("usr:delok", target, f"usr:card:{target}", lang),
    )


@router.callback_query(F.data.startswith("usr:delok:"))
async def confirm_delete(call: CallbackQuery, role: str, user: dict) -> None:
    target = call.data.split(":")[2]
    record = storage.get_user(target)
    if record is None:
        await call.answer(_not_found(user), show_alert=True)
        return
    if not roles.can_delete_user(role, record.get("role")):
        await call.answer(_no_rights(user), show_alert=True)
        return
    await storage.drop_user(target)
    await call.answer(_t(user, "users.deleted_short", "Пользователь удалён"))
    items, pages = _page(0)
    await safe_edit(
        call,
        _t(user, "users.deleted", "✅ Пользователь {id} удалён.").format(
            id=f"<code>{target}</code>"),
        keyboards.users_page(items, 0, pages, i18n.language_of(user)),
    )


@router.callback_query(F.data == "usr:invite")
async def invite(call: CallbackQuery, user: dict) -> None:
    """Приглашение доступно любому пользователю: система тем полезнее,
    чем больше соседей о ней знает. Перешедший получает роль «Пользователь»,
    повысить её может только администрация."""
    await call.answer()
    me = await bot.get_me()
    await safe_edit(
        call,
        _t(user, "users.invite_title", "🔗 <b>Инвайт-ссылка</b>") + "\n"
        f"https://t.me/{me.username}?start=join\n\n<i>"
        + _t(user, "users.invite_hint",
             "Перешедший по ней получает роль «Пользователь»: свои локации "
             "и оповещения. Повысить роль может только администрация.")
        + "</i>",
        back_kb("menu:main", _t(user, "menu.home", "🏠 В главное меню")),
    )


# --------------------------------------------------------------------------
#  Добавление локации пользователю силами администрации
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("usr:addloc:"))
async def ask_location(call: CallbackQuery, state: FSMContext, role: str,
                       user: dict) -> None:
    target = call.data.split(":")[2]
    record = storage.get_user(target)
    if record is None:
        await call.answer(_not_found(user), show_alert=True)
        return
    if not roles.can_edit_user(role, record.get("role")):
        await call.answer(_no_rights(user), show_alert=True)
        return

    await call.answer()
    await state.set_state(Form.admin_add_location)
    await state.update_data(target_id=target)
    hint = ""
    if config.DEFAULT_CITY:
        hint = " " + _t(user, "users.default_city",
                        "Город по умолчанию — {city}.").format(city=esc(config.DEFAULT_CITY))
    await safe_edit(
        call,
        _t(user, "users.add_loc_title", "➕ <b>Локация для</b>") + f" <code>{target}</code>\n\n"
        + _t(user, "users.add_loc_prompt",
             "Пришлите адрес текстом, например <code>улица Чапаева, 12</code>.")
        + hint + "\n"
        + _t(user, "users.add_loc_geo",
             "Можно также переслать или отправить геопозицию — она будет добавлена "
             "этому пользователю.")
        + "\n\n<i>" + _t(user, "users.cancel_hint", "/cancel — отмена.") + "</i>",
        back_kb(f"usr:card:{target}", _t(user, "common.cancel", "Отмена")),
    )


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=25),
        headers={"User-Agent": config.USER_AGENT},
    )


async def _attach(target: str, info: dict[str, str], lat: float, lon: float) -> dict:
    location = storage.new_location(
        info.get("name") or f"{lat:.5f}, {lon:.5f}", lat, lon,
        street=info.get("street", ""), house=info.get("house", ""),
        city=info.get("city", ""), district=info.get("district", ""),
        region=info.get("region", ""),
    )
    storage.get_user(target)["locs"].append(location)
    await storage.save()
    return location


async def _notify_owner(target: str, location: dict) -> None:
    """Сообщение человеку, которому добавили локацию, — на его языке."""
    record = storage.get_user(target)
    await send_html(
        target,
        _t(record, "users.loc_added_notice",
           "📍 Администратор добавил вам локацию {name}.\n"
           "Оповещения по ней уже включены — управлять можно в разделе "
           "«Мои локации».").format(name=f"<b>{esc(location['name'])}</b>"),
    )


async def _report(message: Message, target: str, location: dict,
                  viewer: dict | None) -> None:
    details = ", ".join(
        part for part in (location["district"], location["city"], location["region"]) if part
    )
    text = _t(viewer, "users.loc_added", "✅ Локация {name} добавлена пользователю {id}.").format(
        name=f"<b>{esc(location['name'])}</b>", id=f"<code>{target}</code>")
    if details:
        text += f"\n<i>{esc(details)}</i>"
    if not location["street"]:
        text += "\n⚠️ <i>" + _t(viewer, "users.no_street",
                               "Улица не определена — адресные оповещения ЖКХ "
                               "могут быть неточными.") + "</i>"
    await message.answer(text, reply_markup=back_kb(
        f"usr:card:{target}", _t(viewer, "users.back_to_user", "◀️ К пользователю")))
    await _notify_owner(target, location)


def _denied_text(viewer: dict | None) -> str:
    return "❌ " + _t(viewer, "users.gone_or_denied",
                     "Пользователь не найден или недостаточно прав.")


@router.message(Form.admin_add_location, F.location)
async def add_by_geo(message: Message, state: FSMContext, role: str,
                     user: dict) -> None:
    data = await state.get_data()
    target = data.get("target_id", "")
    record = storage.get_user(target)
    if record is None or not roles.can_edit_user(role, record.get("role")):
        await state.clear()
        await message.answer(_denied_text(user))
        return

    lat, lon = message.location.latitude, message.location.longitude
    async with _session() as session:
        info = await geocode.reverse(session, lat, lon)
    await state.clear()
    await _report(message, target, await _attach(target, info, lat, lon), user)


@router.message(Form.admin_add_location, F.text)
async def add_by_address(message: Message, state: FSMContext, role: str,
                         user: dict) -> None:
    query = (message.text or "").strip()
    if query.startswith("/"):
        return

    data = await state.get_data()
    target = data.get("target_id", "")
    record = storage.get_user(target)
    if record is None or not roles.can_edit_user(role, record.get("role")):
        await state.clear()
        await message.answer(_denied_text(user))
        return

    async with _session() as session:
        found = await geocode.forward(session, query, config.DEFAULT_CITY)

    if not found:
        await message.answer("❌ " + _t(
            user, "users.address_not_found",
            "Адрес не найден. Уточните формулировку — например, "
            "<code>Саратов, улица Чапаева, 12</code>. /cancel — отмена."))
        return

    if len(found) == 1:
        await state.clear()
        item = found[0]
        location = await _attach(target, item, float(item["lat"]), float(item["lon"]))
        await _report(message, target, location, user)
        return

    await state.update_data(candidates=found)
    lines = [_t(user, "users.variants", "🔎 <b>Найдено вариантов: {count}</b>").format(
        count=len(found)), ""]
    lines += [
        f"{index + 1}. {esc(item['display'][:120])}" for index, item in enumerate(found)
    ]
    lines.append("")
    lines.append("<i>" + _t(user, "users.pick_one", "Выберите нужный.") + "</i>")
    await message.answer("\n".join(lines), reply_markup=keyboards.geocode_choices(
        found, target, i18n.language_of(user)))


@router.callback_query(F.data.startswith("usr:pickloc:"))
async def pick_location(call: CallbackQuery, state: FSMContext, role: str,
                        user: dict) -> None:
    parts = call.data.split(":")
    target, index = parts[2], int(parts[3])
    record = storage.get_user(target)
    if record is None or not roles.can_edit_user(role, record.get("role")):
        await call.answer(_no_rights(user), show_alert=True)
        return

    candidates = (await state.get_data()).get("candidates") or []
    if index >= len(candidates):
        await call.answer(_t(user, "users.list_stale", "Список устарел, начните заново."),
                          show_alert=True)
        await state.clear()
        return

    item = candidates[index]
    await state.clear()
    await call.answer(_t(user, "users.adding", "Добавляю…"))
    location = await _attach(target, item, float(item["lat"]), float(item["lon"]))
    await safe_edit(
        call,
        _t(user, "users.loc_added", "✅ Локация {name} добавлена пользователю {id}.").format(
            name=f"<b>{esc(location['name'])}</b>", id=f"<code>{target}</code>"),
        keyboards.user_card(target, record.get("role", "user"), role,
                            i18n.language_of(user)),
    )
    await _notify_owner(target, location)
