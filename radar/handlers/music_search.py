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

from .. import features, music, music_social as social, musicsearch, storage
from ..states import Form
from ..textutils import esc
from ..tg import safe_edit

log = logging.getLogger("radar.handlers.music_search")
router = Router(name="music_search")
_downloads = asyncio.Semaphore(2)
DOWNLOAD_TIMEOUT = 360


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти трек", callback_data="msc:ask")],
        [InlineKeyboardButton(text="⭐ Избранное", callback_data="msc:saved"),
         InlineKeyboardButton(text="🕘 История", callback_data="msc:history")],
        [InlineKeyboardButton(text="📚 Плейлисты", callback_data="mss:list"),
         InlineKeyboardButton(text="🏆 Топы", callback_data="mss:tops")],
        [InlineKeyboardButton(text="🎲 Случайный", callback_data="msc:random"),
         InlineKeyboardButton(text="👤 Профиль", callback_data="mss:profile")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="msc:help")],
        [InlineKeyboardButton(text="◀️ К моей музыке", callback_data="mus:menu")],
    ])


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


async def track_kb(track_id: str, user: dict, *, back: str = "msc:menu") -> InlineKeyboardMarkup:
    liked, disliked = await social.reaction_counts(track_id)
    saved = track_id in music.saved_tracks(user)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Слушать", callback_data=f"msc:play:{track_id}")],
        [InlineKeyboardButton(text=f"👍 {liked}", callback_data=f"mss:like:{track_id}"),
         InlineKeyboardButton(text=f"👎 {disliked}", callback_data=f"mss:dislike:{track_id}")],
        [InlineKeyboardButton(text="⭐ Убрать" if saved else "⭐ В избранное",
                              callback_data=f"mss:save:{track_id}"),
         InlineKeyboardButton(text="➕ В плейлист", callback_data=f"mss:add:{track_id}")],
        [InlineKeyboardButton(text="✈️ Поделиться", switch_inline_query=f"track:{track_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=back)],
    ])


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
    await safe_edit(call, menu_text(), menu_kb())


@router.callback_query(F.data == "msc:noop")
async def noop(call) -> None:
    await call.answer()


@router.callback_query(F.data == "msc:ask")
async def ask_query(call, state) -> None:
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
    await safe_edit(call, menu_text(), menu_kb())


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
async def track_card(call, user: dict) -> None:
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
                    await track_kb(track_id, user))


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
    await call.answer()
    await safe_edit(call, "⭐ <b>Избранное</b>\n\n" + (_tracks_text(tracks) or "Пока пусто."),
                    _tracks_kb(tracks))


@router.callback_query(F.data == "msc:history")
async def history(call, user: dict) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    tracks = []
    for item in social.history_of(user)[:50]:
        track = await musicsearch.catalog_get(item["track_id"])
        if track:
            tracks.append({**track, "id": item["track_id"]})
    await storage.save(call.from_user.id)
    await call.answer()
    await safe_edit(call, "🕘 <b>История за 30 дней</b>\n\n" + (_tracks_text(tracks) or "Пока пусто."),
                    _tracks_kb(tracks))


@router.callback_query(F.data == "msc:random")
async def random_track(call, user: dict) -> None:
    if not _enabled():
        await call.answer("Поиск музыки отключён.", show_alert=True)
        return
    track = await social.random_track()
    await call.answer()
    if not track:
        await safe_edit(call, "Каталог пока пуст — сначала выполните поиск.", menu_kb())
        return
    await safe_edit(call, f"🎲 <b>{esc(track_label(track))}</b>",
                    await track_kb(track["id"], user))


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
