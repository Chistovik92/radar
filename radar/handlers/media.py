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

from .. import config, features, media, mediaquota, roles, storage, transcode
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
    """Загрузка открыта всем ролям с 4.7.3.

    Раньше она была привилегией: MEDIA_MIN_ROLE отсекал обычных
    пользователей. Ограничение перенесено с роли на квоту — двадцать
    роликов в сутки хватает для нормального пользования и не даёт
    превратить одноплатник в бесплатный перекодировщик.
    """
    return features.enabled("media_download")


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
        # Длительность нужна сжатию: битрейт под целевой размер считается
        # именно из неё.
        "duration": int(info.get("duration") or 0),
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


def _compression_offer(token: str, index: int, request: dict,
                       chosen: media.Format, limit_mb: int):
    """Предложение сжать. None — предлагать нечего, пусть идёт обычный путь.

    Отдельной функцией, чтобы решение «можно ли и сколько это займёт»
    проверялось без запуска бота.
    """
    if not features.enabled("media_transcode"):
        return None

    duration = int(request.get("duration") or 0)
    if duration <= 0:
        return None

    plan = transcode.plan(duration, limit_mb, chosen.height)
    if plan is None:
        # Длительность такова, что сжимать бессмысленно. Сказать правду
        # честнее, чем выдать нечитаемое видео.
        return (
            f"📏 {esc(transcode.too_long_message(duration, limit_mb))}",
            back_kb(),
        )

    spent = transcode.human_time(transcode.estimate_seconds(plan))
    text = (
        f"🗜 <b>Ролик не поместится: {chosen.size_mb:.0f} МБ при пределе "
        f"{limit_mb} МБ.</b>\n\n"
        f"Его можно сжать до {plan.height}p — получится примерно "
        f"{limit_mb} МБ.\n"
        f"Займёт <b>{spent}</b>: процессор одноплатника слабый, и сжатие "
        f"идёт с пониженным приоритетом, чтобы не задерживать оповещения.\n\n"
        f"<i>Можно и просто выбрать качество ниже — это мгновенно.</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗜 Сжать ({spent})",
                              callback_data=f"med:zip:{token}:{index}")],
        [InlineKeyboardButton(text="◀️ Выбрать другое качество",
                              callback_data=f"med:back:{token}")],
    ])
    return text, keyboard


@router.callback_query(F.data.startswith("med:get:"))
@router.callback_query(F.data.startswith("med:zip:"))
async def download(call: CallbackQuery, role: str, user: dict) -> None:
    # med:zip — тот же путь, но с последующим сжатием. Разделять их
    # раньше загрузки нельзя: решение влияет на то, ставить ли предел
    # размера самой загрузке (см. ниже).
    compress = call.data.startswith("med:zip:")
    quota = mediaquota.quota_of(user, role)
    if not quota.allowed(mediaquota.today()):
        await call.answer(
            f"Дневной предел исчерпан: {mediaquota.FREE_PER_DAY} видео. "
            "Лимит обновится завтра.",
            show_alert=True,
        )
        return
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

    limit_mb = media.size_limit_mb(config.uses_local_api())

    # Вариант крупнее предела: вместо отказа предлагаем сжать. Спрашиваем
    # ДО загрузки, потому что от ответа зависит, ставить ли ей предел
    # размера: для сжатия нужен полный исходник, а обычной загрузке
    # выкачивать заведомо лишнее незачем.
    if not compress and chosen.size_mb and chosen.size_mb > limit_mb:
        offer = _compression_offer(token, index, request, chosen, limit_mb)
        if offer is not None:
            await safe_edit(call, offer[0], offer[1])
            return

    if _slots.locked():
        await safe_edit(
            call,
            "⏳ Уже идёт другая загрузка. Дождитесь её завершения — "
            "одновременные скачивания перегружают сервер.",
            back_kb(),
        )
        return

    os.makedirs(config.MEDIA_DIR, exist_ok=True)

    # Место проверяем до начала: забитый диск на одноплатнике ломает
    # не загрузку видео, а весь бот — базе некуда писать, и оповещения
    # прекращаются. Ролик подождёт, тревоги нет.
    fits, complaint = media.enough_space(chosen.size_mb, config.MEDIA_DIR)
    if not fits:
        await safe_edit(call, f"💾 {esc(complaint)}", back_kb())
        return

    target = os.path.join(
        config.MEDIA_DIR, f"{request['title'][:40]}_{token}.%(ext)s"
    )
    progress = media.Progress()
    status = call.message

    async with _slots:
        try:
            # При сжатии предел загрузке не ставим: нужен полный исходник,
            # иначе обрывать его на половине — значит сжимать половину.
            path = await _run_download(
                request["url"], chosen, target, progress, status,
                limit_mb=0 if compress else limit_mb,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Скачивание не удалось: %s", exc)
            await _safe_text(status, f"❌ {esc(media.friendly_error(exc))}")
            return

        if not path or not os.path.exists(path):
            await _safe_text(status, "❌ Файл не сформирован.")
            return

        # Квоту тратим здесь: за неудачную загрузку человек платить
        # не должен, а до этой строки мы доходим только с готовым файлом.
        quota.spend(mediaquota.today())
        mediaquota.store_quota(user, quota)
        await storage.save()

        # Исходник запоминаем отдельно: после сжатия path указывает
        # на новый файл, и без этого исходный остался бы на диске —
        # то есть ровно та беда, от которой мы бережём одноплатник.
        source_path = path
        shrunk = ""
        try:
            if compress:
                shrunk, complaint = await _run_transcode(
                    path, request, chosen, limit_mb, status
                )
                if not shrunk:
                    await _safe_text(status, f"❌ {esc(complaint)}")
                    return
                path = shrunk

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
            # Диск одноплатника кончается быстро — убираем сразу и оба
            # файла: исходник и сжатый.
            for leftover in {source_path, shrunk, path}:
                if not leftover:
                    continue
                try:
                    os.remove(leftover)
                except OSError:
                    pass
            _pending.pop(token, None)


async def _run_transcode(source: str, request: dict, chosen: media.Format,
                         limit_mb: int, status: Message) -> tuple[str, str]:
    """Сжимает скачанный файл. Возвращает (путь, объяснение отказа)."""
    duration = int(request.get("duration") or 0)
    plan = transcode.plan(duration, limit_mb, chosen.height)
    if plan is None:
        return "", transcode.too_long_message(duration, limit_mb)

    target = f"{os.path.splitext(source)[0]}_small.mp4"
    spent = transcode.human_time(transcode.estimate_seconds(plan))
    loop = asyncio.get_running_loop()
    last = 0.0

    def on_progress(share: float) -> None:
        # Правим сообщение не чаще раза в несколько процентов: сжатие идёт
        # минутами, а Telegram ограничивает частоту правок.
        nonlocal last
        if share - last < 0.05 and share < 1.0:
            return
        last = share
        asyncio.run_coroutine_threadsafe(
            _safe_text(
                status,
                f"🗜 <b>Сжимаю до {plan.height}p</b> — {share * 100:.0f}%\n"
                f"<i>Всего {spent}. Оповещения при этом идут как обычно.</i>",
            ),
            loop,
        )

    await _safe_text(
        status,
        f"🗜 <b>Сжимаю до {plan.height}p</b>\n"
        f"<i>Займёт {spent}. Оповещения при этом идут как обычно.</i>",
    )

    done, complaint = await transcode.run(
        source, target, plan,
        timeout_s=config.TRANSCODE_TIMEOUT,
        on_progress=on_progress,
    )
    if not done:
        try:
            os.remove(target)
        except OSError:
            pass
        return "", complaint
    return target, ""


@router.callback_query(F.data.startswith("med:back:"))
async def back_to_formats(call: CallbackQuery) -> None:
    """Возврат к выбору качества из предложения сжать."""
    token = call.data.split(":")[2]
    request = _pending.get(token)
    if request is None:
        await call.answer("Запрос устарел — пришлите ссылку заново.", show_alert=True)
        return
    await call.answer()
    limit_mb = media.size_limit_mb(config.uses_local_api())
    await safe_edit(
        call,
        "🎯 <b>Выберите качество:</b>",
        _keyboard(token, request["formats"], limit_mb),
    )


async def _run_download(url: str, chosen: media.Format, target: str,
                        progress: media.Progress, status: Message,
                        *, limit_mb: int = 0) -> str | None:
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

    # Предел передаём и в выбор формата, и в саму загрузку: первое
    # отсеивает заведомо неподходящие варианты, второе обрывает загрузку,
    # если размер выяснился только по ходу дела. При сжатии предел равен
    # нулю — исходник нужен целиком.
    options = media.build_options(
        target,
        chosen.selector_for(limit_mb),
        proxy=config.EGRESS_PROXY,
        cookies=config.MEDIA_COOKIES,
        limit_rate=config.MEDIA_RATE_LIMIT,
        limit_mb=limit_mb,
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


@router.callback_query(F.data == "med:menu")
async def menu_media(call: CallbackQuery, role: str, user: dict) -> None:
    """Вход из главного меню. Раньше сюда попадали только командой /media,
    о которой надо было знать заранее."""
    if not features.enabled("media_download"):
        await call.answer("Загрузка видео отключена.", show_alert=True)
        return
    if not _allowed(role):
        await call.answer("Загрузка видео доступна с другой ролью.", show_alert=True)
        return

    await call.answer()
    limit = media.size_limit_mb(config.uses_local_api())
    server = "собственный Bot API Server" if config.uses_local_api() else "api.telegram.org"
    quota = mediaquota.quota_of(user, role)
    await safe_edit(
        call,
        "🎬 <b>Загрузка видео</b>\n\n"
        "Пришлите ссылку — предложу выбрать качество и пришлю файл.\n\n"
        f"<b>{mediaquota.describe(quota)}</b>\n"
        f"<b>Площадки:</b> {media.SUPPORTED_HINT}\n"
        f"<b>Предел отправки:</b> {limit} МБ ({server})\n\n"
        "<i>Скачивайте только то, на что у вас есть право: правила площадок "
        "и авторские права никто не отменял.</i>",
        _quota_keyboard(quota),
    )


# --------------------------------------------------------------------------
#  Подписка на безлимит (с 4.7.3)
# --------------------------------------------------------------------------

def _quota_keyboard(quota) -> InlineKeyboardMarkup:
    rows = []
    if not quota.unlimited:
        rows.append([InlineKeyboardButton(
            text=f"⭐️ Безлимит на месяц — {mediaquota.STARS_PRICE}",
            callback_data="med:buy",
        )])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню",
                                      callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "med:buy")
async def buy_unlimited(call: CallbackQuery, user: dict, role: str) -> None:
    from aiogram.types import LabeledPrice

    quota = mediaquota.quota_of(user, role)
    if quota.unlimited:
        await call.answer(
            f"Безлимит уже активен, осталось дней: {quota.days_left}",
            show_alert=True,
        )
        return

    await call.answer()
    try:
        await call.message.answer_invoice(
            title=f"Загрузка видео без лимита — {mediaquota.SUBSCRIPTION_DAYS} дней",
            description=(
                f"Снимает дневной предел в {mediaquota.FREE_PER_DAY} видео "
                "и открывает новостные подборки: подписка одна на всё.\n\n"
                "Предел размера файла в 50 МБ остаётся: это ограничение "
                "Telegram, а не наше решение, и подпиской оно не снимается."
            ),
            payload=f"media:{mediaquota.SUBSCRIPTION_DAYS}",
            currency="XTR",
            prices=[LabeledPrice(
                label=f"{mediaquota.SUBSCRIPTION_DAYS} дней",
                amount=mediaquota.STARS_PRICE,
            )],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Счёт за видео не выставлен: %s", exc)
        await call.message.answer("❌ Не удалось выставить счёт. Попробуйте позже.",
                                  reply_markup=back_kb())


async def apply_media_payment(message, user: dict, payload: str,
                              role: str = "user") -> None:
    """Зачислить оплаченный безлимит. Зовётся из общего обработчика платежей."""
    try:
        days = int(payload.split(":", 1)[1])
    except (IndexError, ValueError):
        log.warning("Непонятный платёж за видео: %s", payload)
        return

    quota = mediaquota.quota_of(user, role)
    quota.extend(days)
    mediaquota.store_quota(user, quota)
    await storage.save()

    await message.answer(
        f"✅ Безлимит включён на {days} дней.\n\n"
        f"Дневной предел снят. Размер файла по-прежнему до "
        f"{media.size_limit_mb(config.uses_local_api())} МБ — это ограничение "
        "Telegram, снять его подпиской нельзя.",
        reply_markup=back_kb(),
    )
