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
from collections import defaultdict
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import config, features, i18n, secrets, storage, subscription

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

    url = match.group(0)
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
