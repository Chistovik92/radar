"""Загрузка видео по ссылке в интерфейсе бота.

Роутер подключается перед ассистентом, но после всех остальных: ссылку
надо перехватить раньше, чем текст уйдёт в свободный диалог с моделью.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import config, features, media, roles
from ..textutils import esc
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.media")
router = Router(name="media")

# Одновременных загрузок: на одноплатнике вторая параллельная задача
# отбирает процессор у фонового мониторинга.
_slots = asyncio.Semaphore(config.MEDIA_CONCURRENCY)

# Разобранные ссылки: ключ короткий, потому что callback_data ограничен
# 64 байтами и целый URL туда не помещается.
_pending: dict[str, dict] = {}
_PENDING_TTL = 900


def _allowed(role: str) -> bool:
    if not features.enabled("media_download"):
        return False
    return roles.at_least(role, config.MEDIA_MIN_ROLE)


def _cleanup_pending() -> None:
    edge = time.time() - _PENDING_TTL
    for key in [key for key, item in _pending.items() if item["created"] < edge]:
        _pending.pop(key, None)


def _keyboard(token: str, formats: list[media.Format], limit_mb: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(formats):
        mark = ""
        if item.size_mb and item.size_mb > limit_mb:
            mark = " ⚠️"
        rows.append([
            InlineKeyboardButton(
                text=f"{item.title}{mark}", callback_data=f"med:get:{token}:{index}"
            )
        ])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"med:drop:{token}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------
#  Приём ссылки
# --------------------------------------------------------------------------

@router.message(StateFilter(None), F.text.func(media.looks_like_url))
async def handle_link(message: Message, role: str) -> None:
    if not _allowed(role):
        return  # ссылка уйдёт дальше по цепочке роутеров

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        await message.answer(
            "❌ Загрузка видео недоступна: в образе нет yt-dlp.\n"
            "<i>Пересоберите образ: docker compose build --no-cache</i>"
        )
        return

    url = (message.text or "").strip()
    notice = await message.answer("🔎 <b>Смотрю, что за ссылка…</b>")

    try:
        info = await asyncio.wait_for(_probe(url), timeout=90)
    except asyncio.TimeoutError:
        await notice.edit_text("❌ Площадка не ответила за 90 секунд.")
        return
    except Exception as exc:  # noqa: BLE001
        log.warning("Разбор ссылки не удался: %s", exc)
        await notice.edit_text(f"❌ {esc(media.friendly_error(exc))}")
        return

    formats = media.parse_formats(info)
    limit_mb = media.size_limit_mb(config.uses_local_api())

    _cleanup_pending()
    token = uuid.uuid4().hex[:10]
    _pending[token] = {
        "url": url,
        "formats": formats,
        "title": media.safe_filename(str(info.get("title") or "video")),
        "owner": message.from_user.id,
        "created": time.time(),
    }

    lines = [media.describe(info), "", "🎯 <b>Выберите качество:</b>"]
    if not config.uses_local_api():
        lines.append(
            f"<i>Предел отправки — {limit_mb} МБ. Отмеченные ⚠️ варианты "
            "не поместятся.</i>"
        )
    await notice.edit_text("\n".join(lines), reply_markup=_keyboard(token, formats, limit_mb))


async def _probe(url: str) -> dict:
    """Метаданные без скачивания. yt-dlp синхронный — уводим в поток."""
    import yt_dlp

    options = media.probe_options(config.EGRESS_PROXY, config.MEDIA_COOKIES)

    def worker() -> dict:
        with yt_dlp.YoutubeDL(options) as downloader:
            return downloader.extract_info(url, download=False) or {}

    return await asyncio.to_thread(worker)


# --------------------------------------------------------------------------
#  Скачивание
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("med:drop:"))
async def drop_request(call: CallbackQuery) -> None:
    _pending.pop(call.data.split(":")[2], None)
    await call.answer("Отменено")
    await safe_edit(call, "Загрузка отменена.", back_kb())


@router.callback_query(F.data.startswith("med:get:"))
async def download(call: CallbackQuery, role: str) -> None:
    if not _allowed(role):
        await call.answer("Функция недоступна.", show_alert=True)
        return

    parts = call.data.split(":")
    token, index = parts[2], int(parts[3])
    request = _pending.get(token)

    if request is None:
        await call.answer("Запрос устарел — пришлите ссылку заново.", show_alert=True)
        return
    if request["owner"] != call.from_user.id:
        await call.answer("Это чужой запрос.", show_alert=True)
        return
    if index >= len(request["formats"]):
        await call.answer("Вариант недоступен.", show_alert=True)
        return

    chosen: media.Format = request["formats"][index]
    await call.answer(f"Качество: {chosen.label}")

    if _slots.locked():
        await safe_edit(
            call,
            "⏳ Уже идёт другая загрузка. Дождитесь её завершения — "
            "одновременные скачивания перегружают сервер.",
            back_kb(),
        )
        return

    os.makedirs(config.MEDIA_DIR, exist_ok=True)
    target = os.path.join(
        config.MEDIA_DIR, f"{request['title'][:40]}_{token}.%(ext)s"
    )
    progress = media.Progress()
    status = call.message

    async with _slots:
        try:
            path = await _run_download(request["url"], chosen, target, progress, status)
        except Exception as exc:  # noqa: BLE001
            log.warning("Скачивание не удалось: %s", exc)
            await _safe_text(status, f"❌ {esc(media.friendly_error(exc))}")
            return

        if not path or not os.path.exists(path):
            await _safe_text(status, "❌ Файл не сформирован.")
            return

        try:
            size = os.path.getsize(path)
            oversize, reason = media.too_big(size, config.uses_local_api())
            if oversize:
                await _safe_text(status, f"⚠️ {esc(reason)}")
                return

            await _safe_text(status, "📤 <b>Отправляю в Telegram…</b>")
            await call.message.answer_video(
                FSInputFile(path),
                caption=f"✅ {esc(request['title'])}\n<i>Качество: {chosen.label}</i>",
                supports_streaming=True,
                request_timeout=1800,
            )
            try:
                await status.delete()
            except TelegramBadRequest:
                pass
        finally:
            # Диск одноплатника кончается быстро — убираем сразу
            try:
                os.remove(path)
            except OSError:
                pass
            _pending.pop(token, None)


async def _run_download(url: str, chosen: media.Format, target: str,
                        progress: media.Progress, status: Message) -> str | None:
    """Скачивание в потоке с передачей прогресса в чат."""
    import yt_dlp

    loop = asyncio.get_running_loop()
    result: dict[str, str] = {}

    def hook(payload: dict) -> None:
        # Хук вызывается в рабочем потоке десятки раз в секунду; правку
        # сообщения планируем в основном цикле и только по таймеру.
        if media.read_hook(payload, progress):
            asyncio.run_coroutine_threadsafe(
                _safe_text(status, progress.render()), loop
            )
        if payload.get("status") == "finished":
            filename = payload.get("filename")
            if filename:
                result["path"] = filename

    options = media.build_options(
        target,
        chosen.selector,
        proxy=config.EGRESS_PROXY,
        cookies=config.MEDIA_COOKIES,
        limit_rate=config.MEDIA_RATE_LIMIT,
    )
    options["progress_hooks"] = [hook]

    def worker() -> str | None:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if info:
                return downloader.prepare_filename(info)
        return None

    path = await asyncio.to_thread(worker)

    # После склейки расширение меняется на mp4 — берём то, что есть на диске
    for candidate in (path, result.get("path")):
        if candidate and os.path.exists(candidate):
            return candidate
    if path:
        merged = os.path.splitext(path)[0] + ".mp4"
        if os.path.exists(merged):
            return merged
    return None


async def _safe_text(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except TelegramBadRequest:
        pass  # «message is not modified» и подобное — не повод падать
    except Exception:  # noqa: BLE001
        log.debug("Не удалось обновить сообщение прогресса", exc_info=True)


# --------------------------------------------------------------------------
#  Справка
# --------------------------------------------------------------------------

@router.message(Command("media"))
async def cmd_media(message: Message, role: str) -> None:
    if not features.enabled("media_download"):
        await message.answer("Загрузка видео отключена суперадминистратором.")
        return
    if not _allowed(role):
        await message.answer("⛔️ Загрузка видео доступна начиная с другой роли.")
        return

    limit = media.size_limit_mb(config.uses_local_api())
    server = "собственный Bot API Server" if config.uses_local_api() else "api.telegram.org"
    await message.answer(
        "🎬 <b>Загрузка видео</b>\n\n"
        "Пришлите ссылку — предложу выбрать качество и пришлю файл.\n\n"
        f"<b>Площадки:</b> {media.SUPPORTED_HINT}\n"
        f"<b>Предел отправки:</b> {limit} МБ ({server})\n\n"
        "<i>Скачивайте только то, на что у вас есть право: правила площадок "
        "и авторские права никто не отменял.</i>",
        reply_markup=back_kb(),
    )
