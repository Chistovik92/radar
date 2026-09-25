"""Раздел «VPN»: заявка, выдача, ссылка подписки, продление (с 5.0).

Кто что видит:

* любой пользователь — состояние своего доступа и ссылку подписки,
  а без доступа — кнопку заявки;
* роль не ниже `VPN_AUTO_ROLE` (по умолчанию администрация) получает
  доступ сразу, без заявки;
* администрация — заявки с кнопками «выдать»/«отказать», список
  выданных с продлением и отключением, проверку панели.

Ссылка подписки показывается только своему владельцу и в журнал
не пишется: она и есть ключ.
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

from .. import features, i18n, roles, storage, vpn
from ..textutils import esc
from ..tg import safe_edit, send_html
from ..vpnpanels import PanelError

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


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _back(target: str = "vpn:menu", lang: str = i18n.DEFAULT) -> list[InlineKeyboardButton]:
    return [_button(i18n.t("common.back", lang, "◀️ Назад"), target)]


def _name_of(uid: str) -> str:
    user = storage.get_user(uid) or {}
    username = user.get("username")
    return f"@{esc(username)}" if username else f"<code>{esc(uid)}</code>"


def _label(uid: str) -> str:
    """Подпись кнопки: без разметки, в отличие от `_name_of`."""
    username = (storage.get_user(uid) or {}).get("username")
    return f"@{username}" if username else uid


async def _menu_view(uid: str, user: dict[str, Any], role: str
                     ) -> tuple[str, InlineKeyboardMarkup]:
    lang = i18n.language_of(user)
    title = i18n.t("vpn.title", lang, "🔐 <b>VPN</b>")
    rows: list[list[InlineKeyboardButton]] = []
    lines = [title, ""]

    ok, reason = vpn.ready()
    entry = await vpn.record(uid) or {}
    state = entry.get("state")

    if not ok:
        lines.append(i18n.t("vpn.unavailable", lang,
                            "Раздел пока не настроен администратором."))
        if roles.is_admin(role):
            lines.append(f"\n<i>{esc(reason)}</i>")
    elif state == vpn.ACTIVE:
        try:
            account = await vpn.status(uid)
            failure = ""
        except PanelError as exc:
            account, failure = None, str(exc)
        if account is not None:
            lines.append(vpn.describe(account, lang))
            rows.append([_button(i18n.t("vpn.link_button", lang,
                                        "📋 Ссылка подписки"), "vpn:link")])
        elif failure:
            lines.append(f"⚠️ {esc(failure)}")
        else:
            # Запись удалили в самой панели. Забываем выдачу, иначе заявка
            # упёрлась бы в «уже выдано» и кнопка ничего бы не делала.
            await vpn.forget(uid)
            lines.append(i18n.t("vpn.gone", lang,
                                "Запись в панели не найдена — запросите доступ заново."))
            if vpn.issues_without_request(role):
                rows.append([_button(i18n.t("vpn.get_button", lang,
                                            "🔑 Получить доступ"), "vpn:get")])
            else:
                rows.append([_button(i18n.t("vpn.ask_button", lang,
                                            "📨 Запросить доступ"), "vpn:ask")])
    elif state == vpn.PENDING:
        lines.append(i18n.t("vpn.pending", lang,
                            "⏳ Заявка отправлена и ждёт решения администратора."))
    elif vpn.issues_without_request(role):
        lines.append(i18n.t("vpn.can_get", lang,
                            "Доступ выдаётся сразу — нажмите кнопку ниже."))
        rows.append([_button(i18n.t("vpn.get_button", lang,
                                    "🔑 Получить доступ"), "vpn:get")])
    else:
        if state == vpn.DENIED:
            lines.append(i18n.t("vpn.denied", lang,
                                "Прежняя заявка была отклонена. Можно подать новую."))
        else:
            lines.append(i18n.t("vpn.intro", lang,
                                "Доступ к VPN выдаёт администратор. "
                                "Отправьте заявку — ответ придёт сюда же."))
        rows.append([_button(i18n.t("vpn.ask_button", lang,
                                    "📨 Запросить доступ"), "vpn:ask")])

    if roles.is_admin(role):
        waiting = len(await vpn.pending())
        rows.append([
            _button(f"📨 Заявки ({waiting})", "vpn:reqs"),
            _button("👥 Выданные", "vpn:list"),
        ])
        rows.append([_button("🩺 Проверить панель", "vpn:check")])

    rows.append([_button(i18n.t("menu.home", lang, "🏠 В главное меню"), "menu:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _enabled_or_alert() -> bool:
    return features.enabled("vpn")


@router.callback_query(F.data == "vpn:menu")
async def menu_vpn(call: CallbackQuery, user: dict, role: str) -> None:
    if not _enabled_or_alert():
        await call.answer("Раздел выключен.", show_alert=True)
        return
    await call.answer()
    text, markup = await _menu_view(str(call.from_user.id), user, role)
    await safe_edit(call, text, markup)


async def _notify_admins(uid: str) -> None:
    """Заявка — администрации, с кнопками решения прямо в письме."""
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        _button("✅ Выдать", f"vpn:ok:{uid}"),
        _button("❌ Отказать", f"vpn:no:{uid}"),
    ]])
    text = f"🔐 Заявка на VPN от {_name_of(uid)}."
    for admin_uid, record in list(storage.users().items()):
        if not roles.is_admin(record.get("role")) or record.get("blocked"):
            continue
        try:
            await send_html(admin_uid, text, markup)
        except Exception:  # noqa: BLE001
            log.warning("Заявка на VPN не доставлена администратору %s", admin_uid)


@router.callback_query(F.data == "vpn:ask")
async def ask_access(call: CallbackQuery, user: dict, role: str) -> None:
    if not _enabled_or_alert():
        await call.answer("Раздел выключен.", show_alert=True)
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
        await _notify_admins(uid)
    text, markup = await _menu_view(uid, user, role)
    await safe_edit(call, text, markup)


async def _link_text(uid: str, lang: str) -> str:
    link = await vpn.subscription(uid)
    return (
        f"{i18n.t('vpn.link_title', lang, '🔐 <b>Ваша ссылка подписки</b>')}\n\n"
        f"<code>{esc(link)}</code>\n\n"
        f"{i18n.t('vpn.setup_steps', lang, VPN_SETUP_STEPS)}"
    )


def _link_markup(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t("vpn.hydra_button", lang,
                                          "⬇️ HydraVPN для Android"),
                              url=HYDRA_URL)],
        _back("vpn:menu", lang),
    ])


@router.callback_query(F.data == "vpn:get")
async def get_access(call: CallbackQuery, user: dict, role: str) -> None:
    if not _enabled_or_alert():
        await call.answer("Раздел выключен.", show_alert=True)
        return
    if not vpn.issues_without_request(role):
        await call.answer("Доступ выдаётся по заявке.", show_alert=True)
        return
    uid = str(call.from_user.id)
    lang = i18n.language_of(user)
    await call.answer("Выдаю…")
    try:
        await vpn.issue(uid, uid)
        text = await _link_text(uid, lang)
    except PanelError as exc:
        await safe_edit(call, f"❌ {esc(str(exc))}",
                        InlineKeyboardMarkup(inline_keyboard=[_back("vpn:menu", lang)]))
        return
    await safe_edit(call, text, _link_markup(lang))


@router.callback_query(F.data == "vpn:link")
async def show_link(call: CallbackQuery, user: dict) -> None:
    if not _enabled_or_alert():
        await call.answer("Раздел выключен.", show_alert=True)
        return
    uid = str(call.from_user.id)
    lang = i18n.language_of(user)
    entry = await vpn.record(uid) or {}
    if entry.get("state") != vpn.ACTIVE:
        await call.answer(i18n.t("vpn.no_access", lang, "Доступ не выдан."),
                          show_alert=True)
        return
    try:
        text = await _link_text(uid, lang)
    except PanelError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    await call.answer()
    await safe_edit(call, text, _link_markup(lang))


# --------------------------------------------------------------------------
#  Администрация
# --------------------------------------------------------------------------

async def _admin_only(call: CallbackQuery, role: str) -> bool:
    if not roles.is_admin(role):
        await call.answer("Только для администрации.", show_alert=True)
        return False
    if not _enabled_or_alert():
        await call.answer("Раздел выключен.", show_alert=True)
        return False
    return True


@router.callback_query(F.data == "vpn:reqs")
async def list_requests(call: CallbackQuery, role: str) -> None:
    if not await _admin_only(call, role):
        return
    await call.answer()
    waiting = await vpn.pending()
    rows = [[
        _button(f"✅ {_label(uid)}", f"vpn:ok:{uid}"),
        _button("❌", f"vpn:no:{uid}"),
    ] for uid in waiting[:30]]
    rows.append(_back())
    text = ("📨 <b>Заявки на VPN</b>\n\n"
            + ("✅ — выдать, ❌ — отказать." if waiting else "Заявок нет."))
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("vpn:ok:"))
async def approve(call: CallbackQuery, role: str) -> None:
    if not await _admin_only(call, role):
        return
    uid = call.data.split(":", 2)[2]
    entry = await vpn.record(uid) or {}
    if entry.get("state") == vpn.ACTIVE:
        await call.answer("Уже выдано.", show_alert=True)
        return
    await call.answer("Выдаю…")
    try:
        await vpn.issue(uid, call.from_user.id)
    except PanelError as exc:
        await safe_edit(call, f"❌ Выдать не удалось: {esc(str(exc))}",
                        InlineKeyboardMarkup(inline_keyboard=[_back("vpn:reqs")]))
        return

    lang = i18n.language_of(storage.get_user(uid))
    try:
        text = await _link_text(uid, lang)
        delivered = await send_html(uid, text, _link_markup(lang))
    except PanelError as exc:
        delivered = False
        log.warning("Ссылка для %s не получена: %s", uid, exc)
    note = "Ссылка отправлена." if delivered else (
        "Ссылку отправить не удалось — человек увидит её в разделе VPN.")
    await safe_edit(call, f"✅ Доступ выдан: {_name_of(uid)}. {note}",
                    InlineKeyboardMarkup(inline_keyboard=[_back("vpn:reqs")]))


@router.callback_query(F.data.startswith("vpn:no:"))
async def reject(call: CallbackQuery, role: str) -> None:
    if not await _admin_only(call, role):
        return
    uid = call.data.split(":", 2)[2]
    entry = await vpn.record(uid) or {}
    if entry.get("state") != vpn.PENDING:
        await call.answer("Заявки уже нет.", show_alert=True)
        return
    await vpn.deny(uid, call.from_user.id)
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
    if not await _admin_only(call, role):
        return
    await call.answer()
    people = await vpn.issued()
    rows = []
    for uid in people[:40]:
        rows.append([_button(_label(uid), f"vpn:u:{uid}")])
    rows.append(_back())
    text = f"👥 <b>Выданный VPN</b>: {len(people)}"
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def _card(call: CallbackQuery, uid: str, note: str = "") -> None:
    try:
        account = await vpn.status(uid)
    except PanelError as exc:
        account = None
        note = note or f"⚠️ {esc(str(exc))}"
    lines = [f"🔐 <b>VPN</b>: {_name_of(uid)}"]
    if account is not None:
        lines.append(vpn.describe(account))
    elif not note:
        lines.append("Записи в панели нет.")
    if note:
        lines.append("")
        lines.append(note)

    days = vpn.default_days()
    rows = [[_button(f"➕ {days} дн.", f"vpn:ext:{uid}")]]
    if account is not None:
        if account.enabled:
            rows.append([_button("⛔ Отключить", f"vpn:off:{uid}")])
        else:
            rows.append([_button("✅ Включить", f"vpn:on:{uid}")])
    rows.append(_back("vpn:list"))
    await safe_edit(call, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("vpn:u:"))
async def show_card(call: CallbackQuery, role: str) -> None:
    if not await _admin_only(call, role):
        return
    await call.answer()
    await _card(call, call.data.split(":", 2)[2])


@router.callback_query(F.data.startswith("vpn:ext:"))
async def extend_access(call: CallbackQuery, role: str) -> None:
    if not await _admin_only(call, role):
        return
    uid = call.data.split(":", 2)[2]
    days = vpn.default_days()
    await call.answer("Продлеваю…")
    try:
        account = await vpn.extend(uid, days)
    except PanelError as exc:
        await _card(call, uid, f"❌ {esc(str(exc))}")
        return
    note = (f"✅ Продлено на {days} дн." if account.expire
            else "Запись бессрочная — продлевать нечего.")
    await _card(call, uid, note)


@router.callback_query(F.data.startswith("vpn:off:") | F.data.startswith("vpn:on:"))
async def toggle_access(call: CallbackQuery, role: str) -> None:
    if not await _admin_only(call, role):
        return
    _, action, uid = call.data.split(":", 2)
    value = action == "on"
    await call.answer()
    try:
        await vpn.set_enabled(uid, value)
    except PanelError as exc:
        await _card(call, uid, f"❌ {esc(str(exc))}")
        return
    await _card(call, uid, "✅ Включено." if value else "⛔ Отключено.")


@router.callback_query(F.data == "vpn:check")
async def check_panel(call: CallbackQuery, role: str) -> None:
    if not await _admin_only(call, role):
        return
    await call.answer("Проверяю…")
    ok, note = await vpn.check()
    text = f"{'✅' if ok else '❌'} {esc(note)}"
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=[_back()]))
