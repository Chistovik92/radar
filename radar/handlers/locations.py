"""Локации пользователя: добавление, список, удаление, погода по группам."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from typing import Any

import aiohttp
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from .. import config, geocode, keyboards, roles, storage, weather
from ..matching import cluster_title
from ..textutils import cluster_center, cluster_locations, esc, haversine_m
from ..tg import back_kb, safe_edit, send_html

router = Router(name="locations")

def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=25),
        headers={"User-Agent": config.USER_AGENT},
    )


def locations_text(user: dict[str, Any], owner_label: str = "") -> str:
    locations = user.get("locs") or []
    if not locations:
        body = "— список пуст —"
    else:
        clusters = cluster_locations(locations, config.CLUSTER_RADIUS_M)
        lines = []
        for index, cluster in enumerate(clusters, start=1):
            if len(cluster) > 1:
                lines.append(f"<b>Группа {index}</b> <i>(в пределах 1 км)</i>")
            for loc in cluster:
                extra = ", ".join(
                    part for part in (loc.get("district"), loc.get("city")) if part
                )
                suffix = f" <i>({esc(extra)})</i>" if extra else ""
                lines.append(f"• {esc(loc.get('name'))}{suffix}")
        body = "\n".join(lines)

    head = f"📍 <b>Локации {owner_label}</b>" if owner_label else "📍 <b>Ваши локации</b>"
    tail = (
        "\n\n<i>Добавить: отправьте геопозицию в чат (Скрепка → Геопозиция). "
        "Количество не ограничено.</i>"
    )
    return f"{head}\n{body}{tail if not owner_label else ''}"


# StateFilter(None) обязателен: иначе этот обработчик перехватит геопозицию,
# отправленную администратором при добавлении локации другому пользователю.
@router.message(StateFilter(None), F.location)
async def add_location(message: Message, user: dict[str, Any]) -> None:
    lat = message.location.latitude
    lon = message.location.longitude

    if config.MAX_LOCATIONS and len(user["locs"]) >= config.MAX_LOCATIONS:
        await message.answer(f"❌ Достигнут лимит локаций ({config.MAX_LOCATIONS}).")
        return

    for existing in user["locs"]:
        if existing.get("lat") and haversine_m(
            lat, lon, float(existing["lat"]), float(existing["lon"])
        ) < 40:
            await message.answer(
                f"ℹ️ Эта точка уже сохранена как <b>{esc(existing['name'])}</b>.",
                reply_markup=back_kb(),
            )
            return

    async with _session() as session:
        info = await geocode.reverse(session, lat, lon)

    location = storage.new_location(
        info["name"], lat, lon,
        street=info["street"], house=info["house"],
        city=info["city"], district=info["district"], region=info["region"],
    )
    user["locs"].append(location)
    await storage.save()

    details = ", ".join(
        part for part in (location["district"], location["city"], location["region"]) if part
    )
    text = f"🏠 Локация <b>{esc(location['name'])}</b> добавлена."
    if details:
        text += f"\n<i>{esc(details)}</i>"
    if not location["street"]:
        text += "\n⚠️ <i>Улица не определена — адресные оповещения ЖКХ могут быть неточными.</i>"
    await message.answer(text, reply_markup=back_kb())


@router.callback_query(F.data == "loc:list")
async def list_locations(call: CallbackQuery, user: dict[str, Any]) -> None:
    await call.answer()
    await safe_edit(call, locations_text(user), keyboards.locations_menu(user["locs"]))


@router.callback_query(F.data == "loc:clear")
async def clear_locations(call: CallbackQuery, user: dict[str, Any]) -> None:
    user["locs"] = []
    await storage.save()
    await call.answer("Локации удалены")
    await safe_edit(call, locations_text(user), keyboards.locations_menu([]))


@router.callback_query(F.data.startswith("loc:del:"))
async def delete_location(call: CallbackQuery, user: dict[str, Any], role: str) -> None:
    parts = call.data.split(":")
    loc_id = parts[2]
    owner = parts[3] if len(parts) > 3 else ""

    if owner:
        target = storage.get_user(owner)
        if target is None:
            await call.answer("Пользователь не найден.", show_alert=True)
            return
        if not roles.can_edit_user(role, target.get("role")):
            await call.answer("Недостаточно прав.", show_alert=True)
            return
        storage.remove_location(owner, loc_id)
        await storage.save()
        await call.answer("Локация удалена")
        await safe_edit(
            call,
            locations_text(target, owner_label=f"<code>{owner}</code>"),
            keyboards.locations_menu(target["locs"], owner=owner),
        )
        return

    storage.remove_location(call.from_user.id, loc_id)
    await storage.save()
    await call.answer("Локация удалена")
    await safe_edit(call, locations_text(user), keyboards.locations_menu(user["locs"]))


@router.callback_query(F.data == "loc:weather")
async def show_weather(call: CallbackQuery, user: dict[str, Any]) -> None:
    locations = user.get("locs") or []
    if not locations:
        await call.answer("Сначала добавьте локацию.", show_alert=True)
        return

    await call.answer("Запрашиваю прогноз…")
    clusters = cluster_locations(locations, config.CLUSTER_RADIUS_M)
    async with _session() as session:
        for index, cluster in enumerate(clusters):
            lat, lon = cluster_center(cluster)
            data = await weather.fetch(session, lat, lon)
            markup = back_kb() if index == len(clusters) - 1 else None
            await send_html(
                call.message.chat.id,
                weather.render(data, cluster_title(cluster)),
                markup,
            )
