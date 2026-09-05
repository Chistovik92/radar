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

from .. import (
    config,
    features,
    i18n,
    identity,
    images,
    media,
    mediaquota,
    roles,
    storage,
    subscription,
    transcode,
)
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


def _keyboard(token: str, formats: list[media.Format], limit_mb: int,
              has_text: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
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
    if has_text:
        rows.append([InlineKeyboardButton(
            text=i18n.t("media.btn_text", lang, "📝 Текст описания"),
            callback_data=f"med:txt:{token}")])
    rows.append([InlineKeyboardButton(
        text=i18n.t("media.btn_cancel", lang, "❌ Отмена"),
        callback_data=f"med:drop:{token}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------
#  Приём ссылки
# --------------------------------------------------------------------------

@router.message(StateFilter(None), F.text.func(media.looks_like_url))
async def handle_link(message: Message, role: str, user: dict) -> None:
    if not _allowed(role):
        return  # ссылка уйдёт дальше по цепочке роутеров

    lang = i18n.language_of(user)

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        await message.answer(
            "❌ Загрузка видео недоступна: в образе нет yt-dlp.\n"
            "<i>Пересоберите образ: docker compose build --no-cache</i>"
        )
        return

    url = (message.text or "").strip()

    # Картинка перехватывается раньше: гнать её через yt-dlp значило бы
    # обвешать простую задачу выбором качества и склейкой.
    if images.looks_like_image(url):
        await _send_image(message, url, user)
        return

    notice = await message.answer(
        i18n.t("media.looking", lang, "🔎 <b>Смотрю, что за ссылка…</b>")
    )

    try:
        info = await asyncio.wait_for(_probe(url), timeout=90)
    except asyncio.TimeoutError:
        await notice.edit_text(
            i18n.t("media.slow_probe", lang, "❌ Площадка не ответила за 90 секунд.")
        )
        return
    except Exception as exc:  # noqa: BLE001
        log.warning("Разбор ссылки не удался: %s", exc)
        # «Видео тут нет» — не всегда отказ. Люди присылают ссылку
        # на запись с картинками: пост в Instagram, твит с фотографией,
        # сообщение сообщества YouTube. До 4.8.4.7 человек получал
        # «не удалось обработать ссылку» и не понимал, что делать.
        if media.looks_like_no_video(exc) and await _send_post_images(
                message, url, notice):
            return
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
        # Метаданные держим целиком: из них берётся текст описания.
        # Живут не дольше самого запроса — четверть часа.
        "info": info,
    }

    lines = [media.describe(info), "",
             i18n.t("media.pick_quality", lang, "🎯 <b>Выберите качество:</b>")]
    if not config.uses_local_api():
        lines.append(
            i18n.t(
                "media.pick_note", lang,
                f"<i>Предел отправки — {limit_mb} МБ. Отмеченные ⚠️ варианты "
                "не поместятся.</i>",
            ).replace("{limit}", str(limit_mb))
        )
    await notice.edit_text(
        "\n".join(lines),
        reply_markup=_keyboard(token, formats, limit_mb,
                               has_text=bool(images.description_of(info)),
                               lang=lang),
    )


async def post_images(message: Message, url: str, user: dict | None = None) -> None:
    """Картинки из записи — прямой путь, мимо yt-dlp.

    До 4.9.4.3 до них можно было добраться только «наугад»: yt-dlp
    сначала тратил до 90 секунд на пробу записи и лишь потом, не найдя
    видео, бот искал картинки. Из выбора ссылки и из медиа-меню теперь
    идёт сразу сюда.
    """
    lang = i18n.language_of(user)
    notice = await message.answer(
        i18n.t("img.looking", lang, "🖼 <b>Ищу картинки в записи…</b>")
    )
    found = await _send_post_images(message, url, notice)
    if not found:
        try:
            await notice.edit_text(
                i18n.t(
                    "img.none_found", lang,
                    "🖼 В этой записи не нашлось картинок.\n"
                    "<i>Закрытая запись не покажет их и браузеру без входа.</i>",
                )
            )
        except TelegramBadRequest:
            pass


async def _send_post_images(message: Message, url: str, notice) -> bool:
    """Картинки из записи, в которой нет видео. False — не вышло.

    Разбор идёт по метаданным страницы и по встроенному JSON: первые дают
    главную картинку, второй — остальные снимки карусели. Способ
    не всесильный — закрытая запись отдаёт страницу входа, и картинок
    в ней не будет. Тогда возвращаем False, и человек увидит объяснение.
    """
    import aiohttp
    from aiogram.types import BufferedInputFile, InputMediaPhoto

    owner = storage.get_user(message.from_user.id)
    lang = i18n.language_of(owner)
    await notice.edit_text(
        i18n.t("img.looking", lang, "🖼 <b>Ищу картинки в записи…</b>")
    )

    # Обычный User-Agent, а не наш: метаданные предпросмотра площадки
    # отдают браузерам и краулерам, а незнакомому агенту нередко
    # показывают страницу входа.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; RadarBot/1.0; "
            "+https://github.com/Chistovik92/radar)"
        ),
        "Accept-Language": "ru,en;q=0.8",
    }
    timeout = aiohttp.ClientTimeout(total=90)
    limit_mb = media.size_limit_mb(config.uses_local_api())

    photos: list[tuple[bytes, str]] = []
    heavy: list[tuple[bytes, str]] = []

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        markup = await images.fetch_page(session, url)
        links = images.from_page(markup, url)
        if not links:
            return False

        for link in links:
            data, _complaint = await images.fetch(session, link, limit_mb)
            if not data:
                continue
            name = images.filename_from(link)
            # Крупная картинка альбомом не уходит: у фотографий свой
            # предел в 10 МБ. Такие отправляем отдельно, файлом.
            (photos if images.as_photo(len(data)) else heavy).append((data, name))

    if not photos and not heavy:
        return False

    sent = 0
    # Альбомом, а не вереницей сообщений: карусель из десяти снимков
    # десятью сообщениями превращает переписку в ленту. Telegram берёт
    # не больше десяти вложений за раз.
    for start in range(0, len(photos), 10):
        chunk = photos[start:start + 10]
        try:
            if len(chunk) == 1:
                data, name = chunk[0]
                await message.answer_photo(
                    BufferedInputFile(data, filename=name),
                    caption=f"🖼 {esc(name)}",
                )
            else:
                await message.answer_media_group([
                    InputMediaPhoto(
                        media=BufferedInputFile(data, filename=name),
                        caption=(f"🖼 Картинок в записи: {len(photos)}"
                                 if index == 0 and start == 0 else None),
                    )
                    for index, (data, name) in enumerate(chunk)
                ])
            sent += len(chunk)
        except Exception:  # noqa: BLE001
            log.warning("Альбом не отправлен, шлю по одной")
            for data, name in chunk:
                try:
                    await message.answer_photo(
                        BufferedInputFile(data, filename=name),
                        caption=f"🖼 {esc(name)}",
                    )
                    sent += 1
                except Exception:  # noqa: BLE001
                    log.warning("Картинка из записи не отправлена: %s", name)
                await asyncio.sleep(0.3)
        await asyncio.sleep(0.3)

    for data, name in heavy:
        try:
            await message.answer_document(
                BufferedInputFile(data, filename=name),
                caption=f"🖼 {esc(name)} · {len(data) / 1024 / 1024:.1f} МБ",
            )
            sent += 1
        except Exception:  # noqa: BLE001
            log.warning("Крупная картинка не отправлена: %s", name)
        await asyncio.sleep(0.3)

    if not sent:
        return False
    try:
        await notice.delete()
    except TelegramBadRequest:
        pass
    log.info("Из записи отправлено картинок: %d", sent)
    return True



async def _send_image(message: Message, url: str, user: dict | None = None) -> None:
    """Скачивает картинку и отдаёт её фотографией или документом."""
    import aiohttp
    from aiogram.types import BufferedInputFile

    lang = i18n.language_of(user)
    notice = await message.answer(
        i18n.t("img.downloading", lang, "🖼 <b>Скачиваю картинку…</b>")
    )
    limit_mb = media.size_limit_mb(config.uses_local_api())

    timeout = aiohttp.ClientTimeout(total=120)
    headers = {"User-Agent": config.USER_AGENT}
    connector = None
    async with aiohttp.ClientSession(timeout=timeout, headers=headers,
                                     connector=connector) as session:
        data, complaint = await images.fetch(session, url, limit_mb)

    if not data:
        await notice.edit_text(f"❌ {esc(complaint)}")
        return

    name = images.filename_from(url)
    size_mb = len(data) / 1024 / 1024
    file = BufferedInputFile(data, filename=name)

    try:
        if images.as_photo(len(data)):
            await message.answer_photo(file, caption=f"🖼 {esc(name)}")
        else:
            # Крупнее 10 МБ фотографией не уходит — отдаём документом.
            # Откроется так же, просто без предпросмотра в ленте.
            await message.answer_document(
                file,
                caption=f"🖼 {esc(name)} · {size_mb:.1f} МБ\n"
                        f"<i>Крупные картинки Telegram принимает только "
                        f"файлом, без предпросмотра.</i>",
            )
        try:
            await notice.delete()
        except TelegramBadRequest:
            pass
    except Exception as exc:  # noqa: BLE001
        log.warning("Картинка не отправлена: %s", exc)
        await notice.edit_text(
            i18n.t("img.not_sent", lang, "❌ Картинку скачал, но отправить не удалось.")
        )


@router.callback_query(F.data.startswith("med:txt:"))
async def send_description(call: CallbackQuery) -> None:
    """Текст описания публикации отдельным сообщением."""
    token = call.data.split(":")[2]
    request = _pending.get(token)
    if request is None:
        await call.answer("Запрос устарел — пришлите ссылку заново.", show_alert=True)
        return
    await call.answer()
    await call.message.answer(images.format_description(request.get("info") or {}))


async def _probe(url: str) -> dict:
    """Метаданные без скачивания. yt-dlp синхронный — уводим в поток."""
    import yt_dlp

    from .. import secrets as secrets_module

    cookies = (secrets_module.get("MEDIA_COOKIES") or config.MEDIA_COOKIES).strip()
    options = media.probe_options(config.EGRESS_PROXY, cookies)

    def worker() -> dict:
        with yt_dlp.YoutubeDL(options) as downloader:
            return downloader.extract_info(url, download=False) or {}

    return await asyncio.to_thread(worker)


# --------------------------------------------------------------------------
#  Cookies для закрытых площадок (с 4.9.4.5)
# --------------------------------------------------------------------------

@router.message(Command("cookies"))
async def cookies_help(message: Message, role: str) -> None:
    """Инструкция и состояние файла cookies."""
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Управление cookies — суперадминистратору.")
        return

    from .. import cookies as cookies_module

    await message.answer(
        "🍪 <b>Cookies для закрытых записей</b>\n\n"
        f"{cookies_module.describe()}\n\n"
        "Записи «закрыта настройками приватности» и с возрастным "
        "ограничением открываются только с cookies вошедшего человека.\n\n"
        "<b>Как подключить:</b>\n"
        "1. В браузере: расширение «Get cookies.txt LOCALLY» "
        "(Chrome/Firefox) — Export — для нужной площадки.\n"
        "2. Пришлите файл <code>cookies.txt</code> сюда сообщением.\n\n"
        "<i>Файл держит сессию аккаунта: у кого он есть — тот вошёл. "
        "Не пересылайте его никому.</i>",
        reply_markup=back_kb(),
    )


@router.message(F.document)
async def take_cookies(message: Message, role: str) -> None:
    """Приём файла cookies прямо в чат.

    До 4.9.4.5 файл требовалось принести на сервер SCP-ом и прописать
    путь в .env руками. Формат проверяется до сохранения: мусор в нём
    превращал бы отказы yt-dlp в загадки.
    """
    if not roles.is_superadmin(role):
        return  # чужой документ — не наше дело, пусть идёт дальше

    document = message.document
    if not document or not document.file_name:
        return
    if not document.file_name.lower().endswith(".txt"):
        return
    if "cookie" not in document.file_name.lower():
        # Любой .txt документов может быть чем угодно — ловим только
        # похожее на cookies по имени, иначе перехватили бы чужие файлы.
        return

    from .. import cookies as cookies_module

    if document.file_size and document.file_size > cookies_module.MAX_BYTES:
        await message.answer(
            "❌ Файл слишком большой для выгрузки cookies "
            f"({cookies_module.MAX_BYTES // 1024} КБ)."
        )
        return

    try:
        file = await message.bot.get_file(document.file_id)
        data = await message.bot.download_file(file.file_path)
        payload = data.read() if data else b""
    except Exception as exc:  # noqa: BLE001
        log.warning("Файл cookies не скачан: %s", exc)
        await message.answer("❌ Не удалось скачать файл. Попробуйте ещё раз.")
        return

    ok, complaint = await asyncio.to_thread(cookies_module.store, payload)
    if not ok:
        await message.answer(f"❌ Файл не принят: {esc(complaint)}")
        return

    log.info("Файл cookies загружен суперадминистратором")
    await message.answer(
        "✅ <b>Cookies подключены.</b>\n"
        "Закрытые записи и записи с возрастным ограничением откроются "
        "при следующей загрузке — присылайте ссылку заново.\n\n"
        "<i>Файл держит сессию аккаунта и хранится с правами 600.</i>",
        reply_markup=back_kb(),
    )


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
    """Стена размера: сжать или полная версия по ссылке. None — нечего предлагать.

    Отдельной функцией, чтобы решение «можно ли и сколько это займёт»
    проверялось без запуска бота.

    С 4.9.3 выбор честный и полный: бесплатный путь — сжать и попытаться
    уместиться в предел; премиум — полная версия по ссылке до 5 ГБ
    на сутки. Раньше предлагалось только сжатие, а ссылка выдавалась
    всем без подписки уже после загрузки: платная часть не продавалась
    там, где человек упирается в неё лбом.
    """
    if not features.enabled("media_transcode"):
        return None

    from .. import filedrop

    duration = int(request.get("duration") or 0)

    premium_rows = []
    if filedrop.enabled():
        premium_rows.append([InlineKeyboardButton(
            text=f"⭐️ Полная версия по ссылке — до "
                 f"{filedrop.MAX_FILE_MB // 1024} ГБ",
            callback_data=f"med:full:{token}:{index}",
        )])

    if duration <= 0:
        if not premium_rows:
            return None
        return (
            f"📏 <b>Ролик длиннее, чем можно отправить файлом "
            f"({limit_mb} МБ), и сжать его нечем.</b>\n\n"
            f"По подписке полную версию можно забрать ссылкой — "
            f"до {filedrop.MAX_FILE_MB // 1024} ГБ, живёт "
            f"{filedrop.TTL_HOURS} ч.",
            InlineKeyboardMarkup(inline_keyboard=premium_rows + [[
                InlineKeyboardButton(text="◀️ Выбрать другое качество",
                                     callback_data=f"med:back:{token}")
            ]]),
        )

    plan = transcode.plan(duration, limit_mb, chosen.height)
    if plan is None:
        # Длительность такова, что сжимать бессмысленно. Сказать правду
        # честнее, чем выдать нечитаемое видео.
        if not premium_rows:
            return (
                f"📏 {esc(transcode.too_long_message(duration, limit_mb))}",
                back_kb(),
            )
        return (
            f"📏 <b>{esc(transcode.too_long_message(duration, limit_mb))}</b>\n\n"
            f"По подписке полную версию можно забрать ссылкой — до "
            f"{filedrop.MAX_FILE_MB // 1024} ГБ, живёт {filedrop.TTL_HOURS} ч.",
            InlineKeyboardMarkup(inline_keyboard=premium_rows + [[
                InlineKeyboardButton(text="◀️ Выбрать другое качество",
                                     callback_data=f"med:back:{token}")
            ]]),
        )

    spent = transcode.human_time(transcode.estimate_seconds(plan))
    rows = [[InlineKeyboardButton(text=f"🗜 Сжать до {plan.height}p ({spent}) — бесплатно",
                                  callback_data=f"med:zip:{token}:{index}")]]
    rows.extend(premium_rows)
    rows.append([InlineKeyboardButton(text="◀️ Выбрать другое качество",
                                      callback_data=f"med:back:{token}")])
    text = (
        f"🗜 <b>Ролик не поместится: {chosen.size_mb:.0f} МБ при пределе "
        f"{limit_mb} МБ.</b>\n\n"
        f"Бесплатно: сжать до {plan.height}p — получится примерно "
        f"{limit_mb} МБ, займёт <b>{spent}</b> — процессор одноплатника "
        f"слабый, и сжатие идёт с пониженным приоритетом, чтобы не "
        f"задерживать оповещения.\n\n"
    )
    if premium_rows:
        text += (
            f"По подписке: полная версия ссылкой — до "
            f"{filedrop.MAX_FILE_MB // 1024} ГБ, живёт "
            f"{filedrop.TTL_HOURS} ч.\n\n"
        )
    text += "<i>Можно и просто выбрать качество ниже — это мгновенно.</i>"
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("med:get:"))
@router.callback_query(F.data.startswith("med:zip:"))
@router.callback_query(F.data.startswith("med:full:"))
async def download(call: CallbackQuery, role: str, user: dict) -> None:
    # med:zip — тот же путь, но с последующим сжатием. Разделять их
    # раньше загрузки нельзя: решение влияет на то, ставить ли предел
    # размера самой загрузке (см. ниже).
    # med:full — полная версия по ссылке: путь подписки, предел
    # загрузке не ставится вовсе, файл уходит в раздачу.
    compress = call.data.startswith("med:zip:")
    full = call.data.startswith("med:full:")
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

    # Полная версия — часть подписки. Кнопка ведёт сюда и без подписки:
    # место, где человек упёрся в размер, — лучшая точка продажи,
    # и здесь же честно говорится, что именно открывается.
    if full and not subscription.active(user, role):
        from .. import filedrop

        await safe_edit(
            call,
            "⭐️ <b>Полная версия — по подписке</b>\n\n"
            f"Файл целиком, качеством {esc(chosen.label)}, ссылкой — "
            f"до {filedrop.MAX_FILE_MB // 1024} ГБ на "
            f"{filedrop.TTL_HOURS} ч.\n\n"
            "Подписка открывает это и загрузку видео без дневного "
            "предела, и все тематики новостных подборок. Оповещения "
            "об опасности бесплатны всегда.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оформить подписку",
                                      callback_data="sub:menu")],
                [InlineKeyboardButton(text="◀️ Выбрать другое качество",
                                      callback_data=f"med:back:{token}")],
            ]),
        )
        return

    # Вариант крупнее предела: вместо отказа предлагаем сжать. Спрашиваем
    # ДО загрузки, потому что от ответа зависит, ставить ли ей предел
    # размера: для сжатия нужен полный исходник, а обычной загрузке
    # выкачивать заведомо лишнее незачем.
    if not compress and not full and chosen.size_mb and chosen.size_mb > limit_mb:
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
                limit_mb=0 if (compress or full) else limit_mb,
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
                # Предел Telegram не обходим, а объезжаем: файл уже скачан,
                # и если у системы есть внешний адрес — тот же, на котором
                # открыта панель, — человек заберёт его по ссылке. Раньше
                # разговор заканчивался советом «выберите качество ниже»,
                # которого может не существовать.
                if await _offer_link(call, status, path, request, user, role):
                    # Файл переехал в раздачу — удалять его в finally
                    # нельзя. Обнуляем ОБА имени: после сжатия исходник
                    # и отправляемое различаются, а до сжатия совпадают,
                    # и уборка унесла бы файл прямо из-под ссылки.
                    if source_path == path:
                        source_path = ""
                    path = ""
                    return
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


async def _offer_link(call: CallbackQuery, status: Message, path: str,
                      request: dict, user: dict, role: str) -> bool:
    """Отдаёт скачанный файл ссылкой. False — нечем, обычный отказ.

    Условие одно: человек должен быть пользователем бота. Оно выполняется
    самим фактом переписки — ссылку выдаёт бот в ответ на нажатие, — но
    проверяем явно: заблокированному отдавать файлы незачем.

    С 4.9.3 ссылка — часть подписки: до этого она выдавалась всем,
    и платная часть не продавалась именно там, где человек упирается
    в неё лбом. Без подписки показываем предложение оформить её —
    и возвращаем False, чтобы файл убрался с диска: держать гигабайт
    в ожидании оплаты никто не станет.
    """
    from .. import filedrop

    if not filedrop.enabled():
        return False

    owner = storage.get_user(call.from_user.id)
    if owner is None or owner.get("blocked"):
        return False

    if not subscription.active(user, role):
        await _safe_text(
            status,
            f"⚠️ <b>Файл больше предела Telegram.</b>\n\n"
            f"По подписке его можно забрать целиком — ссылкой до "
            f"{filedrop.MAX_FILE_MB // 1024} ГБ на {filedrop.TTL_HOURS} ч.\n\n"
            "Подписка открывает это и загрузку видео без дневного "
            "предела, и все тематики подборок.",
            InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💳 Оформить подписку",
                                     callback_data="sub:menu"),
            ]]),
        )
        return False

    # Предел одной ссылки. Подписка его не снимает: она про доступ
    # к возможности, а не про место на диске. Пятигигабайтный файл занял
    # бы весь бюджет раздачи один, и следующему человеку места бы не было.
    try:
        if filedrop.too_large(os.path.getsize(path)):
            await _safe_text(
                status,
                f"⚠️ Файл больше {filedrop.MAX_FILE_MB // 1024} ГБ — "
                f"по ссылке такие не отдаём. Выберите качество ниже.",
            )
            return True
    except OSError:
        return False

    await _safe_text(status, "🔗 <b>Готовлю ссылку для скачивания…</b>")
    drop = await asyncio.to_thread(
        filedrop.store,
        path,
        media.safe_filename(str(request.get("title") or "video")),
        identity.make("telegram", str(call.from_user.id)).key,
    )
    if drop is None:
        return False

    await _safe_text(
        status,
        "\n".join([
            f"📦 <b>{esc(request['title'])}</b>",
            f"Размер: <b>{drop.size_mb:.0f} МБ</b> — больше предела "
            f"Telegram, поэтому файл отдан ссылкой.",
            "",
            f'<a href="{esc(filedrop.url_for(drop))}">⬇️ Скачать файл</a>',
            "",
            f"<i>Ссылка действует {drop.hours_left:.0f} ч, потом файл "
            f"удаляется с сервера.</i>",
        ]),
    )
    return True


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
    from .. import secrets as secrets_module

    cookies_path = (secrets_module.get("MEDIA_COOKIES")
                    or config.MEDIA_COOKIES).strip()
    options = media.build_options(
        target,
        chosen.selector_for(limit_mb),
        proxy=config.EGRESS_PROXY,
        cookies=cookies_path,
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


async def _safe_text(message: Message, text: str,
                     keyboard=None) -> None:
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass  # «message is not modified» и подобное — не повод падать
    except Exception:  # noqa: BLE001
        log.debug("Не удалось обновить сообщение прогресса", exc_info=True)


# --------------------------------------------------------------------------
#  Справка
# --------------------------------------------------------------------------

def _drop_note() -> str:
    """Строка про выдачу крупного файла ссылкой.

    Сказана прямо в разделе загрузки: без неё человек упирается в предел
    Telegram и решает, что бот больше ничего не умеет. Пусто, когда
    внешнего адреса нет — обещать несуществующее нельзя.
    """
    from .. import filedrop

    if not filedrop.enabled():
        return ""
    return (f"<b>Крупнее предела:</b> отдаётся ссылкой, до "
            f"{filedrop.MAX_FILE_MB // 1024} ГБ на файл. "
            f"Ссылка живёт {filedrop.TTL_HOURS} ч.\n")


@router.message(Command("media"))
async def cmd_media(message: Message, role: str) -> None:
    if not features.enabled("media_download"):
        await message.answer("Загрузка видео отключена суперадминистратором.")
        return
    if not _allowed(role):
        await message.answer("⛔️ Загрузка видео доступна начиная с другой роли.")
        return

    drop_note = _drop_note()
    limit = media.size_limit_mb(config.uses_local_api())
    server = "собственный Bot API Server" if config.uses_local_api() else "api.telegram.org"
    await message.answer(
        "🎬 <b>Загрузка видео</b>\n\n"
        "Пришлите ссылку — предложу выбрать качество и пришлю файл.\n\n"
        f"<b>Площадки:</b> {media.SUPPORTED_HINT}\n"
        f"<b>Предел отправки:</b> {limit} МБ ({server})\n"
        f"{drop_note}\n"
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
        f"<b>Предел отправки:</b> {limit} МБ ({server})\n"
        f"{_drop_note()}\n"
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
        # Ведём в общую подписку, а не в отдельную покупку безлимита:
        # раздельно эти части не продаются, и второе предложение
        # заставляло человека думать, что купить надо оба.
        rows.append([InlineKeyboardButton(
            text="💳 Подписка — безлимит на видео и подборки",
            callback_data="sub:menu",
        )])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню",
                                      callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "med:buy")
async def buy_unlimited(call: CallbackQuery, user: dict, role: str) -> None:
    """Старый отдельный вход покупки безлимита. С 4.9 подписка одна
    на бота и продаётся из одного места, поэтому кнопка из старых
    сообщений ведёт в общее меню — показывать тут вторую кассу
    значило бы вернуться к двум товарам за одну услугу."""
    await call.answer()
    await safe_edit(
        call,
        "💳 <b>Подписка одна на бота</b>\n\nОна открывает загрузку видео "
        "без дневного предела и все тематики новостных подборок. "
        "Раздельно эти части не продаются.",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⭐️ К подписке",
                                 callback_data="sub:menu"),
        ]]),
    )


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
