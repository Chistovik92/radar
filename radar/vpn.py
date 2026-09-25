"""Выдача VPN-доступа: несколько панелей, решение — только суперадминистратора.

С 5.0 — выдача уже авторизованным без платежей. С 5.0.1:

* **Несколько панелей сразу, в том числе разных.** Панели заводятся
  слотами (`VPN1_*` … `VPN6_*`), у каждого свой вид, адрес и вход.
  Человеку можно выдать доступ на одну панель или на несколько; у каждой
  своя ссылка. Обращения к разным панелям идут параллельно, и отказ одной
  не задерживает и не ломает остальные.
* **Ключи выдаёт только суперадминистратор.** Выдачи по роли больше нет
  (`VPN_AUTO_ROLE` из 5.0 убран): заявку видит и решает только он, и он
  же выбирает, на какие панели выдать. Проверка стоит здесь, в самой
  логике, а не только на кнопках: вызов `issue` от имени кого-то другого
  отклоняется, даже если кнопку кто-то подделал.

Как устроено хранение: запись о выдаче лежит в служебной таблице
(`meta`, ключ `vpn_accounts`) — состояние заявки и, для каждого слота,
имя в панели, вид и адрес панели на момент выдачи. Ссылка подписки
в базу не пишется: она берётся у панели при показе.

Продление возвращает **тот же** ключ: имя в панели выводится из ключа
пользователя, и повторная выдача находит прежнюю запись. Окончание срока
отключает доступ силами самой панели; бот ничего не опрашивает по
расписанию, и цикл оповещений с панелями не пересекается вовсе.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import features, roles
from .vpnpanels import GB, Account, Panel, PanelError, account_name, build

log = logging.getLogger("radar.vpn")

META_KEY = "vpn_accounts"
DAY = 86400
SLOTS = 6

PENDING = "pending"
ACTIVE = "active"
DENIED = "denied"

DEFAULT_DAYS = 30

# Поля слота: окружение VPN{n}_<ПОЛЕ>. Для первого слота читаются и имена
# из 5.0 (VPN_PANEL, VPN_PANEL_URL…), чтобы обновление не сбросило
# уже настроенную панель.
FIELDS = ("KIND", "TITLE", "URL", "TOKEN", "USER", "PASS", "INBOUND",
          "SUB_URL", "GROUPS", "CERT")
LEGACY = {
    "KIND": "VPN_PANEL", "URL": "VPN_PANEL_URL", "TOKEN": "VPN_PANEL_TOKEN",
    "USER": "VPN_PANEL_USER", "PASS": "VPN_PANEL_PASS",
    "INBOUND": "VPN_XUI_INBOUND", "SUB_URL": "VPN_SUB_URL",
    "GROUPS": "VPN_GROUPS",
}

# Записи читаются и пишутся целиком одной строкой meta. Два нажатия
# подряд иначе потеряли бы одно из изменений.
_lock = asyncio.Lock()


def _setting(key: str) -> str:
    from . import secrets

    return str(secrets.get(key) or "").strip()


def env_name(slot: int, field: str) -> str:
    return f"VPN{slot}_{field}"


def slot_value(slot: int, field: str) -> str:
    value = _setting(env_name(slot, field))
    if not value and slot == 1 and field in LEGACY:
        value = _setting(LEGACY[field])
    return value


@dataclass(frozen=True)
class Slot:
    """Настроенная панель: номер слота, подпись для людей и клиент."""

    number: int
    title: str
    client: Panel

    @property
    def key(self) -> str:
        return str(self.number)

    @property
    def fingerprint(self) -> str:
        """Вид и адрес панели. Сменили панель в слоте — прежние выдачи
        к новой не относятся, и бот не должен делать вид, что относятся."""
        source = f"{self.client.kind}|{self.client.url}"
        return hashlib.sha256(source.encode()).hexdigest()[:16]


def slot(number: int) -> Slot | None:
    kind = slot_value(number, "KIND")
    if not kind:
        return None
    groups = tuple(item.strip() for item in slot_value(number, "GROUPS").split(",")
                   if item.strip())
    inbound = slot_value(number, "INBOUND")
    client = build(
        kind,
        url=slot_value(number, "URL"),
        token=slot_value(number, "TOKEN"),
        user=slot_value(number, "USER"),
        password=slot_value(number, "PASS"),
        groups=groups,
        inbound=int(inbound) if inbound.isdigit() else 0,
        sub_url=slot_value(number, "SUB_URL"),
        cert=slot_value(number, "CERT"),
    )
    if client is None:
        return None
    title = slot_value(number, "TITLE") or f"{client.title} #{number}"
    return Slot(number, title, client)


def slots() -> list[Slot]:
    """Все настроенные панели по порядку слотов."""
    return [item for item in (slot(number) for number in range(1, SLOTS + 1)) if item]


def unknown_kinds() -> list[str]:
    """Слоты с незнакомым видом панели — чтобы опечатка не молчала."""
    wrong = []
    for number in range(1, SLOTS + 1):
        kind = slot_value(number, "KIND")
        if kind and build(kind, url="") is None:
            wrong.append(f"слот {number}: «{kind}»")
    return wrong


def ready() -> tuple[bool, str]:
    """Можно ли выдавать. Вторым значением — причина отказа для человека."""
    if not features.enabled("vpn"):
        return False, "Раздел VPN выключен."
    if not slots():
        wrong = unknown_kinds()
        if wrong:
            return False, "Незнакомый вид панели: " + ", ".join(wrong) + "."
        return False, ("Ни одна панель не настроена: задайте VPN1_KIND "
                       "и остальные поля слота в разделе ключей.")
    return True, ""


def default_days() -> int:
    value = _setting("VPN_DAYS")
    return int(value) if value.isdigit() and int(value) > 0 else DEFAULT_DAYS


def default_traffic() -> int:
    """Предел трафика новой записи в байтах, 0 — без предела."""
    value = _setting("VPN_TRAFFIC_GB")
    return int(value) * GB if value.isdigit() else 0


def can_decide(role: str | None) -> bool:
    """Кто выдаёт, продлевает и отключает доступ: только суперадминистратор."""
    return roles.is_superadmin(role)


def _require(role: str | None) -> None:
    if not can_decide(role):
        raise PanelError("Выдавать и менять доступ к VPN может только "
                         "суперадминистратор.")


# --------------------------------------------------------------------------
#  Записи о выдаче
# --------------------------------------------------------------------------

def _normalize(entry: dict[str, Any]) -> dict[str, Any]:
    """Запись 5.0 (одна панель, поля name/panel) → вид 5.0.1 со слотами."""
    entry = dict(entry)
    panels = entry.get("panels")
    if not isinstance(panels, dict):
        panels = {}
        if entry.get("state") == ACTIVE and entry.get("name"):
            panels["1"] = {"name": entry.get("name"), "kind": entry.get("panel", ""),
                           "issued": entry.get("issued", 0), "by": entry.get("by", "")}
        entry["panels"] = panels
    return entry


async def _load() -> dict[str, dict[str, Any]]:
    from . import storage

    value = await storage.meta_get(META_KEY, {})
    if not isinstance(value, dict):
        return {}
    return {uid: _normalize(entry) for uid, entry in value.items()
            if isinstance(entry, dict)}


async def _save(records: dict[str, dict[str, Any]]) -> None:
    from . import storage

    await storage.meta_set(META_KEY, records)


async def _edit(uid: str | int, change: Callable[[dict[str, Any]], None]
                ) -> dict[str, Any]:
    async with _lock:
        stored = await _load()
        entry = stored.get(str(uid)) or {"panels": {}}
        change(entry)
        stored[str(uid)] = entry
        await _save(stored)
        return entry


async def records() -> dict[str, dict[str, Any]]:
    return await _load()


async def record(uid: str | int) -> dict[str, Any] | None:
    return (await _load()).get(str(uid))


async def pending() -> list[str]:
    return [uid for uid, entry in (await _load()).items()
            if entry.get("state") == PENDING]


async def issued() -> list[str]:
    return [uid for uid, entry in (await _load()).items() if entry.get("panels")]


def issued_slots(entry: dict[str, Any] | None) -> list[str]:
    return sorted((entry or {}).get("panels", {}), key=lambda item: int(item))


# --------------------------------------------------------------------------
#  Параллельные обращения
# --------------------------------------------------------------------------

async def _each(targets: list[Slot], action: Callable[[Slot], Awaitable[Any]]
                ) -> dict[str, Any]:
    """Действие на каждой панели параллельно: {слот: результат или PanelError}.

    Панели независимы: медленная не задерживает быструю, упавшая
    не отменяет остальные. Непредвиденное исключение одной панели
    превращается в PanelError этой же панели, а не роняет всю операцию.
    """
    async def one(target: Slot) -> Any:
        try:
            async with target.client:
                return await action(target)
        except PanelError as exc:
            return exc
        except Exception as exc:  # noqa: BLE001
            log.warning("Сбой панели в слоте %s: %s", target.number, type(exc).__name__)
            return PanelError("Непредвиденный сбой при обращении к панели.")

    results = await asyncio.gather(*(one(target) for target in targets))
    return {target.key: result for target, result in zip(targets, results)}


def _pick(keys: list[str] | None) -> list[Slot]:
    available = slots()
    if keys is None:
        return available
    wanted = {str(key) for key in keys}
    return [item for item in available if item.key in wanted]


# --------------------------------------------------------------------------
#  Действия
# --------------------------------------------------------------------------

async def request(uid: str | int) -> str:
    """Заявка на доступ. Возвращает состояние после неё."""
    current = await record(uid)
    if current and current.get("state") == PENDING:
        return PENDING

    def change(entry: dict[str, Any]) -> None:
        entry["state"] = PENDING
        entry["requested"] = int(time.time())

    await _edit(uid, change)
    log.info("Заявка на VPN от %s", uid)
    return PENDING


async def deny(uid: str | int, by: str | int, role: str | None) -> None:
    _require(role)

    def change(entry: dict[str, Any]) -> None:
        entry["state"] = DENIED
        entry["decided"] = int(time.time())
        entry["by"] = str(by)

    await _edit(uid, change)
    log.info("Заявка на VPN от %s отклонена (%s)", uid, by)


async def issue(uid: str | int, keys: list[str], by: str | int, role: str | None,
                *, days: int | None = None) -> dict[str, Any]:
    """Выдаёт доступ на выбранных панелях. {слот: Account или PanelError}.

    Если запись в панели уже есть — возвращается она же: включается и,
    если срок истёк, получает новый. Ключ не меняется, и устройства,
    где он настроен, продолжают работать.
    """
    _require(role)
    ok, reason = ready()
    if not ok:
        raise PanelError(reason)
    targets = _pick(keys)
    if not targets:
        raise PanelError("Не выбрано ни одной панели.")

    return await _grant(uid, targets, by, period=(days or default_days()) * DAY,
                        traffic=default_traffic(), renew=False)


async def grant_paid(uid: str | int, keys: list[str], order_id: str, *,
                     days: int, traffic: int, devices: int = 0) -> dict[str, Any]:
    """Выдача по оплаченному заказу — без решения суперадминистратора.

    Зовёт её только `radar/vpnsales.py` и только для заказа, оплату
    которого подтвердил провайдер или суперадминистратор: решение
    о продажах он принял, включив их и задав тарифы. Бесплатного
    доступа этот путь не даёт — только оплаченный срок.

    В отличие от ручной выдачи срок **прибавляется** к оставшемуся:
    купивший продление не теряет дни, которые у него ещё были.
    """
    ok, reason = ready()
    if not ok:
        raise PanelError(reason)
    targets = _pick(keys)
    if not targets:
        raise PanelError("Панели тарифа не настроены.")
    return await _grant(uid, targets, f"order:{order_id}", period=days * DAY,
                        traffic=traffic, devices=devices, renew=True)


async def _grant(uid: str | int, targets: list[Slot], by: str | int, *, period: int,
                 traffic: int, devices: int = 0, renew: bool) -> dict[str, Any]:
    """Общая часть выдачи: завести или вернуть прежнюю запись на каждой панели.

    `renew=False` — ручная выдача: истёкший срок начинается заново,
    действующий не трогается. `renew=True` — оплата: срок прибавляется
    к большему из «сейчас» и прежнего окончания, предел трафика ставится
    по тарифу.
    """
    # Имя в панели: привязанная чужая запись (5.7.2) — её собственное,
    # иначе выведенное из ключа человека.
    current = (await record(uid) or {}).get("panels", {})

    def name_on(target: Slot) -> str:
        stored = current.get(target.key) or {}
        if stored.get("name") and not _stale(target, stored):
            return str(stored["name"])
        return account_name(uid)

    used_names: dict[str, str] = {}

    async def one(target: Slot) -> Account:
        client = target.client
        name = name_on(target)
        now = int(time.time())
        expire = now + period if client.supports_expiry else 0
        account = await client.get_user(name)
        if account is None and name != account_name(uid):
            # Привязанную запись удалили в самой панели: заводим свою,
            # под именем бота, а не под чужим идентификатором.
            name = account_name(uid)
            account = await client.get_user(name)
        used_names[target.key] = name
        if account is None:
            created = await client.create_user(name, expire, traffic)
            if not (devices and client.supports_devices):
                return created
            await client.set_devices(name, devices)
            return await client.get_user(name) or created
        else:
            if client.supports_expiry and account.expire:
                if renew:
                    await client.set_expiry(name, max(now, account.expire) + period)
                elif account.expire < now:
                    await client.set_expiry(name, expire)
            if renew and traffic and client.supports_traffic:
                # Предел в панелях — на весь расход, а не на период: до 5.6.2
                # продление ставило его равным тарифу, и потративший 45 ГБ
                # из 50 получал за новые 50 ГБ всего пять. Теперь тариф
                # прибавляется к израсходованному, а неистраченный остаток
                # действующего срока сохраняется — как и дни.
                used = max(0, account.traffic_used)
                left = 0
                if account.traffic_limit and (not account.expire or account.expire > now):
                    left = max(0, account.traffic_limit - used)
                await client.set_traffic(name, used + left + traffic)
            if not account.enabled:
                await client.enable(name)
        if devices and client.supports_devices:
            await client.set_devices(name, devices)
        return await client.get_user(name) or account

    results = await _each(targets, one)
    now = int(time.time())
    fingerprints = {target.key: target for target in targets}

    def change(entry: dict[str, Any]) -> None:
        panels = entry.setdefault("panels", {})
        for key, result in results.items():
            if isinstance(result, Account):
                previous = panels.get(key) or {}
                panels[key] = {"name": used_names.get(key) or name_on(fingerprints[key]),
                               "kind": fingerprints[key].client.kind,
                               "fp": fingerprints[key].fingerprint,
                               "issued": now, "by": str(by)}
                if previous.get("adopted") and previous.get("name") == panels[key]["name"]:
                    panels[key]["adopted"] = True
        if panels:
            entry["state"] = ACTIVE
            entry["decided"] = now
            entry["by"] = str(by)

    await _edit(uid, change)
    done = [key for key, result in results.items() if isinstance(result, Account)]
    log.info("VPN %s: выдано на слотах %s (%s)", uid, done or "—", by)
    return results


def _stale(target: Slot, stored: dict[str, Any]) -> bool:
    fingerprint = stored.get("fp")
    return bool(fingerprint) and fingerprint != target.fingerprint


async def _on_issued(uid: str | int, keys: list[str] | None,
                     action: Callable[[Slot, str], Awaitable[Any]]) -> dict[str, Any]:
    entry = await record(uid) or {}
    panels = entry.get("panels", {})
    targets = [item for item in _pick(keys) if item.key in panels]

    async def one(target: Slot) -> Any:
        if _stale(target, panels[target.key]):
            raise PanelError("Панель в этом слоте заменена после выдачи — "
                             "выдайте доступ заново.")
        return await action(target, str(panels[target.key].get("name") or account_name(uid)))

    return await _each(targets, one)


async def extend(uid: str | int, key: str, days: int, role: str | None) -> Account:
    """Сдвигает срок на `days` дней от большего из «сейчас» и прежнего срока."""
    _require(role)

    async def action(target: Slot, name: str) -> Account:
        client = target.client
        if not client.supports_expiry:
            raise PanelError(f"{client.title} не поддерживает сроки.")
        account = await client.get_user(name)
        if account is None:
            raise PanelError("Учётной записи в панели нет — выдайте доступ заново.")
        if account.expire == 0:
            # Бессрочную запись продлевать некуда: сдвиг превратил бы её
            # в срочную, а это уже урезание, а не продление.
            return account
        now = int(time.time())
        await client.set_expiry(name, max(now, account.expire) + days * DAY)
        if not account.enabled:
            await client.enable(name)
        return await client.get_user(name) or account

    result = (await _on_issued(uid, [key], action)).get(str(key))
    if result is None:
        raise PanelError("На этой панели доступ не выдавался.")
    if isinstance(result, PanelError):
        raise result
    log.info("VPN %s продлён на %s дн. (слот %s)", uid, days, key)
    return result


async def set_enabled(uid: str | int, key: str, value: bool, role: str | None) -> None:
    _require(role)

    async def action(target: Slot, name: str) -> None:
        if value:
            await target.client.enable(name)
        else:
            await target.client.disable(name)

    result = (await _on_issued(uid, [key], action)).get(str(key), PanelError(
        "На этой панели доступ не выдавался."))
    if isinstance(result, PanelError):
        raise result
    log.info("VPN %s: слот %s %s", uid, key, "включён" if value else "выключен")


async def revoke(uid: str | int, key: str, role: str | None) -> None:
    """Выключает доступ на панели и забывает выдачу.

    Запись в самой панели не удаляется: удаление необратимо, а выключенную
    можно вернуть тем же ключом. Если панель недоступна, выдача всё равно
    забывается — решение суперадминистратора важнее ответа панели,
    а оставшуюся запись он выключит в панели сам.
    """
    _require(role)

    async def action(target: Slot, name: str) -> None:
        await target.client.disable(name)

    results = await _on_issued(uid, [key], action)

    def change(entry: dict[str, Any]) -> None:
        entry.get("panels", {}).pop(str(key), None)
        if not entry.get("panels") and entry.get("state") == ACTIVE:
            entry["state"] = ""

    await _edit(uid, change)
    failure = results.get(str(key))
    if isinstance(failure, PanelError):
        raise PanelError(f"Выдача забыта, но панель не ответила: {failure}")


#  Привязка уже заведённых в панелях клиентов (5.7.2)
#
#  До 5.7.2 бот знал только записи, которые завёл сам («radar_<id>»).
#  Клиенты, заведённые руками или другим ботом (vpn-bot-3xui и подобные
#  пишут Telegram-id в `tgId`, email или комментарий), к аккаунту не
#  относились: человек их не видел, продление заводило вторую запись.
#  Теперь суперадминистратор привязывает их — по найденным совпадениям
#  или вручную. Привязка ничего в панели не меняет: запись остаётся
#  прежней, с прежним ключом, сроком и трафиком.

@dataclass(frozen=True)
class Match:
    """Предложение привязки: клиент панели и человек, чей Telegram-id в нём."""

    uid: str
    key: str
    ref: str
    title: str
    reason: str


def _mentions(text: str, uid: str) -> bool:
    import re

    return bool(uid) and re.search(rf"(?<!\d){re.escape(uid)}(?!\d)", text or "") is not None


def match_reason(client: Any, uid: str) -> str:
    """Почему клиент панели похож на человека `uid`. Пусто — не похож.

    Короткие числа не сопоставляются: «12345» в комментарии скорее
    номер заказа, чем Telegram-id. Id из собственного поля панели
    (`tgId` и подобных) — точное совпадение, ему верим сильнее.
    """
    if not uid.isdigit() or len(uid) < 6:
        return ""
    if client.telegram and client.telegram == uid:
        return "Telegram-id в поле панели"
    for note in client.notes:
        if _mentions(note, uid):
            return "Telegram-id в имени или комментарии"
    return ""


async def _bound(stored: dict[str, dict[str, Any]]) -> dict[tuple[str, str], str]:
    """Уже занятые записи: (слот, имя в панели) → чей аккаунт."""
    taken = {}
    for owner, entry in stored.items():
        for key, info in (entry.get("panels") or {}).items():
            if info.get("name"):
                taken[(str(key), str(info["name"]))] = owner
    return taken


async def clients(key: str, role: str | None) -> list[Any]:
    """Клиенты одной панели, ещё ни к кому не привязанные."""
    _require(role)
    target = next(iter(_pick([key])), None)
    if target is None:
        raise PanelError("Такой панели нет.")
    result = (await _each([target], lambda item: item.client.list_clients()))[target.key]
    if isinstance(result, PanelError):
        raise result
    taken = await _bound(await _load())
    return [item for item in result if (target.key, item.ref) not in taken]


async def matches(role: str | None) -> tuple[list[Match], dict[str, str]]:
    """Совпадения по всем панелям: клиенты, где записан Telegram-id
    зарегистрированного в боте человека. Второе значение — отказы панелей."""
    from . import storage
    from .identity import is_telegram

    _require(role)
    people = [uid for uid in storage.users() if is_telegram(uid)]
    stored = await _load()
    taken = await _bound(stored)
    results = await _each(slots(), lambda item: item.client.list_clients())
    found: list[Match] = []
    errors: dict[str, str] = {}
    for key, result in results.items():
        if isinstance(result, PanelError):
            errors[key] = str(result)
            continue
        for client in result:
            if (key, client.ref) in taken:
                continue
            for uid in people:
                if key in ((stored.get(uid) or {}).get("panels") or {}):
                    continue   # на этой панели у человека уже есть выдача
                reason = match_reason(client, uid)
                if reason:
                    found.append(Match(uid, key, client.ref, client.title, reason))
    return found, errors


async def bind(uid: str | int, key: str, ref: str, by: str | int,
               role: str | None) -> Account:
    """Привязать существующую запись панели к человеку. В панели не меняется ничего."""
    _require(role)
    target = next(iter(_pick([key])), None)
    if target is None:
        raise PanelError("Такой панели нет.")
    stored = await _load()
    owner = (await _bound(stored)).get((target.key, str(ref)))
    if owner and owner != str(uid):
        raise PanelError("Эта запись уже привязана к другому человеку.")
    if target.key in ((stored.get(str(uid)) or {}).get("panels") or {}) and owner != str(uid):
        raise PanelError("На этой панели у человека уже есть доступ — сначала отзовите его.")
    result = (await _each([target], lambda item: item.client.get_user(str(ref))))[target.key]
    if isinstance(result, PanelError):
        raise result
    if result is None:
        raise PanelError("Такой записи в панели нет.")
    now = int(time.time())

    def change(entry: dict[str, Any]) -> None:
        entry.setdefault("panels", {})[target.key] = {
            "name": str(ref), "kind": target.client.kind, "fp": target.fingerprint,
            "issued": now, "by": str(by), "adopted": True}
        entry["state"] = ACTIVE
        entry["decided"] = now
        entry["by"] = str(by)

    await _edit(uid, change)
    log.info("VPN %s: привязана существующая запись на слоте %s (%s)", uid, target.key, by)
    return result


async def forget(uid: str | int, key: str, role: str | None) -> None:
    """Снять привязку, не трогая запись в панели (в отличие от `revoke`,
    который её выключает): для ошибочной привязки чужого клиента."""
    _require(role)

    def change(entry: dict[str, Any]) -> None:
        entry.get("panels", {}).pop(str(key), None)
        if not entry.get("panels") and entry.get("state") == ACTIVE:
            entry["state"] = ""

    await _edit(uid, change)
    log.info("VPN %s: привязка на слоте %s снята без изменений в панели", uid, key)


async def statuses(uid: str | int) -> dict[str, Any]:
    """Состояние на каждой выданной панели: {слот: Account, None или PanelError}."""
    async def action(target: Slot, name: str) -> Account | None:
        return await target.client.get_user(name)

    return await _on_issued(uid, None, action)


async def subscription(uid: str | int, key: str) -> str:
    async def action(target: Slot, name: str) -> str:
        return await target.client.subscription_url(name)

    result = (await _on_issued(uid, [key], action)).get(str(key))
    if result is None:
        raise PanelError("На этой панели доступ не выдавался.")
    if isinstance(result, PanelError):
        raise result
    return result


async def check_all() -> dict[str, tuple[bool, str]]:
    """Проверка всех панелей разом — для кнопки и для диагностики."""
    async def action(target: Slot) -> str:
        return await target.client.check()

    results = await _each(slots(), action)
    return {key: (not isinstance(value, PanelError), str(value))
            for key, value in results.items()}


SELFTEST_NAME = "radar_selftest"


async def selftest_panel(panel: Panel, name: str = SELFTEST_NAME) -> list[str]:
    """Полный круг на одной панели: завести, прочитать, продлить, выключить,
    включить, сменить предел, получить ссылку — и выключить в конце.

    Каждый шаг проверяется по ответу панели, а не только вызывается:
    панель, которая вернула 200 и ничего не сделала, здесь не пройдёт.
    Тестовая запись остаётся в панели выключенной — доступа она не даёт,
    а удалять записи бот не умеет намеренно.
    """
    def expect(condition: bool, what: str) -> None:
        if not condition:
            raise PanelError(f"проверка не прошла: {what}")

    notes = []
    expire = int(time.time()) + 30 * DAY
    async with panel:
        notes.append(await panel.check())
        account = await panel.get_user(name)
        if account is None:
            account = await panel.create_user(name, expire if panel.supports_expiry else 0,
                                              5 * GB)
        else:
            await panel.enable(name)
            if panel.supports_expiry:
                await panel.set_expiry(name, expire)
        got = await panel.get_user(name)
        expect(got is not None, "созданная запись не находится")
        expect(got.enabled, "запись не включена")
        if panel.supports_expiry:
            expect(abs(got.expire - expire) <= DAY, "срок не совпал")
            await panel.set_expiry(name, expire + 10 * DAY)
            got = await panel.get_user(name)
            expect(abs(got.expire - expire - 10 * DAY) <= DAY, "срок не продлился")
        await panel.disable(name)
        expect(not (await panel.get_user(name)).enabled, "запись не выключилась")
        await panel.enable(name)
        expect((await panel.get_user(name)).enabled, "запись не включилась")
        if panel.supports_traffic:
            await panel.set_traffic(name, 7 * GB)
        expect(bool(await panel.subscription_url(name)), "пустая ссылка")
        expect(await panel.get_user("radar_absent_probe") is None,
               "несуществующая запись нашлась")
        await panel.disable(name)
    notes.append(f"полный круг пройден, ссылка: {panel.link_kind}; "
                 f"запись {name} оставлена выключенной")
    return notes


async def selftest_all() -> dict[str, tuple[bool, str]]:
    """Полный круг на всех панелях разом."""
    async def action(target: Slot) -> str:
        return "; ".join(await selftest_panel(target.client))

    results = await _each(slots(), action)
    return {key: (not isinstance(value, PanelError), str(value))
            for key, value in results.items()}


# --------------------------------------------------------------------------
#  Показ
# --------------------------------------------------------------------------

def format_bytes(value: int, lang: str = "ru") -> str:
    from . import i18n

    if value >= GB:
        return f"{value / GB:.1f} {i18n.t('vpn.gb', lang, 'ГБ')}"
    return f"{value / 1024 ** 2:.0f} {i18n.t('vpn.mb', lang, 'МБ')}"


def describe(account: Account, lang: str = "ru") -> str:
    """Срок, трафик и состояние одной записью — для человека."""
    from datetime import datetime, timezone

    from . import i18n

    lines = []
    if account.expire:
        until = datetime.fromtimestamp(account.expire, timezone.utc).strftime("%d.%m.%Y")
        left = max(0, (account.expire - int(time.time())) // DAY)
        lines.append(i18n.t("vpn.until", lang, "Срок: до {until} (осталось {left} дн.)")
                     .format(until=until, left=left))
    else:
        lines.append(i18n.t("vpn.forever", lang, "Срок: бессрочно"))
    used = format_bytes(account.traffic_used, lang)
    if account.traffic_limit:
        lines.append(i18n.t("vpn.traffic", lang, "Трафик: {used} из {limit}")
                     .format(used=used, limit=format_bytes(account.traffic_limit, lang)))
    else:
        lines.append(i18n.t("vpn.traffic_free", lang, "Трафик: {used}, без предела")
                     .format(used=used))
    if not account.enabled:
        lines.append(i18n.t("vpn.disabled", lang, "⛔ Доступ отключён"))
    return "\n".join(lines)
