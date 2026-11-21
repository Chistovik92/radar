"""Поиск и прослушивание внешнего музыкального каталога (6.0.0).

Постоянно сохраняются только метаданные и Telegram ``file_id``. Байты аудио
живут в памяти лишь на время отправки. Раздел личных файлов остаётся в
``handlers/music.py`` и здесь не изменяется.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import secrets as secrets_module
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
    Message,
)

from .. import features, music, music_social as social, musicsearch, storage, subscription
from ..states import Form
from ..textutils import esc
from ..tg import safe_edit

log = logging.getLogger("radar.handlers.music_search")
router = Router(name="music_search")
_downloads = asyncio.Semaphore(2)
DOWNLOAD_TIMEOUT = 360


def menu_kb() -> InlineKeyboardMarkup:
    """Статичная главная клавиатура каталога (для возвратов без счётчика)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ", callback_data="mss:tops"),
         InlineKeyboardButton(text="⭐ Избранное", callback_data="msc:saved")],
        [InlineKeyboardButton(text="🔍 Поиск", callback_data="msc:ask")],
        [InlineKeyboardButton(text="🎵 Плейлисты", callback_data="mss:list")],
        [InlineKeyboardButton(text="🕘 История", callback_data="msc:history"),
         InlineKeyboardButton(text="🎲 Случайный", callback_data="msc:random")],
        [InlineKeyboardButton(text="🏆 Топ плейлистов", callback_data="mss:toppl")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="mss:profile"),
         InlineKeyboardButton(text="ℹ️ Помощь", callback_data="msc:help")],
        [InlineKeyboardButton(text="◀️ К моей музыке", callback_data="mus:menu")],
    ])


async def menu_kb_full(user_id: str | int) -> InlineKeyboardMarkup:
    """Главная клавиатура со счётчиком плейлистов, как в not_a_music."""
    playlists = await social.user_playlists(user_id)
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🏆 Топ", callback_data="mss:tops"),
         InlineKeyboardButton(text="⭐ Избранное", callback_data="msc:saved")],
        [InlineKeyboardButton(text="🔍 Поиск", callback_data="msc:ask")],
        [InlineKeyboardButton(text=f"🎵 Плейлисты ({len(playlists)})", callback_data="mss:list")],
        [InlineKeyboardButton(text="🕘 История", callback_data="msc:history"),
         InlineKeyboardButton(text="🎲 Случайный", callback_data="msc:random")],
        [InlineKeyboardButton(text="🏆 Топ плейлистов", callback_data="mss:toppl")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="mss:profile"),
         InlineKeyboardButton(text="ℹ️ Помощь", callback_data="msc:help")],
        [InlineKeyboardButton(text="◀️ К моей музыке", callback_data="mus:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_text() -> str:
    return (
        "🎧 <b>Музыкальный каталог</b>\n\n"
        "Ищите бесплатные записи SoundCloud; при недоступности используется "
        "YouTube. Нажмите на трек, чтобы прослушать его в Telegram."
    )


def _enabled() -> bool:
    return features.enabled("music_search")


def track_label(track: dict[str, Any]) -> str:
    return musicsearch.track_display_name(
        str(track.get("artist") or ""), str(track.get("title") or "Трек")
    ) or "Трек"


async def track_kb(track_id: str, user: dict, *, back: str = "msc:menu",
                   next_cb: str | None = None, role: str | None = None,
                   uid: str | int | None = None) -> InlineKeyboardMarkup:
    uid_key = str(uid if uid is not None else (user.get("id") or user.get("uid") or ""))
    state = await social.reaction_state(track_id, uid_key)
    saved = track_id in music.saved_tracks(user)
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text=f"{'❤️' if state['liked'] else '🤍'} {state['likes']}",
            callback_data=f"mss:like:{track_id}"),
         InlineKeyboardButton(
            text=f"{'💔' if state['disliked'] else '👎'} {state['dislikes']}",
            callback_data=f"mss:dislike:{track_id}"),
         InlineKeyboardButton(text=f"👁 {state['views']}", callback_data="msc:noop")],
        [InlineKeyboardButton(text="⭐ Убрать" if saved else "⭐ В избранное",
                              callback_data=f"mss:save:{track_id}"),
         InlineKeyboardButton(text="➕ В плейлист", callback_data=f"mss:add:{track_id}")],
    ]
    if subscription.active(user, role):
        rows.append([InlineKeyboardButton(text="💾 Сохранить в мои треки",
                                          callback_data=f"mss:tolocal:{track_id}")])
    if next_cb:
        rows.append([InlineKeyboardButton(text="▶️ Слушать следующий", callback_data=next_cb)])
    rows.append([InlineKeyboardButton(text="✈️ Поделиться", switch_inline_query=f"track:{track_id}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tracks_text(tracks: list[dict[str, Any]]) -> str:
    lines = []
    for index, track in enumerate(tracks, 1):
        duration = int(track.get("duration") or 0)
        length = f" · {duration // 60}:{duration % 60:02d}" if duration else ""
        lines.append(f"{index}. {esc(track_label(track))}{length}")
    return "\n".join(lines)


def _tracks_kb(tracks: list[dict[str, Any]], *, page: int = 1,
               has_next: bool = False, back: str = "msc:menu") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🎵 {track_label(track)[:55]}",
                                  callback_data=f"msc:track:{track['id']}")]
            for track in tracks if track.get("id")]
    if page > 1 or has_next:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"msc:page:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"Стр. {page}", callback_data="msc:noop"))
        if has_next:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"msc:page:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="◀️ Каталог", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_search(target: Message | Any, query: str, page: int = 1,
                       *, edit: bool = False) -> None:
    client = musicsearch.MusicSearchClient(metadata=musicsearch.catalog_get)
    try:
        result = await client.search_track(query, page=page)
    except Exception as exc:  # noqa: BLE001
        log.info("Музыкальный поиск недоступен: %s", exc)
        text = "❌ Каталог сейчас недоступен. Попробуйте ещё раз немного позже."
        if edit:
            await safe_edit(target, text, menu_kb())
        else:
            await target.answer(text, reply_markup=menu_kb())
        return
    tracks = result.get("items") or []
    await musicsearch.catalog_merge(tracks)
    if not tracks:
        text = f"😔 По запросу «{esc(query)}» ничего не найдено."
    else:
        text = f"🔍 <b>{esc(query)}</b>\n\n{_tracks_text(tracks)}"
    last_page = int((result.get("paginationInfo") or {}).get("lastPage") or page)
    markup = _tracks_kb(tracks, page=page, has_next=last_page > page)
    if edit:
        await safe_edit(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.message(Command("findmusic", "catalog"))
async def cmd_catalog(message: Message, user: dict, state) -> None:
    if not _enabled():
        await message.answer("🎧 Поиск музыки отключён администратором.")
        return
    query = (message.text or "").split(maxsplit=1)
    if len(query) > 1 and query[1].strip():
        social.remember_query(user, query[1])
        await state.update_data(music_query=query[1].strip())
        await storage.save(message.from_user.id)
        await _show_search(message, query[1].strip())
        return
    await message.answer(menu_text(), reply_markup=menu_kb())


@router.callback_query(F.data == "msc:menu")
async def catalog_menu(call, state) -> None:
    await state.clear()
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, menu_text(), await menu_kb_full(call.from_user.id))


@router.callback_query(F.data == "msc:noop")
async def noop(call) -> None:
    await call.answer()


@router.callback_query(F.data == "msc:ask")
async def ask_query(call, user: dict) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    queries = social.recent_queries(user)
    rows: list[list[InlineKeyboardButton]] = []
    for item in queries:
        rows.append([InlineKeyboardButton(
            text=f"🔁 {item[:35]}",
            callback_data=f"msc:q:{item[:80]}")])
    rows.append([InlineKeyboardButton(text="✏️ Новый запрос", callback_data="msc:typed")])
    rows.append([InlineKeyboardButton(text="◀️ Каталог", callback_data="msc:cancel")])
    await call.answer()
    await safe_edit(call, "🔍 <b>Поиск</b>\n\nНажмите недавний запрос или введите новый.",
                    InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("msc:q:"))
async def quick_query(call, user: dict, state) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    query = call.data.split(":", 2)[2].strip()
    if not query:
        await call.answer("Запрос пуст.", show_alert=True)
        return
    social.remember_query(user, query)
    await state.update_data(music_query=query)
    await storage.save(call.from_user.id)
    await call.answer()
    await _show_search(call, query, edit=True)


@router.callback_query(F.data == "msc:typed")
async def typed_query(call, state) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    await state.set_state(Form.music_query)
    await call.answer()
    await safe_edit(call, "🔍 Введите исполнителя и название трека:",
                    InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="◀️ Отмена", callback_data="msc:cancel")
                    ]]))


@router.callback_query(F.data == "msc:cancel")
async def cancel(call, state) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(call, menu_text(), await menu_kb_full(call.from_user.id))


@router.message(Form.music_query, F.text)
async def take_query(message: Message, user: dict, state) -> None:
    if not _enabled():
        await state.clear()
        return
    query = (message.text or "").strip()[:musicsearch.MusicSearchClient.MAX_QUERY]
    if not query:
        await message.answer("Введите текст запроса.")
        return
    social.remember_query(user, query)
    await state.clear()
    await state.update_data(music_query=query)
    await storage.save(message.from_user.id)
    await _show_search(message, query)


@router.callback_query(F.data.startswith("msc:page:"))
async def search_page(call, state) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    page = max(1, int(call.data.rsplit(":", 1)[1]))
    query = str((await state.get_data()).get("music_query") or "")
    await call.answer()
    if not query:
        await safe_edit(call, "Запрос устарел. Найдите трек ещё раз.", menu_kb())
        return
    await _show_search(call, query, page, edit=True)


@router.callback_query(F.data.startswith("msc:track:"))
async def track_card(call, user: dict, role: str) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track_id = call.data.split(":", 2)[2]
    track = await musicsearch.catalog_get(track_id)
    if not track:
        await call.answer("Метаданные устарели, повторите поиск.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, f"🎵 <b>{esc(track_label(track))}</b>",
                    await track_kb(track_id, user, role=role, uid=call.from_user.id))


async def send_track(call, user: dict, track_id: str) -> None:
    """Отдать file_id либо скачать во временный буфер и закэшировать ответ."""
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track = await musicsearch.catalog_get(track_id)
    if not track:
        await call.answer("Трек не найден. Повторите поиск.", show_alert=True)
        return
    await call.answer()
    chat_id = call.message.chat.id if call.message else call.from_user.id
    cached = await musicsearch.file_id_get(track_id)
    caption = f"🎵 {esc(track_label(track))}"
    if cached:
        try:
            await call.bot.send_audio(
                chat_id, cached, caption=caption,
                title=str(track.get("title") or "Трек")[:64],
                performer=str(track.get("artist") or "")[:64] or None,
                duration=int(track.get("duration") or 0) or None,
                request_timeout=600,
            )
        except Exception as exc:  # file_id мог устареть или быть отклонён.
            log.info("Кэшированный file_id %s не принят: %s", track_id, exc)
            await musicsearch.file_id_forget(track_id)
        else:
            social.record_history(user, track_id)
            await social.register_view(track_id)
            await storage.save(call.from_user.id)
            return

    progress = await call.bot.send_message(chat_id, "⏳ Подбираю аудиодорожку…")
    reporter = musicsearch.TelegramProgressReporter(progress.edit_text, track_label(track))
    try:
        async with _downloads:
            client = musicsearch.MusicSearchClient(metadata=musicsearch.catalog_get)
            buffer = await asyncio.wait_for(
                client.download_track(track_id, reporter.update), timeout=DOWNLOAD_TIMEOUT
            )
        try:
            payload = buffer.getvalue()
            if not payload or len(payload) > musicsearch.MAX_DOWNLOAD_BYTES:
                raise musicsearch.TrackUnavailable("недопустимый размер аудио")
            ext = str(getattr(buffer, "ext", "") or "bin").lower().lstrip(".")
            filename = f"{track_label(track)[:80] or 'track'}.{ext}"
            if ext in ("mp3", "m4a"):
                sent = await call.bot.send_audio(
                    chat_id, BufferedInputFile(payload, filename=filename), caption=caption,
                    title=str(track.get("title") or "Трек")[:64],
                    performer=str(track.get("artist") or "")[:64] or None,
                    duration=int(track.get("duration") or 0) or None,
                    request_timeout=600,
                )
            else:
                # WebM/Opus и другие контейнеры не выдаём за MP3: Telegram
                # получит документ с настоящим расширением.
                sent = await call.bot.send_document(
                    chat_id, BufferedInputFile(payload, filename=filename), caption=caption,
                    request_timeout=600,
                )
        finally:
            buffer.close()
    except (TimeoutError, asyncio.TimeoutError):
        await progress.edit_text("⏱ Загрузка заняла слишком много времени. Попробуйте позже.")
        return
    except Exception as exc:  # noqa: BLE001
        log.info("Трек %s не скачан: %s", track_id, exc)
        await progress.edit_text(
            "❌ Не удалось получить полноценную бесплатную запись. "
            "Возможны DRM, премиум-превью или ограничение источника."
        )
        return
    file_id = getattr(getattr(sent, "audio", None), "file_id", "")
    if file_id:
        await musicsearch.file_id_set(track_id, file_id)
    social.record_history(user, track_id)
    await social.register_view(track_id)
    await storage.save(call.from_user.id)
    try:
        await progress.delete()
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("msc:play:"))
async def play(call, user: dict) -> None:
    await send_track(call, user, call.data.split(":", 2)[2])


async def _download_track_payload(call, track_id: str):
    """Скачать трек каталога в буфер; None — недоступен."""
    client = musicsearch.MusicSearchClient(metadata=musicsearch.catalog_get)
    try:
        async with _downloads:
            buffer = await asyncio.wait_for(
                client.download_track(track_id), timeout=DOWNLOAD_TIMEOUT
            )
        payload = buffer.getvalue()
        if not payload or len(payload) > musicsearch.MAX_DOWNLOAD_BYTES:
            return None, "недопустимый размер аудио"
        ext = str(getattr(buffer, "ext", "") or "").lower().lstrip(".")
        ext = f".{ext}" if ext else ""
        if ext not in music.SUPPORTED_EXT:
            ext = ".mp3"
        return payload, ext
    except Exception as exc:  # noqa: BLE001
        log.info("Трек %s не скачан для сохранения: %s", track_id, exc)
        return None, "источник недоступен"


@router.callback_query(F.data.startswith("mss:tolocal:"))
async def save_to_local(call, user: dict, role: str) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return

    if not subscription.active(user, role):
        await call.answer("Сохранение в личную библиотеку — только по подписке.",
                          show_alert=True)
        return
    if len(music.tracks_of(user)) >= music.track_limit(user, role):
        await call.answer(f"Хранилище заполнено ({music.track_limit(user, role)} треков).",
                          show_alert=True)
        return
    track_id = call.data.split(":", 2)[2]
    track = await musicsearch.catalog_get(track_id)
    if not track:
        await call.answer("Трек не найден.", show_alert=True)
        return
    await call.answer("Сохраняю…")
    if call.message:
        try:
            await call.message.edit_text("⏳ Сохраняю трек в личную библиотеку…")
        except Exception:  # noqa: BLE001
            pass
    payload, ext = await _download_track_payload(call, track_id)
    if payload is None:
        if call.message:
            try:
                await call.message.edit_text("❌ Не удалось сохранить: источник недоступен.")
            except Exception:  # noqa: BLE001
                pass
        return
    new_id = secrets_module.token_hex(8)
    await music.store(new_id, ext, payload)
    music.add_track(user, new_id, name=str(track.get("title") or "Трек"), ext=ext,
                    size=len(payload), artist=str(track.get("artist") or ""),
                    title=str(track.get("title") or ""))
    await storage.save(call.from_user.id)
    text = (f"✅ Сохранено в «Мои треки»: <b>{esc(track_label(track))[:80]}</b>\n"
            + music.describe(user, role))
    if call.message:
        try:
            await call.message.edit_text(text)
        except Exception:  # noqa: BLE001
            await call.bot.send_message(call.from_user.id, text)
    else:
        await call.bot.send_message(call.from_user.id, text)


@router.callback_query(F.data == "msc:saved")
async def saved(call, user: dict) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    tracks = []
    for track_id in music.saved_tracks(user)[:50]:
        track = await musicsearch.catalog_get(track_id)
        if track:
            tracks.append({**track, "id": track_id})
    rows = []
    for track in tracks:
        label = track_label(track)[:40]
        rows.append([
            InlineKeyboardButton(text=f"▶️ {label}", callback_data=f"msc:play:{track['id']}"),
            InlineKeyboardButton(text="❌", callback_data=f"mss:frem:{track['id']}"),
        ])
    rows.append([InlineKeyboardButton(text="◀️ Каталог", callback_data="msc:menu")])
    await call.answer()
    await safe_edit(call, "⭐ <b>Избранное</b>\n\n" + (_tracks_text(tracks) or "Пока пусто."),
                    InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mss:frem:"))
async def fav_remove(call, user: dict) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track_id = call.data.split(":", 2)[2]
    music.toggle_saved(user, track_id)
    await storage.save(call.from_user.id)
    await call.answer("Убрано из избранного")
    await saved(call, user)


@router.callback_query(F.data == "msc:history")
async def history(call, user: dict) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    items = social.history_of(user)[:50]
    tracks = []
    for item in items:
        track = await musicsearch.catalog_get(item["track_id"])
        if track:
            tracks.append({**track, "id": item["track_id"]})
    rows = []
    for track in tracks:
        label = track_label(track)[:40]
        rows.append([
            InlineKeyboardButton(text=f"▶️ {label}", callback_data=f"msc:play:{track['id']}"),
            InlineKeyboardButton(text="❌", callback_data=f"mss:hrem:{track['id']}"),
        ])
    if items:
        rows.append([InlineKeyboardButton(text="🗑 Очистить историю", callback_data="mss:hclr")])
    rows.append([InlineKeyboardButton(text="◀️ Каталог", callback_data="msc:menu")])
    await call.answer()
    await safe_edit(call, "🕘 <b>История за 30 дней</b>\n\n" + (_tracks_text(tracks) or "Пока пусто."),
                    InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mss:hrem:"))
async def hist_remove(call, user: dict) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track_id = call.data.split(":", 2)[2]
    social.remove_history(user, track_id)
    await storage.save(call.from_user.id)
    await call.answer("Убрано из истории")
    await history(call, user)


@router.callback_query(F.data == "mss:hclr")
async def hist_clear(call, user: dict) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    social.clear_history(user)
    await storage.save(call.from_user.id)
    await call.answer("История очищена")
    await history(call, user)


@router.callback_query(F.data == "msc:random")
async def random_track(call, user: dict, role: str) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track = await social.random_track()
    await call.answer()
    if not track:
        await safe_edit(call, "Каталог пока пуст — сначала выполните поиск.", menu_kb())
        return
    await safe_edit(call, f"🎲 <b>{esc(track_label(track))}</b>",
                    await track_kb(track["id"], user, role=role, uid=call.from_user.id))


@router.callback_query(F.data == "msc:help")
async def help_section(call) -> None:
    await call.answer()
    await safe_edit(call,
        "ℹ️ <b>О каталоге</b>\n\n"
        "Источники: бесплатные общедоступные записи SoundCloud и YouTube. "
        "DRM, SoundCloud Go+ и короткие превью не загружаются.\n\n"
        "Бот хранит только Telegram file_id, названия, ссылки и ваши настройки. "
        "Аудиофайлы на сервере постоянно не сохраняются. История удаляется "
        "через 30 дней. Используйте контент в рамках правил источника и "
        "пользовательского соглашения «Радара».",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Каталог", callback_data="msc:menu")
        ]]))


async def _inline_track_result(track: dict[str, Any]):
    track_id = str(track["id"])
    label = track_label(track)
    cached = await musicsearch.file_id_get(track_id)
    if cached:
        return InlineQueryResultCachedAudio(
            id=f"audio_{track_id}"[:64], audio_file_id=cached,
            title=str(track.get("title") or label)[:64],
            performer=str(track.get("artist") or "")[:64] or None,
            caption=f"🎵 {esc(label)}",
        )
    values = {
        "type": "article", "id": track_id[:64], "title": label[:64],
        "description": "Нажмите, затем кнопку «Слушать»",
        "input_message_content": InputTextMessageContent(
            message_text=f"🎵 {esc(label)}"
        ),
        "reply_markup": InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="▶️ Слушать", callback_data=f"msc:play:{track_id}")
        ]]),
    }
    cover = str((track.get("imageInfo") or {}).get("imageUrl") or "")
    if cover.startswith("https://"):
        values["thumbnail_url"] = cover
    return InlineQueryResultArticle(**values)


def _register_inline(func):
    """Зарегистрировать handler, не подменяя его возвратом stub-декоратора."""
    router.inline_query()(func)
    return func


@_register_inline
async def inline_search(query: InlineQuery) -> None:
    if not _enabled() or storage.get_user(str(query.from_user.id)) is None:
        await query.answer([], cache_time=10, is_personal=True)
        return
    text = (query.query or "").strip()
    if text.startswith("track:"):
        track_id = text.split(":", 1)[1].strip()[:80]
        track = await musicsearch.catalog_get(track_id)
        if not track:
            await query.answer([], cache_time=5, is_personal=True)
            return
        result = await _inline_track_result({**track, "id": track_id})
        await query.answer([result], cache_time=10, is_personal=True)
        return
    if text.startswith("playlist:"):
        playlist_id = text.split(":", 1)[1].strip()[:16]
        item = await social.public_playlist_view(
            playlist_id, query.from_user.id, count_view=False
        )
        if not item:
            await query.answer([], cache_time=5, is_personal=True)
            return
        result = InlineQueryResultArticle(
            id=f"playlist_{playlist_id}",
            title=item["name"][:64],
            description=f"Плейлист · {len(item['tracks'])} треков · 👍 {item['likes']}",
            input_message_content=InputTextMessageContent(
                message_text=f"🎶 <b>{esc(item['name'])}</b>\nПлейлист музыкального каталога"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🎶 Открыть плейлист",
                                     callback_data=f"mss:pl:{playlist_id}")
            ]]),
        )
        await query.answer([result], cache_time=10, is_personal=True)
        return
    if not text:
        await query.answer([], cache_time=10, is_personal=True,
                           switch_pm_text="Найти музыку", switch_pm_parameter="music")
        return
    try:
        async with musicsearch.MusicSearchClient(metadata=musicsearch.catalog_get) as client:
            found = await client.search_track(text)
    except Exception as exc:  # noqa: BLE001
        log.info("Inline-поиск недоступен: %s", exc)
        await query.answer([], cache_time=5, is_personal=True)
        return
    tracks = found.get("items") or []
    await musicsearch.catalog_merge(tracks)
    results = [await _inline_track_result(track) for track in tracks[:20]]
    await query.answer(results, cache_time=30, is_personal=True)
