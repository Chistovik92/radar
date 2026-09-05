"""Проверка ссылок на признаки мошенничества — команда /check.

Функция приехала из отдельного бота linkcheck (с 4.9.4 — часть «Радара»
за флагом возможности): статический разбор адреса плюс необязательные
сетевые проверки. Вывод перечисляет признаки и никогда не говорит
«ссылка безопасна» — это честнее, чем обещать гарантию.

Отдельного процесса и токена больше нет: тот бот пришлось бы узнавать
заранее, а /check живёт в основном боте и включается тумблером.

Квота: бесплатно 200 проверок в сутки, подписчикам — безлимит. Считаем
штуки, как и у загрузки видео: «осталось 17 из 200» понятнее мегабайт,
а дорога здесь не полоса, а чужие сервисы сетевых проверок.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import config, features, i18n, images, media, secrets, storage, subscription

log = logging.getLogger("radar.handlers.linkcheck")
router = Router(name="linkcheck")

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

# Квота дня: {"tg:<id>": {"day": "2026-09-05", "used": 17}}. Живёт в записи
# пользователя, поэтому переживает перезапуск. Ключ оставлен строкой —
# общий с антиспамом и квотами загрузки вид.
SLOT = "linkcheck"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _quota(user: dict) -> dict:
    data = user.get(SLOT)
    return data if isinstance(data, dict) else {}


def _left_today(user: dict) -> int:
    """Сколько бесплатных проверок осталось сегодня."""
    used = _quota(user)
    if used.get("day") != _today():
        return config.LINKCHECK_FREE_PER_DAY
    return max(0, config.LINKCHECK_FREE_PER_DAY - int(used.get("used") or 0))


def _spend(user: dict) -> None:
    used = dict(_quota(user))
    if used.get("day") != _today():
        used = {"day": _today(), "used": 0}
    used["used"] = int(used.get("used") or 0) + 1
    user[SLOT] = used


# Ограничение частоты: сетевые проверки ходят в чужие сервисы, и один
# человек очередью ссылок мог бы занять их на всех. Работает поверх
# дневной квоты и не касается подписчиков: безлимит не должен упираться
# в минутный предел.
_hits: dict[int, list[float]] = defaultdict(list)


def _rate_ok(user_id: int, unlimited: bool) -> bool:
    if unlimited:
        return True
    now = datetime.now(timezone.utc).timestamp()
    _hits[user_id] = [t for t in _hits[user_id] if now - t < 60]
    if len(_hits[user_id]) >= config.LINKCHECK_RATE_LIMIT:
        return False
    _hits[user_id].append(now)
    return True


def _menu_kb(lang: str, unlimited: bool, left: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not unlimited:
        # Точка продажи там, где человек упёрся в лимит: подписка одна
        # на бота и открывает всё, а не отдельный «проверочный» тариф.
        rows.append([InlineKeyboardButton(
            text=i18n.t("menu.sub_button", lang, "💳 Подписка — безлимит проверок"),
            callback_data="sub:menu",
        )])
    rows.append([InlineKeyboardButton(
        text=i18n.t("menu.home", lang, "🏠 В главное меню"),
        callback_data="menu:main",
    )])
    del left
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _section_screen(message: Message, user: dict, role: str) -> None:
    """Экран раздела из главного меню: что умеет проверка и что осталось."""
    lang = i18n.language_of(user)
    unlimited = subscription.active(user, role)
    left = _left_today(user)

    if unlimited:
        quota_line = i18n.t(
            "linkcheck.unlimited", lang, "Проверки без дневного предела — по подписке."
        )
    else:
        quota_line = i18n.t(
            "linkcheck.left", lang,
            f"Осталось сегодня: {left} из {config.LINKCHECK_FREE_PER_DAY}",
        )

    net = ""
    if not config.LINKCHECK_NET:
        net = "\n<i>Сетевые проверки выключены — работает мгновенный разбор адреса.</i>"

    await message.answer(
        i18n.t(
            "linkcheck.section", lang,
            "🔍 <b>Проверка ссылок</b>\n\n"
            "Разбор адреса на признаки мошенничества: подмена букв под "
            "бренд, чужой домен, редиректы, возраст домена, базы "
            "Safe Browsing.\n\n"
            f"{quota_line}{net}\n\n"
            "Проверка — командой <code>/check &lt;ссылка&gt;</code>.\n\n"
            "<i>Вывод перечисляет признаки и не говорит «ссылка "
            "безопасна»: отсутствие признаков — не гарантия.</i>",
        ),
        reply_markup=_menu_kb(lang, unlimited, left),
    )


@router.callback_query(F.data == "lchk:menu")
async def section(call: CallbackQuery, user: dict, role: str) -> None:
    await call.answer()
    await _section_screen(call.message, user, role)


async def _run_check(message: Message, user: dict, role: str, url: str) -> None:
    """Полная проверка: квоты, разбор, сеть, отчёт."""
    lang = i18n.language_of(user)
    unlimited = subscription.active(user, role)

    if not _rate_ok(message.from_user.id, unlimited):
        await message.answer(
            i18n.t(
                "linkcheck.slow_down", lang,
                "⚠️ Слишком много проверок подряд. Подождите минуту.",
            )
        )
        return

    if not unlimited and _left_today(user) <= 0:
        await message.answer(
            i18n.t(
                "linkcheck.limit", lang,
                f"🔒 Дневной предел проверок исчерпан "
                f"({config.LINKCHECK_FREE_PER_DAY} в сутки).\n\n"
                "Подписка снимает предел. Оповещения об опасности "
                "бесплатны всегда и от этого не зависят.",
            ),
            reply_markup=_menu_kb(lang, unlimited, 0),
        )
        return

    await message.answer(i18n.t("linkcheck.working", lang, "⏳ Проверяю ссылку…"))

    # Импорт внутри обработчика: утилиты мультитула не грузятся, пока
    # флаг выключен, и правка в них не трогает остального бота.
    from multitool.linkcheck.analyze import analyze
    from multitool.linkcheck.report import build_report

    verdict = analyze(url)

    if config.LINKCHECK_NET:
        from multitool.linkcheck.netcheck import NetResult, full_check

        key = (secrets.get("SAFE_BROWSING_API_KEY") or "").strip()
        try:
            verdict.net = await asyncio.wait_for(
                full_check(url, key), timeout=config.LINKCHECK_TIMEOUT
            )
        except asyncio.TimeoutError:
            verdict.net = NetResult(notes=["timeout"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Сетевая проверка не удалась: %s", exc)
            verdict.net = NetResult(notes=[f"error: {type(exc).__name__}"])

    # Счётчик дня тратим только за состоявшуюся проверку: за неудачную
    # человек платить квотой не должен.
    if not unlimited:
        _spend(user)
        await storage.save(message.from_user.id)

    log.info("Проверена ссылка: %s (счёт %d)", url[:80], verdict.score)

    note = ""
    if not unlimited:
        left = _left_today(user)
        note = "\n\n" + i18n.t(
            "linkcheck.left", lang, f"Осталось сегодня: {left} из "
            f"{config.LINKCHECK_FREE_PER_DAY}"
        )
    await message.answer(
        build_report(verdict) + note,
        disable_web_page_preview=True,
    )


@router.message(Command("check"))
async def cmd_check(message: Message, user: dict, role: str) -> None:
    lang = i18n.language_of(user)

    if not features.enabled("linkcheck"):
        await message.answer(
            i18n.t("linkcheck.off", lang, "Проверка ссылок отключена.")
        )
        return

    args = (message.text or "").split(maxsplit=1)
    match = URL_RE.search(args[1] if len(args) > 1 else "")
    if not match:
        unlimited = subscription.active(user, role)
        await message.answer(
            i18n.t(
                "linkcheck.usage", lang,
                "🔍 Пришлите ссылку после команды:\n"
                "<code>/check https://пример.рф/страница</code>",
            ),
            reply_markup=_menu_kb(lang, unlimited, _left_today(user)),
        )
        return

    await _run_check(message, user, role, match.group(0))


# --------------------------------------------------------------------------
#  Ссылка, присланная просто сообщением
# --------------------------------------------------------------------------
#
# До 4.9.4.2 любую ссылку целиком забирал загрузчик видео — и человек,
# хотевший её проверить, получал «Смотрю, что за ссылка…» и список
# качеств. Когда включены обе возможности, выбора не должен не существовать:
# бот спрашивает, что сделать со ссылкой. Когда проверка включена одна —
# проверяет сразу. Когда выключена — молча пропускает ссылку дальше
# по цепочке, и работает прежний путь.

# Ожидающие выбора: токен → ссылка, владелец, исходное сообщение.
# Сообщение храним, чтобы кнопка «Скачать» запустила штатный путь
# загрузчика с тем же текстом.
_pending: dict[str, dict] = {}
_PENDING_TTL = 15 * 60


def _cleanup_pending() -> None:
    edge = time.time() - _PENDING_TTL
    for token, item in list(_pending.items()):
        if item["created"] < edge:
            _pending.pop(token, None)


def _media_available() -> bool:
    """Включён ли загрузчик и есть ли yt-dlp в образе."""
    if not features.enabled("media_download"):
        return False
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


@router.message(StateFilter(None), F.text.func(media.looks_like_url))
async def plain_link(message: Message, user: dict, role: str) -> None:
    from aiogram.dispatcher.event.bases import SkipHandler

    # Проверка выключена — ссылку не трогаем: её возьмёт загрузчик
    # или ассистент, как раньше.
    if not features.enabled("linkcheck"):
        raise SkipHandler

    url = (message.text or "").strip().split()[0]
    lang = i18n.language_of(user)

    # Прямая ссылка на картинку — сразу в загрузку картинки, без
    # выбора: проверять там нечего, а «скачать видео» про картинку
    # не говорят. До 4.9.4.3 такой линк застревал в выборе.
    if images.looks_like_image(url):
        raise SkipHandler

    # Загрузчик недоступен — проверяем сразу, выбора нет.
    if not _media_available():
        await _run_check(message, user, role, url)
        return

    # Включены обе возможности: спрашиваем. Картинки из записи —
    # отдельная дорога: yt-dlp тратил бы до 90 секунд на пробу и лишь
    # потом падал с «видео нет», а человек хотел снимки поста.
    _cleanup_pending()
    token = uuid.uuid4().hex[:10]
    _pending[token] = {
        "url": url,
        "owner": message.from_user.id,
        "message": message,
        "created": time.time(),
    }
    await message.answer(
        i18n.t("linkcheck.choice", lang, "🔗 <b>Что сделать со ссылкой?</b>"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=i18n.t("linkcheck.btn_check", lang, "🔍 Проверить"),
                callback_data=f"lchk:go:{token}"),
             InlineKeyboardButton(
                 text=i18n.t("linkcheck.btn_video", lang, "🎬 Скачать видео"),
                 callback_data=f"lchk:dl:{token}")],
            [InlineKeyboardButton(
                text=i18n.t("linkcheck.btn_images", lang, "🖼 Картинки из записи"),
                callback_data=f"lchk:img:{token}")],
            [InlineKeyboardButton(
                text=i18n.t("linkcheck.btn_nothing", lang, "❌ Ничего"),
                callback_data=f"lchk:skip:{token}")],
        ]),
    )


def _pending_of(call: CallbackQuery, token: str) -> dict | None:
    """Запрос по токену с проверкой владельца. None — чужой или устаревший."""
    item = _pending.get(token)
    if item is None:
        return None
    if item["owner"] != call.from_user.id:
        return None
    return item


async def _drop_choice(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("lchk:go:"))
async def choice_check(call: CallbackQuery, user: dict, role: str) -> None:
    item = _pending_of(call, call.data.split(":")[2])
    if item is None:
        await call.answer("Запрос устарел — пришлите ссылку заново.", show_alert=True)
        return
    _pending.pop(call.data.split(":")[2], None)
    await call.answer()
    await _drop_choice(call)
    await _run_check(item["message"], user, role, item["url"])


@router.callback_query(F.data.startswith("lchk:dl:"))
async def choice_download(call: CallbackQuery, role: str, user: dict) -> None:
    token = call.data.split(":")[2]
    item = _pending_of(call, token)
    if item is None:
        await call.answer("Запрос устарел — пришлите ссылку заново.", show_alert=True)
        return
    _pending.pop(token, None)
    await call.answer()
    await _drop_choice(call)

    # Штатный путь загрузчика с исходным сообщением: у него свои
    # проверки, свои сообщения и своя обработка ошибок.
    from . import media as media_handler

    await media_handler.handle_link(item["message"], role, user)


@router.callback_query(F.data.startswith("lchk:img:"))
async def choice_images(call: CallbackQuery, user: dict) -> None:
    """Картинки из записи напрямую — без 90-секундной пробы yt-dlp."""
    token = call.data.split(":")[2]
    item = _pending_of(call, token)
    if item is None:
        await call.answer("Запрос устарел — пришлите ссылку заново.", show_alert=True)
        return
    _pending.pop(token, None)
    await call.answer()
    await _drop_choice(call)

    from . import media as media_handler

    await media_handler.post_images(item["message"], item["url"], user)


@router.callback_query(F.data.startswith("lchk:skip:"))
async def choice_skip(call: CallbackQuery) -> None:
    _pending.pop(call.data.split(":")[2], None)
    await call.answer()
    await _drop_choice(call)
