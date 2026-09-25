"""Продажа VPN-доступа по тарифам (с 5.0.2).

Пункт 4 блока 5.0. Тариф — срок, предел трафика и число устройств;
цены задаёт суперадминистратор строкой `VPN_PLANS` в разделе ключей,
как уже задаются цены подписки на подборки. Оплата открывает доступ,
окончание срока его отключает силами панели, продление возвращает
**тот же** ключ и прибавляет дни к оставшимся.

Кто решает. Бесплатно доступ по-прежнему выдаёт только суперадминистратор
(`radar/vpn.py`). Продажи — его же решение, принятое заранее: они
работают только при включённой возможности `vpn_sales` и заданных
тарифах. С ручным провайдером каждую оплату подтверждает он сам.

Заказ проходит состояния:

    new → paid → done
               ↘ failed   (оплачено, но выдать не удалось — повтор кнопкой)
    new → expired | cancelled

Переход `new → paid` делается под замком и один раз: два нажатия
«Я оплатил» подряд не выдадут доступ дважды и не продлят его на два
срока. Ссылки и токены в заказ не пишутся.
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
import secrets as pysecrets
import time
from dataclasses import asdict, dataclass
from typing import Any

from . import features, payments, vpn
from .vpnpanels import GB, Account, PanelError

log = logging.getLogger("radar.vpnsales")

META_KEY = "vpn_orders"
DEFAULT_CURRENCY = "RUB"
# Неоплаченный счёт живёт сутки: дольше держать цену, которую
# суперадминистратор мог уже поменять, незачем.
ORDER_TTL = 86400

NEW = "new"
PAID = "paid"
DONE = "done"
FAILED = "failed"
EXPIRED = "expired"
CANCELLED = "cancelled"

_lock = asyncio.Lock()

_PLAN_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*:\s*(\d+)\s*:\s*(\d+(?:[.,]\d{1,2})?)\s*$")


class SaleError(Exception):
    """Отказ продажи, понятный человеку."""


@dataclass(frozen=True)
class Plan:
    """Тариф: срок, трафик (0 — без предела), устройства (0 — без предела), цена."""

    days: int
    traffic_gb: int
    devices: int
    price: float

    def title(self, currency: str) -> str:
        parts = [f"{self.days} дн."]
        parts.append(f"{self.traffic_gb} ГБ" if self.traffic_gb else "без предела трафика")
        if self.devices:
            parts.append(f"до {self.devices} устр.")
        return f"{', '.join(parts)} — {format_price(self.price)} {currency}"


def format_price(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _setting(key: str) -> str:
    from . import secrets

    return str(secrets.get(key) or "").strip()


def parse_plans(raw: str) -> list[Plan]:
    """«дни:трафикГБ:устройства:цена» через точку с запятой.

    Негодные куски пропускаются, а не роняют весь список: опечатка
    в одном тарифе не должна снимать с продажи остальные.
    """
    plans = []
    for chunk in (raw or "").split(";"):
        match = _PLAN_RE.match(chunk)
        if not match:
            continue
        days, traffic, devices = (int(match.group(n)) for n in (1, 2, 3))
        price = float(match.group(4).replace(",", "."))
        if days <= 0 or price <= 0:
            continue
        plans.append(Plan(days, traffic, devices, price))
    return plans


def plans() -> list[Plan]:
    return parse_plans(_setting("VPN_PLANS"))


def currency() -> str:
    return (_setting("VPN_CURRENCY") or DEFAULT_CURRENCY).upper()


def sale_slots() -> list[str]:
    """На каких панелях продаётся доступ. Пусто в настройке — на всех."""
    configured = [item.key for item in vpn.slots()]
    wanted = [item.strip() for item in _setting("VPN_PLAN_SLOTS").split(",") if item.strip()]
    return [key for key in configured if not wanted or key in wanted]


def ready() -> tuple[bool, str]:
    if not features.enabled("vpn_sales"):
        return False, "Продажа VPN выключена."
    ok, reason = vpn.ready()
    if not ok:
        return False, reason
    if not plans():
        return False, "Тарифы не заданы: VPN_PLANS в разделе ключей."
    if not sale_slots():
        return False, "Ни одна панель не выбрана для продажи (VPN_PLAN_SLOTS)."
    problems = payments.provider().problems()
    if problems:
        return False, "Оплата не настроена: " + ", ".join(problems) + "."
    return True, ""


# --------------------------------------------------------------------------
#  Заказы
# --------------------------------------------------------------------------

async def _load() -> dict[str, dict[str, Any]]:
    from . import storage

    value = await storage.meta_get(META_KEY, {})
    return dict(value) if isinstance(value, dict) else {}


async def _save(orders: dict[str, dict[str, Any]]) -> None:
    from . import storage

    await storage.meta_set(META_KEY, orders)


def _expired(order: dict[str, Any], now: float | None = None) -> bool:
    return (order.get("status") == NEW
            and (now or time.time()) - int(order.get("created") or 0) > ORDER_TTL)


async def order(order_id: str) -> dict[str, Any] | None:
    found = (await _load()).get(order_id)
    if found and _expired(found):
        found = dict(found, status=EXPIRED)
    return found


async def orders_of(uid: str | int) -> list[dict[str, Any]]:
    now = time.time()
    rows = [dict(item, status=EXPIRED) if _expired(item, now) else item
            for item in (await _load()).values() if item.get("uid") == str(uid)]
    return sorted(rows, key=lambda item: -int(item.get("created") or 0))


async def recent(limit: int = 20) -> list[dict[str, Any]]:
    now = time.time()
    rows = [dict(item, status=EXPIRED) if _expired(item, now) else item
            for item in (await _load()).values()]
    return sorted(rows, key=lambda item: -int(item.get("created") or 0))[:limit]


async def create(uid: str | int, index: int) -> dict[str, Any]:
    """Заказ по тарифу с номером `index` в текущем списке.

    Номер тарифа приходит из кнопки, а кнопку подделать легко, — поэтому
    тариф берётся из списка на сервере, а цена запоминается в заказе:
    сменит суперадминистратор цены, пока человек платит, — заплаченное
    всё равно соответствует тому, что было показано.
    """
    ok, reason = ready()
    if not ok:
        raise SaleError(reason)
    available = plans()
    if not 0 <= index < len(available):
        raise SaleError("Такого тарифа нет.")
    plan = available[index]
    provider = payments.provider()
    order_id = pysecrets.token_hex(5)
    try:
        invoice = await provider.create_invoice(
            plan.price, currency(), f"VPN: {plan.title(currency())}", f"vpn:{order_id}",
            expires_in=ORDER_TTL,
        )
    except payments.PaymentError as exc:
        raise SaleError(str(exc))

    now = int(time.time())
    entry = {
        "id": order_id, "uid": str(uid), "plan": asdict(plan), "slots": sale_slots(),
        "provider": provider.kind, "invoice": invoice.id, "url": invoice.url,
        "amount": plan.price, "currency": currency(), "status": NEW,
        "created": now, "updated": now,
    }
    async with _lock:
        stored = await _load()
        stored[order_id] = entry
        await _save(stored)
    log.info("VPN: заказ %s от %s, %s %s, %s", order_id, uid, plan.price,
             currency(), provider.kind)
    return entry


async def _move(order_id: str, allowed: tuple[str, ...], status: str,
                **fields: Any) -> dict[str, Any] | None:
    """Смена состояния, только если текущее — из `allowed`. Под замком."""
    async with _lock:
        stored = await _load()
        entry = stored.get(order_id)
        if entry is None or entry.get("status") not in allowed or (
                NEW in allowed and entry.get("status") == NEW and _expired(entry)):
            return None
        entry = dict(entry, status=status, updated=int(time.time()), **fields)
        stored[order_id] = entry
        await _save(stored)
        return entry


async def _fulfil(entry: dict[str, Any]) -> dict[str, Any]:
    """Выдача по оплаченному заказу. Вызывается ровно один раз на заказ."""
    plan = entry["plan"]
    try:
        results = await vpn.grant_paid(
            entry["uid"], entry["slots"], entry["id"], days=int(plan["days"]),
            traffic=int(plan["traffic_gb"]) * GB, devices=int(plan["devices"]),
        )
        granted = [key for key, value in results.items() if isinstance(value, Account)]
        errors = {key: str(value) for key, value in results.items()
                  if isinstance(value, PanelError)}
    except PanelError as exc:
        granted, errors = [], {"*": str(exc)}
    status = DONE if granted else FAILED
    final = await _move(entry["id"], (PAID,), status, granted=granted, errors=errors)
    log.info("VPN: заказ %s — %s (панели %s)", entry["id"], status, granted or "—")
    return final or dict(entry, status=status, granted=granted, errors=errors)


async def check(order_id: str, uid: str | int) -> dict[str, Any]:
    """«Я оплатил»: спросить провайдера и, если оплачено, выдать доступ."""
    entry = await order(order_id)
    if entry is None or entry.get("uid") != str(uid):
        raise SaleError("Заказ не найден.")
    if entry["status"] != NEW:
        return entry
    provider = payments.provider()
    if provider.kind != entry.get("provider"):
        raise SaleError("Способ оплаты сменился — оформите заказ заново.")
    if provider.manual:
        return entry
    try:
        status = await provider.status(entry["invoice"])
    except payments.PaymentError as exc:
        raise SaleError(str(exc))
    if status == payments.EXPIRED:
        return await _move(order_id, (NEW,), EXPIRED) or dict(entry, status=EXPIRED)
    if status != payments.PAID:
        return entry
    moved = await _move(order_id, (NEW,), PAID, paid=int(time.time()))
    if moved is None:
        # Кто-то успел раньше — второе нажатие ничего не выдаёт.
        return await order(order_id) or entry
    return await _fulfil(moved)


async def confirm(order_id: str, role: str | None, by: str | int) -> dict[str, Any]:
    """Ручное подтверждение оплаты — только суперадминистратор."""
    if not vpn.can_decide(role):
        raise SaleError("Подтверждать оплату может только суперадминистратор.")
    moved = await _move(order_id, (NEW,), PAID, paid=int(time.time()), confirmed_by=str(by))
    if moved is None:
        entry = await order(order_id)
        if entry is None:
            raise SaleError("Заказ не найден.")
        raise SaleError(f"Заказ уже не ждёт оплаты: {entry['status']}.")
    return await _fulfil(moved)


async def retry(order_id: str, role: str | None) -> dict[str, Any]:
    """Повторить выдачу по оплаченному заказу, где она не удалась."""
    if not vpn.can_decide(role):
        raise SaleError("Повторять выдачу может только суперадминистратор.")
    moved = await _move(order_id, (FAILED,), PAID)
    if moved is None:
        raise SaleError("Повторять нечего: заказ не в состоянии «не выдано».")
    return await _fulfil(moved)


async def cancel(order_id: str, uid: str | int, role: str | None) -> dict[str, Any]:
    entry = await order(order_id)
    if entry is None or (entry.get("uid") != str(uid) and not vpn.can_decide(role)):
        raise SaleError("Заказ не найден.")
    moved = await _move(order_id, (NEW,), CANCELLED)
    if moved is None:
        raise SaleError("Отменить можно только неоплаченный заказ.")
    return moved


STATUS_TITLES = {
    NEW: "ждёт оплаты", PAID: "оплачен, выдаётся", DONE: "выдан",
    FAILED: "оплачен, выдать не удалось", EXPIRED: "истёк", CANCELLED: "отменён",
}
