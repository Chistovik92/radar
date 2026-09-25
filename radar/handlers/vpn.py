"""Раздел «VPN»: заявка, выдача на выбранные панели, ссылки (с 5.0).

Кто что видит (с 5.0.1):

* любой пользователь — свои доступы по каждой панели, ссылку для каждой
  и кнопку заявки. Сам себе он ничего не выдаёт: доступа без решения
  суперадминистратора не бывает;
* суперадминистратор — заявки (письмо приходит только ему), выбор
  панелей при выдаче, список выданных с продлением, отключением
  и отзывом по каждой панели, проверку всех панелей разом.

Администраторы и модераторы управлять выдачей не могут: это решение
вынесено на одного человека намеренно — доступ к VPN бесплатный
только по его воле. Проверка роли стоит и здесь, и в `radar/vpn.py`.

Ссылки показываются только своему владельцу и в журнал не пишутся:
ссылка и есть ключ.
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
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .. import features, i18n, payments, roles, storage, vpn, vpnsales
from ..textutils import esc
from ..tg import safe_edit, send_html
from ..vpnpanels import Account, PanelError

log = logging.getLogger("radar.handlers.vpn")
router = Router(name="vpn")

HYDRA_URL = "https://github.com/Chistovik92/HydraVPN"

VPN_SETUP_STEPS = (
    "<b>Как подключить:</b>\n"
    "1. Установите клиент с поддержкой подписок: HydraVPN или v2rayNG "
    "на Android, Streisand или Happ на iPhone, Hiddify или v2rayN "
    "на компьютере.\n"
    "2. Добавьте подписку по ссылке выше — «импорт из буфера» "
    "или «добавить подписку».\n"
    "3. Обновите подписку и выберите сервер.\n\n"
    "Ссылка — это ваш ключ: не пересылайте её. Одна и та же ссылка "
    "работает на всех ваших устройствах."
)

VPN_KEY_STEPS = (
    "<b>Как подключить:</b>\n"
    "1. Установите Outline Client или любой клиент Shadowsocks.\n"
    "2. Скопируйте ключ выше и добавьте его в клиент.\n\n"
    "Ключ — это ваш доступ: не пересылайте его."
)

VPN_CONFIG_STEPS = (
    "<b>Как подключить:</b>\n"
    "1. Установите WireGuard (или AmneziaWG).\n"
    "2. Откройте ссылку выше и скачайте файл настроек — ссылка "
    "<b>одноразовая</b>, второй раз она не откроется.\n"
    "3. Импортируйте файл в приложение.\n\n"
    "Нужна ещё раз — нажмите кнопку снова, бот выпустит новую ссылку."
)

DISABLED_TEXT = "Раздел выключен."
SUPERADMIN_ONLY = "Только для суперадминистратора."


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _back(target: str = "vpn:menu", lang: str = i18n.DEFAULT) -> list[InlineKeyboardButton]:
    return [_button(i18n.t("common.back", lang, "◀️ Назад"), target)]


def _name_of(uid: str) -> str:
    username = (storage.get_user(uid) or {}).get("username")
    return f"@{esc(username)}" if username else f"<code>{esc(uid)}</code>"


def _label(uid: str) -> str:
    """Подпись кнопки: без разметки, в отличие от `_name_of`."""
    username = (storage.get_user(uid) or {}).get("username")
    return f"@{username}" if username else uid


def _titles() -> dict[str, vpn.Slot]:
    return {item.key: item for item in vpn.slots()}


def _short(title: str, limit: int = 18) -> str:
    return title if len(title) <= limit else title[:limit - 1] + "…"


def _status_lines(results: dict[str, Any], lang: str) -> list[str]:
    """Состояние по каждой панели: название, затем срок и трафик."""
    known = _titles()
    lines: list[str] = []
    for key, result in sorted(results.items(), key=lambda item: int(item[0])):
        title = esc(known[key].title) if key in known else f"#{key}"
        lines.append(f"\n<b>{title}</b>")
        if isinstance(result, Account):
            lines.append(vpn.describe(result, lang))
        elif isinstance(result, PanelError):
            lines.append(f"⚠️ {esc(str(result))}")
        else:
            lines.append(i18n.t("vpn.gone", lang,
                                "Запись в панели не найдена — запросите доступ заново."))
    return lines


async def _menu_view(uid: str, user: dict[str, Any], role: str
                     ) -> tuple[str, InlineKeyboardMarkup]:
    lang = i18n.language_of(user)
    lines = [i18n.t("vpn.title", lang, "🔐 <b>VPN</b>")]
    rows: list[list[InlineKeyboardButton]] = []

    ok, reason = vpn.ready()
    entry = await vpn.record(uid) or {}
    state = entry.get("state")

    if not ok:
        lines.append("")
        lines.append(i18n.t("vpn.unavailable", lang,
                            "Раздел пока не настроен администратором."))
        if vpn.can_decide(role):
            lines.append(f"\n<i>{esc(reason)}</i>")
    else:
        if vpn.issued_slots(entry):
            results = await vpn.statuses(uid)
            lines.extend(_status_lines(results, lang))
            known = _titles()
            for key, result in sorted(results.items(), key=lambda item: int(item[0])):
                if isinstance(result, Account) and key in known:
                    rows.append([_button(f"📋 {_short(known[key].title, 30)}",
                                         f"vpn:l:{key}")])
        lines.append("")
        if state == vpn.PENDING:
            lines.append(i18n.t("vpn.pending", lang,
                                "⏳ Заявка отправлена и ждёт решения администратора."))
        else:
            if state == vpn.DENIED:
                lines.append(i18n.t("vpn.denied", lang,
                                    "Прежняя заявка была отклонена. Можно подать новую."))
            elif not vpn.issued_slots(entry):
                lines.append(i18n.t("vpn.intro", lang,
                                    "Доступ к VPN выдаёт администратор. "
                                    "Отправьте заявку — ответ придёт сюда же."))
            rows.append([_button(i18n.t("vpn.ask_button", lang,
                                        "📨 Запросить доступ"), "vpn:ask")])

    if ok and vpnsales.ready()[0]:
        rows.insert(0, [_button(i18n.t("vpn.buy_button", lang, "💳 Купить доступ"),
                                "vpn:buy")])

    if vpn.can_decide(role):
        waiting = len(await vpn.pending())
        rows.append([
            _button(f"📨 Заявки ({waiting})", "vpn:reqs"),
            _button("👥 Выданные", "vpn:list"),
        ])
        rows.append([
            _button("🔑 Выдать себе", f"vpn:rv:{uid}:0"),
            _button("🩺 Проверить панели", "vpn:check"),
        ])
        if features.enabled("vpn_sales"):
            rows.append([_button("🧾 Заказы", "vpn:orders")])

    rows.append([_button(i18n.t("menu.home", lang, "🏠 В главное меню"), "menu:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "vpn:menu")
async def menu_vpn(call: CallbackQuery, user: dict, role: str) -> None:
    if not features.enabled("vpn"):
        await call.answer(DISABLED_TEXT, show_alert=True)
        return
    await call.answer()
    text, markup = await _menu_view(str(call.from_user.id), user, role)
    await safe_edit(call, text, markup)


async def _notify_superadmins(uid: str) -> None:
    """Заявка — только суперадминистратору: решение за ним одним."""
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        _button("🔍 Рассмотреть", f"vpn:rv:{uid}:0"),
        _button("❌ Отказать", f"vpn:no:{uid}"),
    ]])
    text = f"🔐 Заявка на VPN от {_name_of(uid)}."
    for target, record in list(storage.users().items()):
        if not vpn.can_decide(record.get("role")) or record.get("blocked"):
            continue
        try:
            await send_html(target, text, markup)
        except Exception:  # noqa: BLE001
            log.warning("Заявка на VPN не доставлена суперадминистратору %s", target)


@router.callback_query(F.data == "vpn:ask")
async def ask_access(call: CallbackQuery, user: dict, role: str) -> None:
    if not features.enabled("vpn"):
        await call.answer(DISABLED_TEXT, show_alert=True)
        return
    ok, reason = vpn.ready()
    if not ok:
        await call.answer(reason, show_alert=True)
        return
    uid = str(call.from_user.id)
    before = (await vpn.record(uid) or {}).get("state")
    state = await vpn.request(uid)
    lang = i18n.language_of(user)
    await call.answer(i18n.t("vpn.sent", lang, "Заявка отправлена."))
    if state == vpn.PENDING and before != vpn.PENDING:
        await _notify_superadmins(uid)
    text, markup = await _menu_view(uid, user, role)
    await safe_edit(call, text, markup)


def _steps(link_kind: str, lang: str) -> str:
    if link_kind == "key":
        return i18n.t("vpn.key_steps", lang, VPN_KEY_STEPS)
    if link_kind == "config":
        return i18n.t("vpn.config_steps", lang, VPN_CONFIG_STEPS)
    return i18n.t("vpn.setup_steps", lang, VPN_SETUP_STEPS)


async def _link_text(uid: str, key: str, lang: str) -> str:
    target = _titles().get(key)
    if target is None:
        raise PanelError("Панель больше не настроена.")
    link = await vpn.subscription(uid, key)
    heading = {
        "key": i18n.t("vpn.key_title", lang, "🔐 <b>Ваш ключ</b>"),
        "config": i18n.t("vpn.config_title", lang, "🔐 <b>Ваша ссылка на настройки</b>"),
    }.get(target.client.link_kind,
          i18n.t("vpn.link_title", lang, "🔐 <b>Ваша ссылка подписки</b>"))
    return (
        f"{heading} — {esc(target.title)}\n\n"
        f"<code>{esc(link)}</code>\n\n"
        f"{_steps(target.client.link_kind, lang)}"
    )


def _link_markup(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t("vpn.hydra_button", lang,
                                          "⬇️ HydraVPN для Android"),
                              url=HYDRA_URL)],
        _back("vpn:menu", lang),
    ])


@router.callback_query(F.data.startswith("vpn:l:"))
async def show_link(call: CallbackQuery, user: dict) -> None:
    if not features.enabled("vpn"):
        await call.answer(DISABLED_TEXT, show_alert=True)
        return
    uid = str(call.from_user.id)
    key = call.data.split(":", 2)[2]
    lang = i18n.language_of(user)
    if key not in vpn.issued_slots(await vpn.record(uid)):
        await call.answer(i18n.t("vpn.no_access", lang, "Доступ не выдан."),
                          show_alert=True)
        return
    try:
        text = await _link_text(uid, key, lang)
    except PanelError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    await call.answer()
    await safe_edit(call, text, _link_markup(lang))


# --------------------------------------------------------------------------
#  Суперадминистратор
# --------------------------------------------------------------------------

async def _decider_only(call: CallbackQuery, role: str) -> bool:
    if not vpn.can_decide(role):
        await call.answer(SUPERADMIN_ONLY, show_alert=True)
        return False
    if not features.enabled("vpn"):
        await call.answer(DISABLED_TEXT, show_alert=True)
        return False
    return True


def _keys_of(mask: int) -> list[str]:
    return [str(number) for number in range(1, vpn.SLOTS + 1) if mask & (1 << (number - 1))]


def _parse_mask(value: str) -> int:
    return int(value) if value.isdigit() and int(value) < (1 << vpn.SLOTS) else 0


@router.callback_query(F.data == "vpn:reqs")
async def list_requests(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    await call.answer()
    waiting = await vpn.pending()
    rows = [[
        _button(f"🔍 {_label(uid)}", f"vpn:rv:{uid}:0"),
        _button("❌", f"vpn:no:{uid}"),
    ] for uid in waiting[:30]]
    rows.append(_back())
    text = ("📨 <b>Заявки на VPN</b>\n\n"
            + ("🔍 — выбрать панели и выдать, ❌ — отказать." if waiting else "Заявок нет."))
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("vpn:rv:"))
async def review(call: CallbackQuery, role: str) -> None:
    """Выбор панелей для выдачи: отметки хранятся в самой кнопке маской."""
    if not await _decider_only(call, role):
        return
    _, _, uid, raw = call.data.split(":", 3)
    mask = _parse_mask(raw)
    available = vpn.slots()
    entry = await vpn.record(uid) or {}
    have = set(vpn.issued_slots(entry))
    await call.answer()

    if not available:
        ok, reason = vpn.ready()
        await safe_edit(call, f"❌ {esc(reason)}",
                        InlineKeyboardMarkup(inline_keyboard=[_back()]))
        return

    rows = []
    for target in available:
        bit = 1 << (target.number - 1)
        mark = "☑️" if mask & bit else "⬜️"
        note = " · уже выдано" if target.key in have else ""
        rows.append([_button(f"{mark} {_short(target.title, 28)}{note}",
                             f"vpn:rv:{uid}:{mask ^ bit}")])
    every = sum(1 << (target.number - 1) for target in available)
    rows.append([_button("☑️ Все панели", f"vpn:rv:{uid}:{every}")])
    chosen = len(_keys_of(mask))
    if chosen:
        rows.append([_button(f"✅ Выдать ({chosen})", f"vpn:go:{uid}:{mask}")])
    if entry.get("state") == vpn.PENDING:
        rows.append([_button("❌ Отказать", f"vpn:no:{uid}")])
    rows.append(_back("vpn:reqs"))

    days = vpn.default_days()
    text = (f"🔐 <b>Выдача VPN</b>: {_name_of(uid)}\n\n"
            f"Отметьте панели. Срок — {days} дн., повторная выдача "
            f"возвращает прежний ключ.")
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("vpn:go:"))
async def approve(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    _, _, uid, raw = call.data.split(":", 3)
    keys = _keys_of(_parse_mask(raw))
    await call.answer("Выдаю…")
    try:
        results = await vpn.issue(uid, keys, call.from_user.id, role)
    except PanelError as exc:
        await safe_edit(call, f"❌ Выдать не удалось: {esc(str(exc))}",
                        InlineKeyboardMarkup(inline_keyboard=[_back("vpn:reqs")]))
        return

    known = _titles()
    report = []
    granted = []
    for key, result in sorted(results.items(), key=lambda item: int(item[0])):
        title = esc(known[key].title) if key in known else f"#{key}"
        if isinstance(result, Account):
            granted.append(key)
            report.append(f"✅ {title}")
        else:
            report.append(f"❌ {title}: {esc(str(result))}")

    delivered = False
    if granted:
        lang = i18n.language_of(storage.get_user(uid))
        parts = []
        for key in granted:
            try:
                parts.append(await _link_text(uid, key, lang))
            except PanelError as exc:
                log.warning("Ссылка для %s (слот %s) не получена: %s", uid, key, exc)
        if parts:
            delivered = await send_html(uid, "\n\n———\n\n".join(parts), _link_markup(lang))
    note = ""
    if granted:
        note = ("\n\nСсылки отправлены." if delivered else
                "\n\nСсылки отправить не удалось — человек увидит их в разделе VPN.")
    await safe_edit(call, f"🔐 Выдача для {_name_of(uid)}:\n" + "\n".join(report) + note,
                    InlineKeyboardMarkup(inline_keyboard=[_back("vpn:reqs")]))


@router.callback_query(F.data.startswith("vpn:no:"))
async def reject(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    uid = call.data.split(":", 2)[2]
    entry = await vpn.record(uid) or {}
    if entry.get("state") != vpn.PENDING:
        await call.answer("Заявки уже нет.", show_alert=True)
        return
    await vpn.deny(uid, call.from_user.id, role)
    await call.answer("Отклонено.")
    lang = i18n.language_of(storage.get_user(uid))
    try:
        await send_html(uid, i18n.t("vpn.denied_note", lang,
                                    "🔐 Заявка на VPN отклонена администратором."))
    except Exception:  # noqa: BLE001
        log.debug("Отказ по VPN не доставлен %s", uid)
    await safe_edit(call, f"❌ Заявка {_name_of(uid)} отклонена.",
                    InlineKeyboardMarkup(inline_keyboard=[_back("vpn:reqs")]))


@router.callback_query(F.data == "vpn:list")
async def list_issued(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    await call.answer()
    people = await vpn.issued()
    rows = [[_button(_label(uid), f"vpn:u:{uid}")] for uid in people[:40]]
    rows.append(_back())
    text = f"👥 <b>Выданный VPN</b>: {len(people)}"
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def _card(call: CallbackQuery, uid: str, note: str = "") -> None:
    results = await vpn.statuses(uid)
    lines = [f"🔐 <b>VPN</b>: {_name_of(uid)}"]
    lines.extend(_status_lines(results, "ru") if results else ["\nНичего не выдано."])
    if note:
        lines.append("")
        lines.append(note)

    known = _titles()
    days = vpn.default_days()
    rows = []
    for key, result in sorted(results.items(), key=lambda item: int(item[0])):
        target = known.get(key)
        if target is None:
            continue
        row = []
        if target.client.supports_expiry:
            row.append(_button(f"➕{days}д · {_short(target.title, 14)}",
                               f"vpn:ext:{key}:{uid}"))
        if isinstance(result, Account) and not result.enabled:
            row.append(_button("✅ Вкл.", f"vpn:on:{key}:{uid}"))
        else:
            row.append(_button("⛔ Выкл.", f"vpn:off:{key}:{uid}"))
        row.append(_button("🗑", f"vpn:rm:{key}:{uid}"))
        rows.append(row)
    rows.append([_button("➕ Выдать на другие панели", f"vpn:rv:{uid}:0")])
    rows.append(_back("vpn:list"))
    await safe_edit(call, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("vpn:u:"))
async def show_card(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    await call.answer()
    await _card(call, call.data.split(":", 2)[2])


@router.callback_query(F.data.startswith("vpn:ext:"))
async def extend_access(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    _, _, key, uid = call.data.split(":", 3)
    days = vpn.default_days()
    await call.answer("Продлеваю…")
    try:
        account = await vpn.extend(uid, key, days, role)
    except PanelError as exc:
        await _card(call, uid, f"❌ {esc(str(exc))}")
        return
    note = (f"✅ Продлено на {days} дн." if account.expire
            else "Запись бессрочная — продлевать нечего.")
    await _card(call, uid, note)


@router.callback_query(F.data.startswith("vpn:off:") | F.data.startswith("vpn:on:"))
async def toggle_access(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    _, action, key, uid = call.data.split(":", 3)
    value = action == "on"
    await call.answer()
    try:
        await vpn.set_enabled(uid, key, value, role)
    except PanelError as exc:
        await _card(call, uid, f"❌ {esc(str(exc))}")
        return
    await _card(call, uid, "✅ Включено." if value else "⛔ Отключено.")


@router.callback_query(F.data.startswith("vpn:rm:"))
async def revoke_access(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    _, _, key, uid = call.data.split(":", 3)
    await call.answer()
    try:
        await vpn.revoke(uid, key, role)
        note = "🗑 Доступ отозван: запись в панели выключена, выдача забыта."
    except PanelError as exc:
        note = f"⚠️ {esc(str(exc))}"
    await _card(call, uid, note)


@router.callback_query(F.data == "vpn:check")
async def check_panels(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    await call.answer("Проверяю…")
    known = _titles()
    results = await vpn.check_all()
    lines = ["🩺 <b>Панели VPN</b>"]
    for key, (ok, note) in sorted(results.items(), key=lambda item: int(item[0])):
        title = esc(known[key].title) if key in known else f"#{key}"
        lines.append(f"\n{'✅' if ok else '❌'} <b>{title}</b>\n{esc(note)}")
    wrong = vpn.unknown_kinds()
    if wrong:
        lines.append("\n⚠️ Незнакомый вид панели: " + esc(", ".join(wrong)))
    if len(lines) == 1:
        lines.append("\nНи одна панель не настроена.")
    await safe_edit(call, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[_back()]))


# --------------------------------------------------------------------------
#  Продажа по тарифам (с 5.0.2)
# --------------------------------------------------------------------------

def _plan_price(entry: dict[str, Any]) -> str:
    return f"{vpnsales.format_price(float(entry['amount']))} {esc(entry['currency'])}"


def _order_line(entry: dict[str, Any]) -> str:
    plan = vpnsales.Plan(**entry["plan"])
    status = vpnsales.STATUS_TITLES.get(entry["status"], entry["status"])
    return (f"<code>{esc(entry['id'])}</code> · {_name_of(entry['uid'])} · "
            f"{esc(plan.title(entry['currency']))} · <i>{esc(status)}</i>")


@router.callback_query(F.data == "vpn:buy")
async def show_plans(call: CallbackQuery, user: dict) -> None:
    lang = i18n.language_of(user)
    ok, reason = vpnsales.ready()
    if not ok:
        await call.answer(reason, show_alert=True)
        return
    await call.answer()
    unit = vpnsales.currency()
    rows = [[_button(plan.title(unit), f"vpn:plan:{index}")]
            for index, plan in enumerate(vpnsales.plans())]
    rows.append(_back("vpn:menu", lang))
    text = i18n.t("vpn.plans_title", lang,
                  "💳 <b>Тарифы VPN</b>\n\nПродление возвращает тот же ключ "
                  "и прибавляет дни к оставшимся.")
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def _notify_deciders(text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    for target, record in list(storage.users().items()):
        if not vpn.can_decide(record.get("role")) or record.get("blocked"):
            continue
        try:
            await send_html(target, text, markup)
        except Exception:  # noqa: BLE001
            log.warning("Сообщение о заказе VPN не доставлено %s", target)


@router.callback_query(F.data.startswith("vpn:plan:"))
async def buy_plan(call: CallbackQuery, user: dict) -> None:
    lang = i18n.language_of(user)
    raw = call.data.split(":", 2)[2]
    uid = str(call.from_user.id)
    try:
        entry = await vpnsales.create(uid, int(raw) if raw.isdigit() else -1)
    except vpnsales.SaleError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    await call.answer()
    plan = vpnsales.Plan(**entry["plan"])
    order_id = entry["id"]
    lines = [i18n.t("vpn.order_title", lang, "🧾 <b>Заказ</b> <code>{id}</code>")
             .format(id=esc(order_id)),
             esc(plan.title(entry["currency"]))]
    rows = []
    if entry["url"]:
        lines.append("")
        lines.append(i18n.t("vpn.order_pay", lang,
                            "Оплатите счёт по кнопке ниже, затем нажмите «Я оплатил»."))
        rows.append([InlineKeyboardButton(
            text=i18n.t("vpn.pay_button", lang, "💳 Оплатить"), url=entry["url"])])
        rows.append([_button(i18n.t("vpn.paid_button", lang, "✅ Я оплатил"),
                             f"vpn:chk:{order_id}")])
    else:
        note = payments_note()
        lines.append("")
        lines.append(i18n.t("vpn.order_manual", lang,
                            "Оплату подтверждает администратор. Доступ придёт "
                            "сюда сразу после подтверждения."))
        if note:
            lines.append(f"\n{esc(note)}")
        await _notify_deciders(
            f"🧾 Заказ VPN {_order_line(entry)}\nПодтвердите, когда оплата поступит.",
            InlineKeyboardMarkup(inline_keyboard=[[
                _button("✅ Оплата получена", f"vpn:cfm:{order_id}"),
                _button("✖️ Отменить", f"vpn:cnl:{order_id}"),
            ]]))
    rows.append([_button(i18n.t("vpn.cancel_order", lang, "✖️ Отменить заказ"),
                         f"vpn:cnl:{order_id}")])
    rows.append(_back("vpn:menu", lang))
    await safe_edit(call, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


def payments_note() -> str:
    """Как платить при ручном подтверждении — текст суперадминистратора."""
    from .. import secrets

    return str(secrets.get("PAY_MANUAL_NOTE") or "").strip()


async def _deliver(entry: dict[str, Any]) -> bool:
    """Ссылки по выполненному заказу — покупателю в личку."""
    uid = entry["uid"]
    lang = i18n.language_of(storage.get_user(uid))
    parts = []
    for key in entry.get("granted") or []:
        try:
            parts.append(await _link_text(uid, key, lang))
        except PanelError as exc:
            log.warning("Ссылка по заказу %s (слот %s) не получена: %s",
                        entry["id"], key, exc)
    if not parts:
        return False
    head = i18n.t("vpn.order_done", lang, "✅ Оплата получена, доступ открыт.")
    return await send_html(uid, head + "\n\n" + "\n\n———\n\n".join(parts),
                           _link_markup(lang))


async def _report_failure(entry: dict[str, Any]) -> None:
    errors = "; ".join(f"{key}: {value}" for key, value in (entry.get("errors") or {}).items())
    await _notify_deciders(
        f"⚠️ Заказ VPN оплачен, но выдать не удалось: {_order_line(entry)}\n"
        f"{esc(errors)}",
        InlineKeyboardMarkup(inline_keyboard=[[
            _button("🔁 Повторить выдачу", f"vpn:rty:{entry['id']}")]]))


async def _settle(entry: dict[str, Any]) -> str:
    """Что сказать после оплаты: выдано, не выдано или ещё ждём."""
    if entry["status"] == vpnsales.DONE:
        delivered = await _deliver(entry)
        return "✅ Доступ открыт." + ("" if delivered else
                                     " Ссылки — в разделе VPN.")
    if entry["status"] == vpnsales.FAILED:
        await _report_failure(entry)
        return ("⚠️ Оплата получена, но выдать доступ пока не удалось. "
                "Администратор уведомлён и повторит выдачу.")
    return vpnsales.STATUS_TITLES.get(entry["status"], entry["status"])


@router.callback_query(F.data.startswith("vpn:chk:"))
async def check_order(call: CallbackQuery, user: dict) -> None:
    lang = i18n.language_of(user)
    order_id = call.data.split(":", 2)[2]
    try:
        entry = await vpnsales.check(order_id, call.from_user.id)
    except vpnsales.SaleError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    if entry["status"] == vpnsales.NEW:
        await call.answer(i18n.t("vpn.not_paid", lang,
                                 "Оплата ещё не поступила. Попробуйте через минуту."),
                          show_alert=True)
        return
    await call.answer()
    note = await _settle(entry) if entry["status"] in (vpnsales.DONE, vpnsales.FAILED) \
        else vpnsales.STATUS_TITLES.get(entry["status"], entry["status"])
    await safe_edit(call, f"🧾 <code>{esc(order_id)}</code>: {esc(note)}",
                    InlineKeyboardMarkup(inline_keyboard=[_back("vpn:menu", lang)]))


@router.callback_query(F.data.startswith("vpn:cnl:"))
async def cancel_order(call: CallbackQuery, role: str) -> None:
    order_id = call.data.split(":", 2)[2]
    try:
        await vpnsales.cancel(order_id, call.from_user.id, role)
    except vpnsales.SaleError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    await call.answer("Заказ отменён.")
    await safe_edit(call, f"✖️ Заказ <code>{esc(order_id)}</code> отменён.",
                    InlineKeyboardMarkup(inline_keyboard=[_back()]))


@router.callback_query(F.data.startswith("vpn:cfm:") | F.data.startswith("vpn:rty:"))
async def confirm_order(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    _, action, order_id = call.data.split(":", 2)
    await call.answer("Выдаю…")
    try:
        if action == "cfm":
            entry = await vpnsales.confirm(order_id, role, call.from_user.id)
        else:
            entry = await vpnsales.retry(order_id, role)
    except vpnsales.SaleError as exc:
        await safe_edit(call, f"❌ {esc(str(exc))}",
                        InlineKeyboardMarkup(inline_keyboard=[_back("vpn:orders")]))
        return
    if entry["status"] == vpnsales.DONE:
        delivered = await _deliver(entry)
        note = "✅ Выдано." + (" Ссылки отправлены." if delivered
                              else " Ссылки отправить не удалось — они в разделе VPN.")
    else:
        errors = "; ".join(f"{k}: {v}" for k, v in (entry.get("errors") or {}).items())
        note = f"⚠️ Выдать не удалось: {esc(errors)}"
    rows = []
    if entry["status"] == vpnsales.FAILED:
        rows.append([_button("🔁 Повторить выдачу", f"vpn:rty:{order_id}")])
    rows.append(_back("vpn:orders"))
    await safe_edit(call, f"{_order_line(entry)}\n\n{note}",
                    InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "vpn:orders")
async def list_orders(call: CallbackQuery, role: str) -> None:
    if not await _decider_only(call, role):
        return
    await call.answer()
    entries = await vpnsales.recent(15)
    rows = []
    for entry in entries:
        if entry["status"] == vpnsales.NEW and entry.get("provider") == payments.ManualProvider.kind:
            rows.append([_button(f"✅ Оплачен {entry['id']}", f"vpn:cfm:{entry['id']}")])
        elif entry["status"] == vpnsales.FAILED:
            rows.append([_button(f"🔁 Повторить {entry['id']}", f"vpn:rty:{entry['id']}")])
    rows.append(_back())
    body = "\n".join(_order_line(entry) for entry in entries) or "Заказов нет."
    ok, reason = vpnsales.ready()
    state = "продажи включены" if ok else f"продажи не работают: {esc(reason)}"
    await safe_edit(call, f"🧾 <b>Заказы VPN</b> — {state}\n\n{body}",
                    InlineKeyboardMarkup(inline_keyboard=rows))
