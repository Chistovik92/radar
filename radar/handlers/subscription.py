"""Подписка одной кнопкой: состояние, пробный период, оплата.

До 4.9 подписка продавалась из двух мест — из раздела подборок и из раздела
видео. Модель под ними давно была одна (`radar/subscription.py`: оплата
любой части открывает обе), но человек видел два разных предложения и
разумно заключал, что покупать надо оба. Продавать дважды одно и то же
ощущение нельзя, поэтому вход теперь один.

Здесь же — пробный период на семь дней. Он даётся один раз и виден сразу:
если предлагать его после отказа от покупки, увидят его только те, кто
дошёл до отказа.

Правка тарифов и служебная часть — за отдельной кнопкой в управлении,
как у остальных разделов администрации.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import mediaquota, redeem, roles, storage, subscription
from ..textutils import esc
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.subscription")
router = Router(name="subscription")


def _plans() -> list[tuple[int, int]]:
    """Тарифы берутся у подборок: цена одна на всю подписку."""
    from .digest import _plans as digest_plans

    return digest_plans()


def _menu(user: dict[str, Any], role: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if not subscription.active(user, role):
        if not subscription.trial_used(user):
            rows.append([InlineKeyboardButton(
                text=f"🎁 Пробный период — {subscription.TRIAL_DAYS} дней",
                callback_data="sub:trial",
            )])
        rows.append([InlineKeyboardButton(
            text="⭐️ Оформить подписку", callback_data="sub:buy")])
    elif not subscription.complimentary(user, role):
        rows.append([InlineKeyboardButton(
            text="⭐️ Продлить подписку", callback_data="sub:buy")])

    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _text(user: dict[str, Any], role: str) -> str:
    """Что даёт подписка. Одним списком, потому что она одна."""
    lines = [
        "💳 <b>Подписка</b>", "",
        esc(subscription.describe(user, role)), "",
        "<b>Что открыто по подписке:</b>",
        "• новостные подборки по всем тематикам;",
        f"• загрузка видео без дневного предела "
        f"(без подписки — {mediaquota.FREE_PER_DAY} в сутки).", "",
        "<b>Оповещения об опасности бесплатны всегда</b> и от подписки "
        "не зависят — платной тревога не станет никогда.", "",
        "Раздельно эти части не продаются: подписка одна на бота.",
    ]
    return "\n".join(lines)


@router.message(Command("subscription"))
@router.message(Command("sub"))
async def show_command(message: Message, user: dict[str, Any], role: str) -> None:
    await message.answer(_text(user, role), reply_markup=_menu(user, role))


@router.callback_query(F.data == "sub:menu")
async def show(call: CallbackQuery, user: dict[str, Any], role: str) -> None:
    await call.answer()
    await safe_edit(call, _text(user, role), _menu(user, role))


@router.callback_query(F.data == "sub:trial")
async def take_trial(call: CallbackQuery, user: dict[str, Any], role: str) -> None:
    if subscription.trial_used(user):
        await call.answer("Пробный период уже был.", show_alert=True)
        return

    subscription.start_trial(user)
    await storage.save(call.from_user.id)
    await call.answer(f"Пробный период на {subscription.TRIAL_DAYS} дней включён")
    log.info("Пробный период выдан: %s", call.from_user.id)
    await safe_edit(call, _text(user, role), _menu(user, role))


@router.callback_query(F.data == "sub:buy")
async def buy(call: CallbackQuery) -> None:
    """Тарифы. Оплата идёт через тот же счёт, что и раньше."""
    rows = [
        [InlineKeyboardButton(text=f"{days} дней — {stars} ⭐️",
                              callback_data=f"dig:pay:{days}:{stars}")]
        for days, stars in _plans()
    ]
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="sub:menu")])
    await call.answer()
    await safe_edit(
        call,
        "⭐️ <b>Оформление подписки</b>\n\n"
        "Оплата звёздами Telegram. Подписка открывает подборки и загрузку "
        "видео без дневного предела — раздельно эти части не продаются.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


# --------------------------------------------------------------------------
#  Погашение кода, выданного на стороне партнёра
# --------------------------------------------------------------------------
#
# Обработчик стоит здесь, а не в разделе партнёров, потому что действие его
# — подписка, а не переход по ссылке. В интерфейсе о нём не сказано ничего:
# код узнаёт тот, кому его дали, и присылает сообщением.
#
# Ловим только то, что похоже на код, и только когда код действительно
# заведён: иначе обычная реплика перехватывалась бы у ассистента.

@router.message(StateFilter(None), F.text.func(redeem.looks_like_code))
async def redeem_code(message: Message, user: dict[str, Any]) -> None:
    # Импорт внутри функции: путь глубокий, и в офлайн-проверках aiogram
    # подменяется заглушкой, которая таких вложений не разбирает.
    from aiogram.dispatcher.event.bases import SkipHandler

    from ..identity import make as make_identity

    key = make_identity("telegram", str(message.from_user.id)).key
    try:
        days = await redeem.redeem(message.text or "", key)
    except Exception:  # noqa: BLE001
        log.exception("Погашение кода не удалось")
        return

    if not days:
        # Не наш код — молчим и пропускаем сообщение дальше по цепочке.
        # Ответ «код не подошёл» на каждое слово из заглавных букв
        # превратил бы бота в угадайку.
        raise SkipHandler

    subscription.grant(user, days)
    await storage.save(message.from_user.id)
    log.info("Подписка по коду: %s на %d дней", message.from_user.id, days)
    await message.answer(
        f"✅ <b>Код принят</b>\nПодписка продлена на {days} дней.\n"
        f"Осталось дней: <b>{subscription.days_left(user)}</b>",
        reply_markup=back_kb(),
    )


# --------------------------------------------------------------------------
#  Служебная часть
# --------------------------------------------------------------------------

@router.callback_query(F.data == "sub:admin")
async def admin(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    await call.answer()
    plans = ", ".join(f"{days} дн. — {stars} ⭐️" for days, stars in _plans())
    try:
        codes = await redeem.summary()
    except Exception:  # noqa: BLE001
        codes = "Список кодов недоступен."

    rows = [
        [InlineKeyboardButton(text="💰 Тарифы", callback_data="dig:price")],
        [InlineKeyboardButton(text="◀️ К управлению", callback_data="menu:manage")],
    ]
    await safe_edit(
        call,
        "💳 <b>Подписка — управление</b>\n\n"
        f"Тарифы: {esc(plans)}\n"
        f"Пробный период: {subscription.TRIAL_DAYS} дней, один раз на человека.\n"
        f"{esc(codes)}\n\n"
        "Подписка одна на бота: оплата открывает и подборки, и загрузку "
        "видео без дневного предела.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )
