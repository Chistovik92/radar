"""Кнопки соцмеханики внешнего музыкального каталога."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import features, music, music_social as social, musicsearch, storage
from ..states import Form
from ..textutils import esc
from ..tg import safe_edit
from . import music_search as search

router = Router(name="music_social")


async def _feature_guard(handler, event, data):
    """Единый вход соцмеханики: флаг и отмена незавершённых форм при выходе."""
    callback = str(getattr(event, "data", "") or "")
    state = data.get("state")
    if not features.enabled("music_search"):
        if state:
            await state.clear()
        if callback:
            await event.answer("Поиск музыки отключён.", show_alert=True)
        return None
    starts_form = callback in ("mss:new", "mss:about") or callback.startswith("mss:newfor:")
    if callback and state and not starts_form:
        await state.clear()
    return await handler(event, data)


if hasattr(router.message, "middleware"):
    router.message.middleware(_feature_guard)
    router.callback_query.middleware(_feature_guard)


async def _edit_or_send(call, text: str, markup: InlineKeyboardMarkup) -> None:
    """Inline-сообщение нельзя редактировать через callback без message."""
    if call.message is not None:
        await safe_edit(call, text, markup)
    else:
        await call.bot.send_message(call.from_user.id, text, reply_markup=markup)


def _back(callback: str = "msc:menu") -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="◀️ Назад", callback_data=callback)]


@router.callback_query(F.data.startswith("mss:like:"))
async def like(call, user: dict) -> None:
    if not features.enabled("music_search"):
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track_id = call.data.split(":", 2)[2]
    active, likes, dislikes = await social.toggle_like(track_id, call.from_user.id)
    await call.answer("Лайк поставлен" if active else "Лайк убран")
    track = await musicsearch.catalog_get(track_id)
    await _edit_or_send(call, f"🎵 <b>{esc(search.track_label(track))}</b>",
                    await search.track_kb(track_id, user))


@router.callback_query(F.data.startswith("mss:dislike:"))
async def dislike(call, user: dict) -> None:
    if not features.enabled("music_search"):
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track_id = call.data.split(":", 2)[2]
    active, _, _ = await social.toggle_dislike(track_id, call.from_user.id)
    await call.answer("Дизлайк поставлен" if active else "Дизлайк убран")
    track = await musicsearch.catalog_get(track_id)
    await _edit_or_send(call, f"🎵 <b>{esc(search.track_label(track))}</b>",
                    await search.track_kb(track_id, user))


@router.callback_query(F.data.startswith("mss:save:"))
async def save(call, user: dict) -> None:
    if not features.enabled("music_search"):
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track_id = call.data.split(":", 2)[2]
    changed = music.toggle_saved(user, track_id)
    if changed is None:
        await call.answer(f"Лимит избранного: {music.MAX_SAVED}.", show_alert=True)
        return
    await storage.save(call.from_user.id)
    await call.answer("Добавлено в избранное" if changed else "Убрано из избранного")
    track = await musicsearch.catalog_get(track_id)
    await _edit_or_send(call, f"🎵 <b>{esc(search.track_label(track))}</b>",
                    await search.track_kb(track_id, user))


@router.callback_query(F.data.startswith("mss:add:"))
async def add_to_playlist(call) -> None:
    if not features.enabled("music_search"):
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track_id = call.data.split(":", 2)[2]
    playlists = await social.user_playlists(call.from_user.id)
    rows = [[InlineKeyboardButton(
        text=f"{'➖' if track_id in item['tracks'] else '➕'} {item['name'][:45]}",
        callback_data=f"mss:toggle:{item['id']}:{track_id}"
    )] for item in playlists]
    rows.append([InlineKeyboardButton(text="➕ Новый плейлист",
                                      callback_data=f"mss:newfor:{track_id}")])
    rows.append(_back(f"msc:track:{track_id}"))
    await call.answer()
    await _edit_or_send(call, "Выберите плейлист:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mss:toggle:"))
async def toggle_track(call) -> None:
    _, _, playlist_id, track_id = call.data.split(":", 3)
    changed = await social.toggle_public_track(playlist_id, call.from_user.id, track_id)
    if changed is None:
        await call.answer("Нет доступа или плейлист заполнен.", show_alert=True)
        return
    await call.answer("Трек добавлен" if changed else "Трек убран")
    playlists = await social.user_playlists(call.from_user.id)
    rows = [[InlineKeyboardButton(
        text=f"{'➖' if track_id in item['tracks'] else '➕'} {item['name'][:45]}",
        callback_data=f"mss:toggle:{item['id']}:{track_id}"
    )] for item in playlists]
    rows.extend([[InlineKeyboardButton(text="➕ Новый плейлист",
                                       callback_data=f"mss:newfor:{track_id}")],
                 _back(f"msc:track:{track_id}")])
    await _edit_or_send(call, "Выберите плейлист:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "mss:list")
async def playlists(call) -> None:
    if not features.enabled("music_search"):
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    own = await social.user_playlists(call.from_user.id)
    rows = [[InlineKeyboardButton(
        text=f"{'🌐' if item['is_public'] else '🔒'} {item['name'][:40]} ({len(item['tracks'])})",
        callback_data=f"mss:pl:{item['id']}"
    )] for item in own]
    rows.append([InlineKeyboardButton(text="➕ Новый плейлист", callback_data="mss:new")])
    rows.append([InlineKeyboardButton(text="🏆 Публичные плейлисты", callback_data="mss:toppl")])
    rows.append(_back())
    await call.answer()
    await _edit_or_send(call, "📚 <b>Мои плейлисты</b>" + ("\n\nПока пусто." if not own else ""),
                    InlineKeyboardMarkup(inline_keyboard=rows))


async def _ask_name(call, state, track_id: str = "") -> None:
    await state.set_state(Form.public_playlist_name)
    await state.update_data(music_pending_track=track_id)
    await call.answer()
    await _edit_or_send(call, "Введите название нового публичного плейлиста (до 80 символов):",
                    InlineKeyboardMarkup(inline_keyboard=[_back("mss:list")]))


@router.callback_query(F.data == "mss:new")
async def new_playlist(call, state) -> None:
    await _ask_name(call, state)


@router.callback_query(F.data.startswith("mss:newfor:"))
async def new_playlist_for(call, state) -> None:
    await _ask_name(call, state, call.data.split(":", 2)[2])


@router.message(Form.public_playlist_name, F.text)
async def create_playlist(message: Message, state) -> None:
    if not features.enabled("music_search"):
        await state.clear()
        return
    data = await state.get_data()
    item = await social.create_public_playlist(message.from_user.id, message.text or "")
    await state.clear()
    if not item:
        await message.answer("❌ Достигнут лимит плейлистов.", reply_markup=search.menu_kb())
        return
    track_id = str(data.get("music_pending_track") or "")
    if track_id:
        await social.toggle_public_track(item["id"], message.from_user.id, track_id)
    await message.answer(f"✅ Плейлист «{esc(item['name'])}» создан.",
                         reply_markup=search.menu_kb())


@router.callback_query(F.data.startswith("mss:pl:"))
async def playlist(call) -> None:
    playlist_id = call.data.split(":", 2)[2]
    item = await social.public_playlist_view(playlist_id, call.from_user.id)
    if not item:
        await call.answer("Плейлист недоступен.", show_alert=True)
        return
    await call.answer()
    await _render_playlist(call, item)


async def _render_playlist(call, item: dict) -> None:
    playlist_id = item["id"]
    rows = []
    tracks = []
    for track_id in item["tracks"][:50]:
        track = await musicsearch.catalog_get(track_id)
        if not track:
            continue
        full = {**track, "id": track_id}
        tracks.append(full)
        rows.append([InlineKeyboardButton(text=f"🎵 {search.track_label(full)[:50]}",
                                          callback_data=f"msc:track:{track_id}")])
    owner = item["founder_id"] == str(call.from_user.id)
    rows.append([InlineKeyboardButton(text=f"👍 {item['likes']}",
                                      callback_data=f"mss:pllike:{playlist_id}"),
                 InlineKeyboardButton(text="✈️ Поделиться",
                                      switch_inline_query=f"playlist:{playlist_id}")])
    if owner:
        rows.append([InlineKeyboardButton(text="🗑 Удалить плейлист",
                                          callback_data=f"mss:pldel:{playlist_id}")])
    rows.append(_back("mss:list" if owner else "mss:toppl"))
    text = (f"🎶 <b>{esc(item['name'])}</b>\n"
            f"Треков: {len(item['tracks'])} · 👁 {item['views']} · 👍 {item['likes']}\n\n"
            + (search._tracks_text(tracks) or "Пока нет доступных треков."))
    await _edit_or_send(call, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mss:pllike:"))
async def playlist_like(call) -> None:
    playlist_id = call.data.split(":", 2)[2]
    active = await social.toggle_playlist_like(playlist_id, call.from_user.id)
    await call.answer("Лайк поставлен" if active else "Лайк убран")
    item = await social.public_playlist_view(playlist_id, call.from_user.id, count_view=False)
    if item:
        await _render_playlist(call, item)


@router.callback_query(F.data.startswith("mss:pldel:"))
async def playlist_delete(call) -> None:
    playlist_id = call.data.split(":", 2)[2]
    if not await social.delete_public_playlist(playlist_id, call.from_user.id):
        await call.answer("Удалить может только владелец.", show_alert=True)
        return
    await call.answer("Плейлист удалён")
    await _edit_or_send(call, "🗑 Плейлист удалён.", search.menu_kb())


@router.callback_query(F.data == "mss:tops")
async def tops(call) -> None:
    tracks = await social.top_tracks(20)
    await call.answer()
    await _edit_or_send(call, "🏆 <b>Топ треков</b>\n\n" +
                    (search._tracks_text(tracks) or "Пока нет прослушиваний."),
                    search._tracks_kb(tracks, back="msc:menu"))


@router.callback_query(F.data == "mss:toppl")
async def top_playlists(call) -> None:
    items = await social.top_playlists(20)
    rows = [[InlineKeyboardButton(text=f"🎶 {item['name'][:40]} · 👍 {item['likes']}",
                                  callback_data=f"mss:pl:{item['id']}")] for item in items]
    rows.append(_back())
    await call.answer()
    await _edit_or_send(call, "🏆 <b>Публичные плейлисты</b>" +
                    ("\n\nПока пусто." if not items else ""),
                    InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "mss:profile")
async def profile(call, user: dict) -> None:
    value = social.profile(user)
    numbers = await social.stats(user, call.from_user.id)
    text = (
        "👤 <b>Музыкальный профиль</b>\n\n"
        f"Прослушано: {numbers['played']}\nЛайков: {numbers['likes']}\n"
        f"Избранное: {numbers['saved']}\nПлейлисты: {numbers['playlists']}\n"
        f"Видимость: {'скрыт' if value['hidden'] else 'виден'}\n"
        f"О себе: {esc(value['about']) if value['about'] else 'не заполнено'}"
    )
    await call.answer()
    await _edit_or_send(call, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ О себе", callback_data="mss:about")],
        [InlineKeyboardButton(text="🙈 Показывать профиль" if value["hidden"] else "🙈 Скрыть профиль",
                              callback_data="mss:visible")],
        _back(),
    ]))


@router.callback_query(F.data == "mss:visible")
async def visible(call, user: dict) -> None:
    social.set_profile(user, hidden=not social.profile(user)["hidden"])
    await storage.save(call.from_user.id)
    await call.answer("Настройка сохранена")
    await profile(call, user)


@router.callback_query(F.data == "mss:about")
async def about(call, state) -> None:
    await state.set_state(Form.music_about)
    await call.answer()
    await _edit_or_send(call, "Введите текст «О себе» (до 500 символов):",
                    InlineKeyboardMarkup(inline_keyboard=[_back("mss:profile")]))


@router.message(Form.music_about, F.text)
async def take_about(message: Message, user: dict, state) -> None:
    social.set_profile(user, about=message.text or "")
    await storage.save(message.from_user.id)
    await state.clear()
    await message.answer("✅ Профиль обновлён.", reply_markup=search.menu_kb())
