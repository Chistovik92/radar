"""Новостные подборки в интерфейсе бота и оплата через Telegram Stars."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from .. import digest, features, roles, secrets, storage
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.digest")
router = Router(name="digest")

# Цены задаёт суперадминистратор; значения по умолчанию — ориентир
DEFAULT_PLANS = ((30, 150), (90, 400), (365, 1400))


def _plans() -> list[tuple[int, int]]:
    """Тарифы из настроек: «дни:звёзды» через запятую."""
    raw = secrets.get("DIGEST_PLANS")
    if not raw:
        return list(DEFAULT_PLANS)
    plans: list[tuple[int, int]] = []
    for chunk in raw.split(","):
        match = re.fullmatch(r"\s*(\d+):(\d+)\s*", chunk)
        if match:
            plans.append((int(match.group(1)), int(match.group(2))))
    return plans or list(DEFAULT_PLANS)


def _menu(subscription: digest.Subscription) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📋 Тематики", callback_data="dig:topics")],
        [InlineKeyboardButton(text="🕘 Время доставки", callback_data="dig:time")],
    ]
    if features.enabled("digest_paid"):
        label = "⭐️ Продлить подписку" if subscription.active else "⭐️ Оформить подписку"
        rows.append([InlineKeyboardButton(text=label, callback_data="dig:buy")])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _topics_menu(subscription: digest.Subscription) -> InlineKeyboardMarkup:
    chosen = set(subscription.topics)
    allowed = set(subscription.allowed_topics())
    rows = []
    for topic in digest.TOPICS:
        if topic.key in allowed:
            mark = "✅"
        elif topic.key in chosen:
            mark = "🔒"       # выбрана, но недоступна без подписки
        else:
            mark = "▫️"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {topic.icon} {topic.title}",
                callback_data=f"dig:topic:{topic.key}",
            )
        ])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="dig:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("digest"))
async def cmd_digest(message: Message, user: dict) -> None:
    if not features.enabled("digest"):
        await message.answer("Новостные подборки пока отключены.")
        return
    subscription = digest.subscription_of(user)
    await message.answer(digest.describe(subscription), reply_markup=_menu(subscription))


@router.callback_query(F.data == "dig:menu")
async def show_menu(call: CallbackQuery, state: FSMContext, user: dict) -> None:
    if not features.enabled("digest"):
        await call.answer("Функция отключена.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    subscription = digest.subscription_of(user)
    await safe_edit(call, digest.describe(subscription), _menu(subscription))


@router.callback_query(F.data == "dig:topics")
async def show_topics(call: CallbackQuery, user: dict) -> None:
    subscription = digest.subscription_of(user)
    await call.answer()

    lines = ["📋 <b>Тематики</b>", ""]
    if not subscription.active:
        lines.append(
            f"Без подписки доставляется тематик: <b>{digest.FREE_TOPICS}</b>. "
            "Выбранные сверх лимита помечены замком."
        )
        lines.append("")
    for topic in digest.TOPICS:
        lines.append(f"{topic.icon} <b>{esc(topic.title)}</b> — <i>{esc(topic.description)}</i>")
    await safe_edit(call, "\n".join(lines), _topics_menu(subscription))


@router.callback_query(F.data.startswith("dig:topic:"))
async def toggle_topic(call: CallbackQuery, user: dict) -> None:
    key = call.data.split(":", 2)[2]
    subscription = digest.subscription_of(user)
    enabled, reason = subscription.toggle(key)

    if reason:
        await call.answer(reason, show_alert=True)
    else:
        topic = digest.BY_KEY.get(key)
        await call.answer(
            f"{topic.title}: {'включена' if enabled else 'выключена'}" if topic else "Готово"
        )

    digest.store_subscription(user, subscription)
    await storage.save(call.from_user.id)
    await safe_edit(call, digest.describe(subscription), _topics_menu(subscription))


@router.callback_query(F.data == "dig:time")
async def ask_time(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(Form.digest_time)
    await safe_edit(
        call,
        "🕘 <b>Время доставки</b>\n\n"
        "Пришлите одно или два времени через запятую, например:\n"
        "<code>08:30, 19:30</code>\n\n"
        "<i>/cancel — отмена.</i>",
        back_kb("dig:menu", "Отмена"),
    )


@router.message(Form.digest_time)
async def save_time(message: Message, state: FSMContext, user: dict) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    times = []
    for chunk in text.split(","):
        value = chunk.strip()
        if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
            hour, minute = value.split(":")
            times.append(f"{int(hour):02d}:{minute}")

    if not times:
        await message.answer(
            "❌ Неверный формат. Пример: <code>08:30, 19:30</code>. /cancel — отмена."
        )
        return

    subscription = digest.subscription_of(user)
    subscription.times = times[:2]
    digest.store_subscription(user, subscription)
    await storage.save(message.from_user.id)
    await state.clear()

    await message.answer(
        f"✅ Подборка будет приходить в <b>{', '.join(subscription.times)}</b>.",
        reply_markup=back_kb("dig:menu", "◀️ Назад"),
    )


# --------------------------------------------------------------------------
#  Оплата
# --------------------------------------------------------------------------

@router.callback_query(F.data == "dig:buy")
async def show_plans(call: CallbackQuery) -> None:
    if not features.enabled("digest_paid"):
        await call.answer("Подписка отключена.", show_alert=True)
        return

    await call.answer()
    rows = [
        [
            InlineKeyboardButton(
                text=f"{days} дней — {stars} ⭐️",
                callback_data=f"dig:pay:{days}:{stars}",
            )
        ]
        for days, stars in _plans()
    ]
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="dig:menu")])

    await safe_edit(
        call,
        "⭐️ <b>Подписка на подборки</b>\n\n"
        "Открывает все двенадцать тематик. Оплата — звёздами Telegram.\n\n"
        "<i>Оповещения об опасности, ЖКХ, погода и SOS остаются бесплатными "
        "всегда и от подписки не зависят.</i>",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("dig:pay:"))
async def send_invoice(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    days, stars = int(parts[2]), int(parts[3])
    await call.answer()

    try:
        await call.message.answer_invoice(
            title=f"Подборки — {days} дней",
            description=(
                "Все двенадцать тематик новостей города в одном сообщении "
                "в выбранное вами время."
            ),
            payload=f"digest:{days}",
            currency="XTR",                      # звёзды Telegram
            prices=[LabeledPrice(label=f"{days} дней", amount=stars)],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Счёт не выставлен: %s", exc)
        await call.message.answer(
            "❌ Не удалось выставить счёт. Попробуйте позже.",
            reply_markup=back_kb("dig:menu", "◀️ Назад"),
        )


@router.pre_checkout_query()
async def confirm_checkout(query: PreCheckoutQuery) -> None:
    # Подтверждаем всегда: товар цифровой, наличия не бывает
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def payment_done(message: Message, user: dict) -> None:
    payload = message.successful_payment.invoice_payload or ""
    match = re.fullmatch(r"digest:(\d+)", payload)
    if not match:
        log.warning("Неизвестный платёж: %s", payload)
        return

    days = int(match.group(1))
    subscription = digest.subscription_of(user)
    subscription.extend(days)
    digest.store_subscription(user, subscription)
    await storage.save(message.from_user.id)

    log.info("Оплата подписки: %s на %d дней", message.from_user.id, days)
    await message.answer(
        f"✅ <b>Подписка активна</b>\nДней осталось: <b>{subscription.days_left}</b>\n\n"
        "Теперь доступны все двенадцать тематик — выберите нужные.",
        reply_markup=_menu(subscription),
    )


@router.message(Command("digestprice"))
async def set_price(message: Message, role: str) -> None:
    """Цены задаёт только суперадминистратор."""
    if not roles.is_superadmin(role):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        current = ", ".join(f"{days}д:{stars}⭐️" for days, stars in _plans())
        await message.answer(
            f"Текущие тарифы: {current}\n\n"
            "Изменить: <code>/digestprice 30:150, 90:400, 365:1400</code>\n"
            "<i>Формат «дни:звёзды» через запятую.</i>"
        )
        return

    value = parts[1].strip()
    if not re.fullmatch(r"\s*\d+:\d+\s*(,\s*\d+:\d+\s*)*", value):
        await message.answer("❌ Формат: <code>30:150, 90:400</code>")
        return

    secrets.write("DIGEST_PLANS", value)
    plans = ", ".join(f"{days}д:{stars}⭐️" for days, stars in _plans())
    await message.answer(f"✅ Тарифы обновлены: {plans}")
