"""API для приложений HydraVPN: вход по коду из бота и выдача подписок (5.9.1).

Приложения — HydraVPN для Android и HydraVPN for Routers — не заводят
своих пользователей: человек уже есть в боте и уже получил там доступ.
Приложение лишь подключается к его аккаунту и забирает то, что выдано.

Как это устроено:

1. В боте («🔐 VPN» → «📱 Подключить приложение») человек получает
   одноразовый код на пять минут.
2. Приложение меняет код на токен устройства (`exchange`). Токен виден
   один раз; на сервере лежит только его SHA-256, так что база не выдаёт
   чужой вход.
3. По токену приложение читает профиль и подписки (`profile`,
   `subscriptions`). Читает — и только: выдачей и отзывом доступа по-прежнему
   распоряжается один суперадминистратор (решение 5.0.1), API ничего
   не выдаёт и не продлевает.
4. Устройство можно отключить из бота или самим приложением.

Ссылки подписок и токены в журнал не пишутся.
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
import secrets as secrets_module
import time
from typing import Any

log = logging.getLogger("radar.appapi")

META_KEY = "app_sessions"
CODE_TTL = 300
MAX_DEVICES = 5            # устройств на человека; старейшее вытесняется
SEEN_STEP = 300            # как часто обновляем «был на связи»
APPS = ("hydravpn", "hydravpn-router", "other")

_codes: dict[str, tuple[str, float]] = {}
_lock = asyncio.Lock()


def enabled() -> bool:
    from . import features

    return features.enabled("app_api")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --------------------------------------------------------------------------
#  Код из бота
# --------------------------------------------------------------------------

def issue_code(uid: str | int, now: float | None = None) -> str:
    """Одноразовый код на пять минут; прежний код человека гаснет."""
    moment = now if now is not None else time.time()
    for code in [c for c, (_, until) in _codes.items() if until < moment]:
        _codes.pop(code, None)
    for code in [c for c, (owner, _) in _codes.items() if owner == str(uid)]:
        _codes.pop(code, None)
    while True:
        code = f"{secrets_module.randbelow(10 ** 8):08d}"
        if code not in _codes:
            break
    _codes[code] = (str(uid), moment + CODE_TTL)
    return code


def _clean_app(app: str) -> str:
    app = (app or "").strip().lower()
    return app if app in APPS else "other"


def _clean_device(name: str) -> str:
    text = "".join(ch for ch in (name or "") if ch.isprintable()).strip()
    return text[:40] or "устройство"


async def _load() -> dict[str, dict[str, Any]]:
    from . import storage

    value = await storage.meta_get(META_KEY, {})
    return value if isinstance(value, dict) else {}


async def _save(sessions: dict[str, dict[str, Any]]) -> None:
    from . import storage

    await storage.meta_set(META_KEY, sessions)


async def exchange(code: str, device: str, app: str, address: str = "",
                   now: float | None = None) -> tuple[str, str, str]:
    """Код -> токен. Возвращает (токен, id устройства, причина отказа)."""
    from .web import auth

    moment = now if now is not None else time.time()
    if address and auth.rate_limited(address):
        return "", "", "слишком много попыток, подождите"
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    entry = _codes.pop(digits, None)
    if entry is None or entry[1] < moment:
        if address:
            auth.note_failure(address)
        return "", "", "код не подошёл или устарел"
    if address:
        auth.clear_failures(address)

    uid = entry[0]
    token = secrets_module.token_urlsafe(32)
    device_id = secrets_module.token_hex(4)
    async with _lock:
        sessions = await _load()
        mine = sorted((h for h, s in sessions.items() if s.get("uid") == uid),
                      key=lambda h: sessions[h].get("created", 0))
        for stale in mine[:max(0, len(mine) - MAX_DEVICES + 1)]:
            sessions.pop(stale, None)
        sessions[_hash(token)] = {
            "uid": uid, "id": device_id, "device": _clean_device(device),
            "app": _clean_app(app), "created": int(moment), "seen": int(moment),
        }
        await _save(sessions)
    log.info("Приложение подключено к аккаунту %s (%s)", uid, _clean_app(app))
    return token, device_id, ""


async def session_of(token: str, now: float | None = None) -> dict[str, Any] | None:
    """Сессия по токену или None. Время последнего обращения — не чаще раза в 5 минут."""
    if not token:
        return None
    key = _hash(token)
    sessions = await _load()
    found = sessions.get(key)
    if not found:
        return None
    moment = int(now if now is not None else time.time())
    if moment - int(found.get("seen", 0)) >= SEEN_STEP:
        async with _lock:
            sessions = await _load()
            if key in sessions:
                sessions[key]["seen"] = moment
                await _save(sessions)
    return dict(found)


async def devices(uid: str | int) -> list[dict[str, Any]]:
    mine = [dict(s) for s in (await _load()).values() if s.get("uid") == str(uid)]
    return sorted(mine, key=lambda s: s.get("created", 0))


async def revoke(uid: str | int, device_id: str | None = None) -> int:
    """Отключить устройство (или все, если id не указан). Возвращает число."""
    async with _lock:
        sessions = await _load()
        drop = [h for h, s in sessions.items()
                if s.get("uid") == str(uid) and (device_id is None or s.get("id") == device_id)]
        for key in drop:
            sessions.pop(key, None)
        if drop:
            await _save(sessions)
    return len(drop)


async def revoke_token(token: str) -> bool:
    async with _lock:
        sessions = await _load()
        if sessions.pop(_hash(token), None) is None:
            return False
        await _save(sessions)
        return True


# --------------------------------------------------------------------------
#  Что отдаём приложению
# --------------------------------------------------------------------------

async def profile(uid: str | int) -> dict[str, Any]:
    from . import storage, vpn

    user = storage.get_user(uid) or {}
    entry = await vpn.record(uid) or {}
    return {
        "user_id": str(uid),
        "username": user.get("username") or "",
        "blocked": bool(user.get("blocked")),
        "vpn": {
            "enabled": _vpn_on(),
            "state": entry.get("state") or "none",
            "panels": len(vpn.issued_slots(entry)),
        },
    }


def _vpn_on() -> bool:
    from . import features

    return features.enabled("vpn")


async def subscriptions(uid: str | int) -> list[dict[str, Any]]:
    """Подписки человека по всем выданным панелям.

    Блокированному человеку и при выключенном разделе VPN — пусто: приложение
    не должно получать то, что бот сам бы не показал.
    """
    from . import storage, vpn
    from .vpnpanels import Account, PanelError

    if not _vpn_on() or (storage.get_user(uid) or {}).get("blocked"):
        return []
    entry = await vpn.record(uid) or {}
    if not vpn.issued_slots(entry):
        return []
    titles = {item.key: item for item in vpn.slots()}
    results = await vpn.statuses(uid)
    items: list[dict[str, Any]] = []
    for key in vpn.issued_slots(entry):
        target = titles.get(key)
        result = results.get(key)
        item: dict[str, Any] = {
            "panel": key,
            "title": target.title if target else f"#{key}",
            "kind": target.client.kind if target else "",
            "link_kind": getattr(target.client, "link_kind", "subscription") if target else "",
            "state": "ok", "enabled": False, "expire": 0,
            "traffic_limit": 0, "traffic_used": 0, "url": "",
        }
        if isinstance(result, Account):
            item.update(enabled=result.enabled, expire=result.expire,
                        traffic_limit=result.traffic_limit,
                        traffic_used=result.traffic_used)
            url = result.subscription_url
            if not url:
                try:
                    url = await vpn.subscription(uid, key)
                except PanelError:
                    url = ""
            item["url"] = url
            if not url:
                item["state"] = "no_link"
        elif isinstance(result, PanelError):
            item["state"] = "panel_error"
        else:
            item["state"] = "missing"
        items.append(item)
    return items


__all__ = ["enabled", "issue_code", "exchange", "session_of", "devices", "revoke",
           "revoke_token", "profile", "subscriptions", "CODE_TTL", "MAX_DEVICES"]
