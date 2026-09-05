"""Музыка: приём треков, плейлисты, воспроизведение (с 4.9.5.2).

Каркас из дорожной карты 4.9.5: трек присылается файлом, играет
встроенным проигрывателем Telegram, раскладывается по плейлистам.
Подбор похожего и внешние базы — следующие шаги.

Ограничение, которое нельзя обойти: каждый слушает то, что загрузил
сам. Общей библиотеки нет и не будет: раздача чужих фонограмм —
распространение, а платная выдача треков сделала бы бота пиратским
сервисом со всеми последствиями для домена и хостинга.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import secrets as secrets_module

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import music, roles, storage, subscription
from ..states import Form
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.music")
router = Router(name="music")


def _menu(user: dict, role: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if music.tracks_of(user):
        rows.append([InlineKeyboardButton(
            text="▶️ Мои треки", callback_data="mus:list")])
    for pl in music.playlists_of(user):
        count = len(pl.get("tracks") or [])
        rows.append([InlineKeyboardButton(
            text=f"🎵 {pl['name']} ({count})",
            callback_data=f"mus:pl:{pl['name'][:40]}")])
    rows.append([InlineKeyboardButton(
        text="➕ Новый плейлист", callback_data="mus:newpl")])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню",
                                      callback_data="menu:main")])
    del role
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _track_kb(track_id: str, playlists: list[dict],
              has_similar: bool = False,
              heavy: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text="▶️ Играть", callback_data=f"mus:play:{track_id}")]]
    for pl in playlists:
        mark = "➖" if track_id in (pl.get("tracks") or []) else "➕"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {pl['name'][:40]}",
            callback_data=f"mus:toggle:{pl['name'][:40]}:{track_id}")])
    if has_similar:
        rows.append([InlineKeyboardButton(
            text="✨ Похожие из моих треков",
            callback_data=f"mus:similar:{track_id}")])
    if heavy:
        # Пережатие — только когда есть чем сэкономить: кнопка на треке
        # в 2 МБ обещала бы впустую.
        rows.append([InlineKeyboardButton(
            text="🗜 Сжать без потери качества на слух",
            callback_data=f"mus:zip:{track_id}")])
    rows.append([InlineKeyboardButton(
        text="🗑 Удалить", callback_data=f"mus:del:{track_id}")])
    rows.append([InlineKeyboardButton(text="◀️ К музыке",
                                      callback_data="mus:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _section(user: dict, role: str) -> str:
    return (
        "🎵 <b>Музыка</b>\n\n"
        f"{music.describe(user, role)}\n\n"
        "Пришлите аудиофайл сообщением — он появится в ваших треках.\n"
        "Форматы: mp3, m4a, ogg, opus, flac, wav; до "
        f"{music.MAX_TRACK_MB} МБ.\n\n"
        "<i>Каждый слушает только то, что загрузил сам — общей "
        "библиотеки нет.</i>"
    )


@router.message(Command("music"))
async def cmd_music(message: Message, user: dict, role: str) -> None:
    from .. import features

    if not features.enabled("music"):
        await message.answer("🎵 Музыка отключена.")
        return
    await message.answer(_section(user, role), reply_markup=_menu(user, role))


@router.callback_query(F.data == "mus:menu")
async def menu(call, user: dict, role: str) -> None:
    from .. import features

    if not features.enabled("music"):
        await call.answer("Музыка отключена.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _section(user, role), _menu(user, role))


@router.message(F.audio)
async def take_track(message: Message, user: dict, role: str) -> None:
    """Аудиофайл сообщением — в хранилище."""
    from .. import features

    if not features.enabled("music"):
        return  # не наш файл — пусть идёт дальше по цепочке

    audio = message.audio
    if not audio:
        return

    ext = ""
    for candidate in music.SUPPORTED_EXT:
        if (audio.file_name or "").lower().endswith(candidate):
            ext = candidate
            break
    if not ext:
        await message.answer(
            "❌ Формат не поддерживается. Игрок Telegram понимает: "
            + ", ".join(music.SUPPORTED_EXT) + ".")
        return

    if audio.file_size and audio.file_size > music.MAX_TRACK_MB * 1024 * 1024:
        await message.answer(
            f"❌ Файл больше {music.MAX_TRACK_MB} МБ — это уже не песня "
            "в мессенджере.")
        return

    limit = music.track_limit(user, role)
    if len(music.tracks_of(user)) >= limit:
        if subscription.active(user, role):
            await message.answer("❌ Хранилище заполнено.")
        else:
            await message.answer(
                f"🔒 Бесплатно — {music.FREE_TRACKS} треков. Подписка "
                "расширяет хранилище до "
                f"{music.SUBSCRIBED_TRACKS}.")
        return

    try:
        file = await message.bot.get_file(audio.file_id)
        data = await message.bot.download_file(file.file_path)
        payload = data.read() if data else b""
    except Exception as exc:  # noqa: BLE001
        log.warning("Трек не скачан: %s", exc)
        await message.answer("❌ Не удалось скачать файл. Попробуйте ещё раз.")
        return

    tags = music.read_tags(payload)
    track_id = secrets_module.token_hex(8)

    os.makedirs(music.DIRECTORY, exist_ok=True)
    path = os.path.join(music.DIRECTORY, f"{track_id}{ext}")
    with open(path, "wb") as handle:
        handle.write(payload)

    name = (audio.file_name or "Без названия").rsplit(".", 1)[0]
    music.add_track(user, track_id, name=name, ext=ext,
                    size=len(payload),
                    artist=tags.get("artist", ""),
                    title=tags.get("title", ""),
                    genre=tags.get("genre", ""))
    await storage.save(message.from_user.id)

    shown = tags.get("title") or name
    artist = tags.get("artist", "")
    label = f"{artist} — {shown}" if artist else shown
    # Кнопка «Похожие» появляется, только когда находить есть из чего:
    # пустая кнопка обещала бы впустую.
    similar_now = any(
        _same_tag(tags.get("artist"), t.get("artist"))
        or _same_tag(tags.get("genre"), t.get("genre"))
        for t in music.tracks_of(user) if t.get("id") != track_id
    )
    await message.answer(
        f"✅ Трек добавлен: <b>{label[:80]}</b>\n"
        f"{music.describe(user, role)}",
        reply_markup=_track_kb(track_id, music.playlists_of(user),
                               has_similar=similar_now),
    )
    log.info("Добавлен трек: %s", label[:60])


def _same_tag(a: str | None, b: str | None) -> bool:
    """Совпадают ли теги по нормализованному виду."""
    from ..music import _norm_word

    left, right = _norm_word(a or ""), _norm_word(b or "")
    return bool(left) and left == right


@router.callback_query(F.data.startswith("mus:play:"))
async def play(call) -> None:
    track_id = call.data.split(":")[2]
    await call.answer()
    track = next((t for t in music.tracks_of(_user_of(call))
                  if t.get("id") == track_id), None)
    if track is None:
        await call.message.answer("Трек не найден.")
        return
    path = os.path.join(music.DIRECTORY,
                        f"{track_id}{track.get('ext') or ''}")
    if not os.path.isfile(path):
        await call.message.answer("Файл трека потерян — загрузите заново.")
        return
    caption = track.get("name") or "Трек"
    artist = track.get("artist") or ""
    title = track.get("title") or ""
    if artist or title:
        caption = f"{artist} — {title}" if artist else title
    await call.message.answer_audio(
        FSInputFile(path),
        caption=f"🎵 {caption[:80]}",
        request_timeout=600,
    )


@router.callback_query(F.data.startswith("mus:del:"))
async def remove(call) -> None:
    track_id = call.data.split(":")[2]
    await call.answer()
    user = _user_of(call)
    if music.remove_track(user, track_id):
        await storage.save(call.from_user.id)
        await safe_edit(call, "🗑 Трек удалён.", _menu(user, _role_of(call)))
    else:
        await call.answer("Трек не найден.", show_alert=True)


@router.callback_query(F.data.startswith("mus:list"))
async def track_list(call, user: dict, role: str) -> None:
    await call.answer()
    tracks = music.tracks_of(user)
    if not tracks:
        await safe_edit(call, _section(user, role), _menu(user, role))
        return
    rows = []
    for t in tracks:
        artist = t.get("artist") or ""
        title = t.get("title") or t.get("name") or "Трек"
        label = f"{artist} — {title}" if artist else title
        rows.append([InlineKeyboardButton(
            text=f"🎵 {label[:50]}",
            callback_data=f"mus:track:{t['id']}")])
    rows.append([InlineKeyboardButton(text="◀️ К музыке",
                                      callback_data="mus:menu")])
    await safe_edit(call, "🎵 <b>Мои треки</b>",
                    InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mus:track:"))
async def track_card(call, user: dict) -> None:
    track_id = call.data.split(":")[2]
    await call.answer()
    track = next((t for t in music.tracks_of(user)
                  if t.get("id") == track_id), None)
    if track is None:
        await call.answer("Трек не найден.", show_alert=True)
        return
    artist = track.get("artist") or ""
    title = track.get("title") or track.get("name") or "Трек"
    label = f"{artist} — {title}" if artist else title
    has_similar = bool(music.similar(user, track_id))
    size = int(track.get("size") or 0)
    heavy = music.worth_compress(size)
    size_line = f"\nВес: {music.format_size(size)}" if size else ""
    await safe_edit(
        call,
        f"🎵 <b>{label[:80]}</b>\n"
        f"Файл: {track.get('name', '')[:60]}{track.get('ext', '')}"
        f"{size_line}",
        _track_kb(track_id, music.playlists_of(user),
                  has_similar=has_similar, heavy=heavy),
    )


@router.callback_query(F.data.startswith("mus:similar:"))
async def similar_tracks(call, user: dict) -> None:
    """Похожие из своих треков — по тегам, без сети."""
    track_id = call.data.split(":")[2]
    await call.answer()
    found = music.similar(user, track_id)
    if not found:
        await call.answer("Похожих не нашлось: мало тегов или треков.",
                          show_alert=True)
        return

    base = next((t for t in music.tracks_of(user)
                 if t.get("id") == track_id), None)
    head = "по треку"
    if base:
        artist = base.get("artist") or ""
        title = base.get("title") or base.get("name") or ""
        head = f"{artist} — {title}" if artist else title

    rows = []
    for t in found:
        artist = t.get("artist") or ""
        title = t.get("title") or t.get("name") or "Трек"
        label = f"{artist} — {title}" if artist else title
        rows.append([InlineKeyboardButton(
            text=f"✨ {label[:50]}",
            callback_data=f"mus:play:{t['id']}")])
    # Похожие можно добавить в существующий плейлист — продолжение
    # одним нажатием.
    for pl in music.playlists_of(user):
        rows.append([InlineKeyboardButton(
            text=f"➕ Все в «{pl['name'][:30]}»",
            callback_data=f"mus:addsim:{track_id}:{pl['name'][:40]}")])
    rows.append([InlineKeyboardButton(
        text="◀️ К треку", callback_data=f"mus:track:{track_id}")])
    await safe_edit(
        call,
        f"✨ <b>Похожие на «{head[:60]}»</b>\n"
        "<i>Подбор по тегам ваших треков — без внешних сервисов.</i>",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("mus:addsim:"))
async def add_similar(call, user: dict) -> None:
    """Все похожие трека — в плейлист одним нажатием."""
    # mus:addsim:<трек>:<плейлист>
    parts = call.data.split(":", 3)
    if len(parts) < 4:
        await call.answer("Запрос устарел.", show_alert=True)
        return
    track_id, playlist = parts[2], parts[3]

    found = music.similar(user, track_id)
    if not found:
        await call.answer("Похожих не нашлось.", show_alert=True)
        return

    added = 0
    for t in found:
        result = music.toggle_in_playlist(user, playlist, t["id"])
        if result:
            added += 1
    await storage.save(call.from_user.id)
    await call.answer(f"Добавлено: {added}")
    await playlist_view(call, user)


@router.callback_query(F.data.startswith("mus:zip:"))
async def compress(call, user: dict) -> None:
    """Пережать трек: opus при битрейте исходника, файл заменяется.

    Тегов и места в плейлистах это не касается — трек тот же,
    просто полегче. Процессор одноплатника слабее музыки: запускаем
    с низким приоритетом, оповещения не ждут.
    """
    track_id = call.data.split(":")[2]
    track = next((t for t in music.tracks_of(user)
                  if t.get("id") == track_id), None)
    if track is None:
        await call.answer("Трек не найден.", show_alert=True)
        return

    await call.answer()
    notice = await call.message.answer(
        "🗜 <b>Сжимаю трек…</b>\n"
        "<i>Занимает до пары минут, оповещения идут как обычно.</i>"
    )
    old_size = int(track.get("size") or 0)
    ok, complaint, new_size = await music.compress_track(track)
    if not ok:
        try:
            await notice.delete()
        except Exception:  # noqa: BLE001
            pass
        await call.message.answer(f"ℹ️ {complaint}.")
        return

    track["size"] = new_size
    await storage.save(call.from_user.id)
    try:
        await notice.delete()
    except Exception:  # noqa: BLE001
        pass
    saved = f", было {music.format_size(old_size)}" if old_size else ""
    await call.message.answer(
        f"✅ Трек сжат: теперь {music.format_size(new_size)}{saved}.\n"
        "Качество — opus при битрейте исходника: на слух разницы нет.",
    )


@router.callback_query(F.data.startswith("mus:shuf:"))
async def shuffle(call, user: dict) -> None:
    """Перемешать плейлист — порядок сохраняется."""
    name = call.data.split(":", 2)[2]
    await call.answer("Перемешано")
    tracks = music.shuffle_playlist(user, name)
    await storage.save(call.from_user.id)

    rows = []
    for t in tracks:
        artist = t.get("artist") or ""
        title = t.get("title") or t.get("name") or "Трек"
        label = f"{artist} — {title}" if artist else title
        rows.append([InlineKeyboardButton(
            text=f"🎲 {label[:50]}",
            callback_data=f"mus:play:{t['id']}")])
    rows.append([InlineKeyboardButton(
        text="🎲 Ещё раз", callback_data=f"mus:shuf:{name}")])
    rows.append([InlineKeyboardButton(text="◀️ К музыке",
                                      callback_data="mus:menu")])
    await safe_edit(call, f"🎲 <b>«{name[:40]}» перемешан</b>",
                    InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mus:toggle:"))
async def toggle(call, user: dict) -> None:
    # mus:toggle:<плейлист>:<трек> — имя плейлиста без двоеточий
    parts = call.data.split(":", 3)
    if len(parts) < 4:
        await call.answer("Запрос устарел.", show_alert=True)
        return
    playlist, track_id = parts[2], parts[3]
    result = music.toggle_in_playlist(user, playlist, track_id)
    if result is None:
        await call.answer("Плейлист не найден.", show_alert=True)
        return
    await storage.save(call.from_user.id)
    await call.answer("Добавлен в плейлист." if result else "Убран из плейлиста.")
    await track_card(call, user)


@router.callback_query(F.data.startswith("mus:pl:"))
async def playlist_view(call, user: dict) -> None:
    name = call.data.split(":", 2)[2]
    await call.answer()
    tracks = music.playlist_tracks(user, name)
    if not tracks:
        await safe_edit(call, f"🎵 Плейлист «{name}» пуст.",
                        _menu(user, _role_of(call)))
        return
    rows = []
    for t in tracks:
        artist = t.get("artist") or ""
        title = t.get("title") or t.get("name") or "Трек"
        label = f"{artist} — {title}" if artist else title
        rows.append([InlineKeyboardButton(
            text=f"🎵 {label[:50]}",
            callback_data=f"mus:play:{t['id']}")])
    rows.append([InlineKeyboardButton(
        text="🎲 Перемешать", callback_data=f"mus:shuf:{name}")])
    rows.append([InlineKeyboardButton(text="◀️ К музыке",
                                      callback_data="mus:menu")])
    await safe_edit(call, f"🎵 <b>Плейлист «{name[:40]}»</b>",
                    InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "mus:newpl")
async def new_playlist(call, state) -> None:
    await call.answer()
    await state.set_state(Form.playlist_name)
    await safe_edit(
        call,
        "➕ <b>Новый плейлист</b>\n\nПришлите название одним сообщением.\n"
        "<i>/cancel — отмена.</i>",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Отмена", callback_data="mus:menu")]]),
    )


@router.message(Form.playlist_name)
async def take_playlist_name(message: Message, state, user: dict) -> None:
    await state.clear()
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    if not music.create_playlist(user, text):
        await message.answer(
            "❌ Не вышло: лимит плейлистов или имя уже занято.",
            reply_markup=back_kb("mus:menu", "◀️ К музыке"))
        return
    await storage.save(message.from_user.id)
    await message.answer(
        f"✅ Плейлист «{music.safe_title(text)}» создан.",
        reply_markup=back_kb("mus:menu", "◀️ К музыке"))


def _user_of(call) -> dict:
    return storage.get_user(call.from_user.id) or {}


def _role_of(call) -> str:
    return (_user_of(call).get("role") or "user")
