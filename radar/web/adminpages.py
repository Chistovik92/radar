"""Страницы веб-панели: VPN-панели, доступы и заказы, подписка бота (5.9.2.1).

Вынесено из panel.py, где уже три с половиной тысячи строк. Здесь только
сборка HTML и действия над данными; маршруты, проверка сессии и токена
формы остаются в panel.py — в одном месте, чтобы не пропустить проверку
в новом обработчике.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
import re
import time
from typing import Any

from .. import features, roles, storage, subscription, vpn, vpnpanels, vpnsales, vpnslots
from ..vpnpanels import Account, PanelError

MAX_GRANT_DAYS = 3650
MAX_PEOPLE_SHOWN = 60


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _note(kind: str, text: str) -> str:
    if not text:
        return ""
    css = "ok" if kind == "ok" else "bad"
    return f'<div class="card {css}">{esc(text)}</div>'


def _stamp(value: Any) -> str:
    try:
        return time.strftime("%d.%m.%Y %H:%M", time.localtime(int(value)))
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def _hidden(token: str, **fields: str) -> str:
    parts = [f'<input type="hidden" name="csrf" value="{esc(token)}">']
    parts.extend(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">'
                 for k, v in fields.items())
    return "".join(parts)


def who(uid: str) -> str:
    user = storage.get_user(uid) or {}
    name = user.get("username")
    return "@" + str(name) if name else str(uid)


def _host(url: str) -> str:
    return re.sub(r"^https?://", "", url or "").split("/")[0] or "—"


# --------------------------------------------------------------------------
#  Панели VPN
# --------------------------------------------------------------------------

async def panels_body(token: str, message: str = "", failed: str = "",
                      edit: int | None = None) -> str:
    parts = [_note("ok", message), _note("bad", failed)]

    records = await vpn.records()
    per_slot: dict[str, int] = {}
    for entry in records.values():
        for key in (entry.get("panels") or {}):
            per_slot[key] = per_slot.get(key, 0) + 1

    rows = []
    for number in vpnslots.numbers():
        if not vpnslots.configured(number):
            continue
        values = vpnslots.read(number)
        known = {info.kind: info.title for info in vpnslots.kinds()}
        kind = known.get(vpnpanels.normalize_kind(values["KIND"]), values["KIND"] + " (незнакомый вид)")
        secret = "токен" if values["TOKEN"] else ("логин и пароль" if values["USER"] else "—")
        issued = per_slot.get(str(number), 0)
        warn = (f"Доступов выдано на этой панели: {issued}. После удаления "
                "бот перестанет находить их записи — выдавать придётся заново. "
                "Сами записи в панели остаются.") if issued else "Удалить панель из бота?"
        rows.append(
            f"<tr><td>{number}</td>"
            f"<td><b>{esc(values['TITLE'] or '—')}</b><br>"
            f'<span class="muted">{esc(kind)}</span></td>'
            f"<td>{esc(_host(values['URL']))}<br>"
            f'<span class="muted">вход: {esc(secret)}</span></td>'
            f"<td>{issued}</td>"
            '<td style="text-align:right;white-space:nowrap">'
            f'<a class="btn ghost" href="/vpn/panels?slot={number}#form">изменить</a> '
            '<form class="inline" method="post" action="/vpn/panels/check">'
            f"{_hidden(token, slot=str(number))}"
            '<button class="ghost" type="submit">проверить</button></form> '
            f'<form class="inline" method="post" action="/vpn/panels/remove" '
            f"onsubmit=\"return confirm('{esc(warn)}')\">"
            f"{_hidden(token, slot=str(number))}"
            '<button class="ghost danger" type="submit">удалить</button></form>'
            "</td></tr>"
        )
    if rows:
        table = ("<table><tr><th>Слот</th><th>Панель</th><th>Адрес</th>"
                 "<th>Выдано</th><th></th></tr>" + "".join(rows) + "</table>")
    else:
        table = '<p class="muted">Панели не добавлены. Добавьте первую ниже.</p>'
    parts.append('<div class="card"><h3>Панели VPN</h3>' + table
                 + '<p class="muted">Слотов всего '
                 f"{vpn.SLOTS}; панели разных видов работают одновременно, "
                 "отказ одной не задевает остальные.</p></div>")

    # --- форма ---
    target = edit if edit in vpnslots.numbers() and vpnslots.configured(edit or 0) else None
    number = target if target is not None else vpnslots.free_number()
    if number is None:
        parts.append('<div class="card muted">Все слоты заняты. Удалите ненужную панель, '
                     "чтобы добавить другую.</div>")
        return "".join(parts)

    values = vpnslots.read(number) if target is not None else {f: "" for f in vpnslots.FIELDS}
    current_kind = vpnpanels.normalize_kind(values["KIND"])
    options = "".join(
        f'<option value="{esc(info.kind)}"{" selected" if info.kind == current_kind else ""}>'
        f"{esc(info.title)}</option>" for info in vpnslots.kinds()
    )

    def field(name: str, label: str, secret: bool = False, hint: str = "") -> str:
        kind = "password" if secret else "text"
        if secret and values[name]:
            place = "задан — оставьте пустым, чтобы не менять"
            shown = ""
        else:
            place, shown = "", esc(values[name])
        tail = f'<div class="hint">{esc(hint)}</div>' if hint else ""
        return (f"<label><b>{esc(label)}</b><br>"
                f'<input type="{kind}" name="{name}" value="{shown}" '
                f'placeholder="{esc(place)}" autocomplete="off" style="width:100%"></label>{tail}')

    title = f"Изменить панель (слот {number})" if target is not None else f"Добавить панель (слот {number})"
    form = (
        f'<div class="card" id="form"><h3>{esc(title)}</h3>'
        '<form method="post" action="/vpn/panels/save">'
        f"{_hidden(token, slot=str(number))}"
        f'<label><b>Вид панели</b><br><select name="KIND">{options}</select></label>'
        + field("TITLE", "Название", hint="Как панель подписана для людей, например «Нидерланды».")
        + field("URL", "Адрес панели", hint="Корень панели, как в браузере до /dashboard (https://хост:порт) — "
                "лишний путь отсекается сам. Секретный путь 3x-ui и x-ui нужен целиком; "
                "для Outline — apiUrl целиком, для Hiddify — с путём администратора.")
        + field("TOKEN", "Токен или ключ API", secret=True)
        + field("USER", "Логин (вместо токена)")
        + field("PASS", "Пароль (вместо токена)", secret=True)
        + field("INBOUND", "Номер подключения (inbound)", hint="Только для 3x-ui и x-ui.")
        + field("SUB_URL", "Адрес службы подписки", hint="3x-ui, x-ui, s-ui; у Hiddify — клиентский путь.")
        + field("GROUPS", "Группы, сервисы, отряды", hint="Через запятую; нужны не всем панелям.")
        + field("CERT", "Отпечаток сертификата (SHA-256)",
                hint="Для панели на самоподписанном сертификате; для Outline обязателен.")
        + '<p><button type="submit">Сохранить</button> '
        + ('<a class="btn ghost" href="/vpn/panels">отмена</a>' if target is not None else "")
        + "</p></form></div>"
    )
    parts.append(form)

    needs = "".join(f"<tr><td><b>{esc(info.title)}</b></td><td>{esc(info.needs)}</td></tr>"
                    for info in vpnslots.kinds())
    parts.append('<details class="card"><summary><b>Что нужно каждой панели</b></summary>'
                 f"<table>{needs}</table>"
                 '<p class="muted">Значения проверяются при сохранении; работу панели '
                 "проверяет кнопка «проверить» — она входит в панель и читает список.</p>"
                 "</details>")
    return "".join(parts)


# --------------------------------------------------------------------------
#  Доступы и заказы
# --------------------------------------------------------------------------

def _slot_boxes(checked: bool = True) -> str:
    items = []
    for target in vpn.slots():
        mark = " checked" if checked else ""
        items.append(f'<label><input type="checkbox" name="slot" value="{esc(target.key)}"{mark}> '
                     f"{esc(target.title)}</label> ")
    return "".join(items) or '<span class="muted">Нет настроенных панелей.</span>'


async def access_body(token: str, message: str = "", failed: str = "",
                      uid: str = "") -> str:
    parts = [_note("ok", message), _note("bad", failed)]
    titles = {item.key: item.title for item in vpn.slots()}

    # --- заявки ---
    pending = await vpn.pending()
    if pending:
        rows = []
        for person in pending:
            rows.append(
                f"<tr><td>{esc(who(person))}</td>"
                '<td><form method="post" action="/vpn/access/act">'
                f"{_hidden(token, uid=person)}{_slot_boxes()}"
                '<button name="action" value="issue" type="submit">Выдать</button> '
                '<button class="ghost danger" name="action" value="deny" type="submit">Отказать</button>'
                "</form></td></tr>"
            )
        parts.append('<div class="card"><h3>Заявки</h3><table>' + "".join(rows) + "</table></div>")
    else:
        parts.append('<div class="card"><h3>Заявки</h3><p class="muted">Новых заявок нет.</p></div>')

    # --- выдать вручную ---
    parts.append(
        '<div class="card"><h3>Выдать доступ</h3>'
        '<form method="post" action="/vpn/access/act">'
        f"{_hidden(token, action='issue')}"
        '<label><b>Человек</b> <span class="muted">(числовой id в Telegram или ключ вида vk:123)</span><br>'
        '<input type="text" name="uid" style="width:100%" autocomplete="off"></label>'
        f"<p>{_slot_boxes()}</p>"
        '<button type="submit">Выдать</button></form>'
        '<p class="muted">Срок и предел трафика — из настроек раздела «VPN»; если запись '
        "в панели уже есть, возвращается она же.</p></div>"
    )

    # --- карточка человека ---
    if uid:
        parts.append(await _person_card(token, uid, titles))

    # --- выданные ---
    records = await vpn.records()
    given = [(key, entry) for key, entry in records.items() if entry.get("panels")]
    if given:
        rows = []
        for key, entry in sorted(given, key=lambda item: str(item[0])):
            slots = ", ".join(esc(titles.get(slot, "#" + slot)) for slot in vpn.issued_slots(entry))
            rows.append(
                f"<tr><td>{esc(who(key))}</td><td>{slots}</td>"
                '<td style="text-align:right">'
                f'<a class="btn ghost" href="/vpn/access?uid={esc(key)}#person">карточка</a></td></tr>'
            )
        parts.append('<div class="card"><h3>Выданные доступы</h3><table>'
                     "<tr><th>Человек</th><th>Панели</th><th></th></tr>"
                     + "".join(rows) + "</table></div>")
    else:
        parts.append('<div class="card"><h3>Выданные доступы</h3>'
                     '<p class="muted">Пока никому не выдано.</p></div>')

    parts.append(await _orders_card(token))
    return "".join(parts)


async def _person_card(token: str, uid: str, titles: dict[str, str]) -> str:
    entry = await vpn.record(uid)
    if not entry or not entry.get("panels"):
        return f'<div class="card" id="person"><h3>{esc(who(uid))}</h3><p class="muted">Доступ не выдан.</p></div>'
    results = await vpn.statuses(uid)
    rows = []
    for key in vpn.issued_slots(entry):
        result = results.get(key)
        if isinstance(result, Account):
            state = esc(vpn.describe(result))
            on = result.enabled
        elif isinstance(result, PanelError):
            state, on = "⚠️ " + esc(str(result)), None
        else:
            state, on = "Записи в панели нет.", None
        toggle = ""
        if on is not None:
            word = "выключить" if on else "включить"
            toggle = ('<form class="inline" method="post" action="/vpn/access/act">'
                      f"{_hidden(token, uid=uid, slot=key, action='toggle', value='0' if on else '1')}"
                      f'<button class="ghost" type="submit">{word}</button></form> ')
        rows.append(
            f"<tr><td><b>{esc(titles.get(key, '#' + key))}</b></td><td>{state}</td>"
            '<td style="text-align:right;white-space:nowrap">'
            '<form class="inline" method="post" action="/vpn/access/act">'
            f"{_hidden(token, uid=uid, slot=key, action='extend')}"
            '<input type="number" name="days" min="1" max="3650" value="30" style="width:5em"> '
            '<button class="ghost" type="submit">продлить, дней</button></form> '
            f"{toggle}"
            '<form class="inline" method="post" action="/vpn/access/act" '
            "onsubmit=\"return confirm('Отозвать доступ и удалить запись в панели?')\">"
            f"{_hidden(token, uid=uid, slot=key, action='revoke')}"
            '<button class="ghost danger" type="submit">отозвать</button></form>'
            "</td></tr>"
        )
    return (f'<div class="card" id="person"><h3>{esc(who(uid))}</h3><table>'
            + "".join(rows) + "</table></div>")


async def _orders_card(token: str) -> str:
    if not features.enabled("vpn_sales"):
        return ('<div class="card"><h3>Заказы</h3><p class="muted">Продажа выключена — '
                "включите «Продажа VPN» выше на странице «VPN».</p></div>")
    orders = await vpnsales.recent(40)
    if not orders:
        return '<div class="card"><h3>Заказы</h3><p class="muted">Заказов пока нет.</p></div>'
    rows = []
    for item in orders:
        status = str(item.get("status"))
        order_id = str(item.get("id"))
        plan = item.get("plan") or {}
        desc = f"{plan.get('days', '?')} дн."
        if plan.get("traffic_gb"):
            desc += f", {plan['traffic_gb']} ГБ"
        if plan.get("devices"):
            desc += f", {plan['devices']} устр."
        buttons = []
        if status == vpnsales.NEW:
            buttons.append(("confirm", "подтвердить оплату", ""))
            buttons.append(("cancel", "отменить", "danger"))
        elif status == vpnsales.FAILED:
            buttons.append(("retry", "повторить выдачу", ""))
        acts = "".join(
            '<form class="inline" method="post" action="/vpn/access/act">'
            f"{_hidden(token, action='order_' + act, order=order_id, uid=str(item.get('uid', '')))}"
            f'<button class="ghost {cls}" type="submit">{label}</button></form> '
            for act, label, cls in buttons)
        rows.append(
            f"<tr><td>{_stamp(item.get('created'))}</td><td>{esc(who(str(item.get('uid', ''))))}</td>"
            f"<td>{esc(desc)}</td><td>{esc(item.get('amount', ''))} {esc(item.get('currency', ''))}</td>"
            f"<td>{esc(vpnsales.STATUS_TITLES.get(status, status))}</td>"
            f'<td style="text-align:right;white-space:nowrap">{acts}</td></tr>'
        )
    return ('<div class="card"><h3>Заказы</h3><table><tr><th>Когда</th><th>Кто</th><th>Тариф</th>'
            "<th>Сумма</th><th>Состояние</th><th></th></tr>" + "".join(rows) + "</table></div>")


async def access_act(form: Any, by: str, role: str) -> tuple[str, str]:
    """Действие над доступом. Возвращает (сообщение, ошибка)."""
    action = str(form.get("action", ""))
    uid = str(form.get("uid", "")).strip()
    slots = [str(item) for item in form.getall("slot", [])] if hasattr(form, "getall") else []
    try:
        if action == "issue":
            if not uid:
                return "", "Не указан человек."
            if not slots:
                return "", "Не выбрана ни одна панель."
            results = await vpn.issue(uid, slots, by, role)
            bad = [f"#{key}: {value}" for key, value in results.items() if isinstance(value, PanelError)]
            done = len(results) - len(bad)
            if bad:
                return (f"Выдано на панелях: {done}" if done else "",
                        "Не удалось: " + "; ".join(bad))
            return f"Выдано на панелях: {done}.", ""
        if action == "deny":
            await vpn.deny(uid, by, role)
            return "Заявка отклонена.", ""
        slot = str(form.get("slot", ""))
        if action == "extend":
            days = int(str(form.get("days", "0")) or 0)
            if not 1 <= days <= MAX_GRANT_DAYS:
                return "", f"Срок — от 1 до {MAX_GRANT_DAYS} дней."
            await vpn.extend(uid, slot, days, role)
            return f"Продлено на {days} дн.", ""
        if action == "toggle":
            await vpn.set_enabled(uid, slot, str(form.get("value", "")) == "1", role)
            return "Состояние изменено.", ""
        if action == "revoke":
            await vpn.revoke(uid, slot, role)
            return "Доступ отозван.", ""
        order_id = str(form.get("order", ""))
        if action == "order_confirm":
            await vpnsales.confirm(order_id, role, by)
            return "Оплата подтверждена, доступ выдаётся.", ""
        if action == "order_retry":
            await vpnsales.retry(order_id, role)
            return "Выдача повторена.", ""
        if action == "order_cancel":
            await vpnsales.cancel(order_id, uid, role)
            return "Заказ отменён.", ""
    except (PanelError, vpnsales.SaleError, ValueError) as exc:
        return "", str(exc)
    return "", "Неизвестное действие."


# --------------------------------------------------------------------------
#  Подписка бота
# --------------------------------------------------------------------------

def _until_text(user: dict[str, Any]) -> str:
    until = subscription.paid_until(user)
    return until[:10] if until else "—"


async def subscriptions_body(token: str, message: str = "", failed: str = "",
                             query: str = "") -> str:
    from .. import redeem, secrets
    from .panel import _setting_row

    parts = [_note("ok", message), _note("bad", failed)]

    # --- тарифы ---
    parts.append(
        '<div class="card"><h3>Тарифы</h3>'
        + _setting_row(secrets.BY_KEY["DIGEST_PLANS"], token, "/subscriptions")
        + f'<p class="muted">Пробный период: {subscription.TRIAL_DAYS} дней, один раз на человека; '
        "администрации подписка не нужна — у неё всё открыто. Подписка одна: оплата открывает "
        "и подборки, и загрузку видео без дневного предела. Подписка на VPN — отдельная: "
        "раздел «VPN».</p></div>"
    )

    # --- промокоды ---
    codes = await redeem.load()
    rows = []
    for item in codes:
        used = (f"{esc(who(str(item.get('used_by'))))}, {esc(str(item.get('used_at', ''))[:10])}"
                if item.get("used_by") else '<span class="ok">свободен</span>')
        rows.append(
            f"<tr><td><code>{esc(item.get('code'))}</code></td><td>{esc(item.get('days'))} дн.</td><td>{used}</td>"
            '<td style="text-align:right"><form class="inline" method="post" action="/subscriptions/act">'
            f"{_hidden(token, action='code_drop', code=str(item.get('code')))}"
            '<button class="ghost danger" type="submit">удалить</button></form></td></tr>'
        )
    table = ("<table><tr><th>Код</th><th>Даёт</th><th>Использован</th><th></th></tr>"
             + "".join(rows) + "</table>") if rows else '<p class="muted">Кодов нет.</p>'
    parts.append(
        '<div class="card"><h3>Промокоды</h3>' + table
        + '<form method="post" action="/subscriptions/act">'
        + _hidden(token, action="code_add")
        + '<label><b>Новые коды</b> <span class="muted">(через пробел, запятую или с новой строки; '
        "латиница, цифры и дефис, от 5 знаков)</span><br>"
        '<textarea name="codes" rows="2" style="width:100%"></textarea></label>'
        f'<label>Дней на код <input type="number" name="days" min="1" max="{MAX_GRANT_DAYS}" '
        f'value="{redeem.DEFAULT_DAYS}" style="width:6em"></label> '
        '<button type="submit">Завести</button></form></div>'
    )

    # --- люди ---
    needle = query.strip().lower()
    people = []
    for uid, user in storage.users().items():
        if needle:
            if needle in str(uid).lower() or needle in str(user.get("username", "")).lower():
                people.append((uid, user))
        elif subscription.paid(user):
            people.append((uid, user))
    people.sort(key=lambda item: subscription.paid_until(item[1]), reverse=True)
    shown = people[:MAX_PEOPLE_SHOWN]

    rows = []
    for uid, user in shown:
        role = str(user.get("role", ""))
        state = esc(subscription.describe(user, role))
        rows.append(
            f"<tr><td>{esc(who(str(uid)))}<br>"
            f'<span class="muted">{esc(roles.title(role))}</span></td>'
            f"<td>{state}<br><span class=\"muted\">до {esc(_until_text(user))}</span></td>"
            '<td style="text-align:right;white-space:nowrap">'
            '<form class="inline" method="post" action="/subscriptions/act">'
            f"{_hidden(token, action='grant', uid=str(uid))}"
            f'<input type="number" name="days" min="1" max="{MAX_GRANT_DAYS}" value="30" style="width:5em"> '
            '<button class="ghost" type="submit">добавить, дней</button></form> '
            '<form class="inline" method="post" action="/subscriptions/act" '
            "onsubmit=\"return confirm('Снять оплаченный срок?')\">"
            f"{_hidden(token, action='revoke', uid=str(uid))}"
            '<button class="ghost danger" type="submit">снять срок</button></form>'
            "</td></tr>"
        )
    if rows:
        body = ("<table><tr><th>Человек</th><th>Подписка</th><th></th></tr>"
                + "".join(rows) + "</table>")
    else:
        body = '<p class="muted">Никого не найдено.</p>' if needle else '<p class="muted">Платных подписок сейчас нет.</p>'
    more = (f'<p class="muted">Показаны первые {MAX_PEOPLE_SHOWN} из {len(people)}; уточните поиск.</p>'
            if len(people) > MAX_PEOPLE_SHOWN else "")
    parts.append(
        '<div class="card"><h3>Подписки людей</h3>'
        '<form method="get" action="/subscriptions"><input type="text" name="q" '
        f'value="{esc(query)}" placeholder="имя или id — найти любого; пусто — только платные">'
        ' <button class="ghost" type="submit">найти</button></form>'
        + body + more + "</div>"
    )
    return "".join(parts)


async def subscriptions_act(form: Any) -> tuple[str, str]:
    """Действие над подпиской бота. Возвращает (сообщение, ошибка)."""
    from .. import redeem

    action = str(form.get("action", ""))
    uid = str(form.get("uid", "")).strip()

    if action == "code_add":
        try:
            days = int(str(form.get("days", "") or redeem.DEFAULT_DAYS))
        except ValueError:
            return "", "Дни — число."
        if not 1 <= days <= MAX_GRANT_DAYS:
            return "", f"Срок кода — от 1 до {MAX_GRANT_DAYS} дней."
        added, skipped = await redeem.add(str(form.get("codes", "")), days)
        if not added:
            return "", "Ни один код не добавлен (неверный вид или уже есть)."
        tail = f" Пропущено: {len(skipped)}." if skipped else ""
        return f"Заведено кодов: {len(added)}.{tail}", ""
    if action == "code_drop":
        ok = await redeem.drop(str(form.get("code", "")))
        return ("Код удалён.", "") if ok else ("", "Такого кода нет.")

    user = storage.get_user(uid)
    if user is None:
        return "", "Человек не найден."
    if action == "grant":
        try:
            days = int(str(form.get("days", "0")) or 0)
        except ValueError:
            return "", "Дни — число."
        if not 1 <= days <= MAX_GRANT_DAYS:
            return "", f"Срок — от 1 до {MAX_GRANT_DAYS} дней."
        until = subscription.grant(user, days)
        await storage.save(uid)
        return f"Добавлено {days} дн., подписка до {until[:10]}.", ""
    if action == "revoke":
        had = subscription.revoke(user)
        await storage.save(uid)
        return ("Срок снят.", "") if had else ("", "Оплаченного срока не было.")
    return "", "Неизвестное действие."
