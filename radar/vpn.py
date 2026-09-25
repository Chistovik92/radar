"""Выдача VPN-доступа уже авторизованным (с 5.0).

Первый шаг блока 5.0 и единственный, который обходится без платежей:
человек, который уже есть в боте, получает доступ по решению
администратора или сразу — по роли. Платежи и тарифы придут следующими
выпусками тем же слоем (`radar/vpnpanels.py`).

Как устроено:

* запись о выдаче хранится в служебной таблице (`meta`, ключ
  `vpn_accounts`): состояние, имя в панели, кто и когда выдал. Ссылка
  подписки в базу не пишется — она берётся у панели при показе, так
  её не придётся отзывать из резервных копий;
* продление возвращает **тот же** ключ: имя в панели выводится из ключа
  пользователя, и повторная выдача находит прежнюю запись, а не заводит
  новую — иначе человеку пришлось бы перенастраивать все устройства;
* окончание срока отключает доступ силами самой панели — все три это
  умеют; бот ничего по расписанию не опрашивает, и цикл оповещений
  с панелями не пересекается вовсе.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from . import features, roles
from .vpnpanels import GB, Account, Panel, PanelError, account_name, build

log = logging.getLogger("radar.vpn")

META_KEY = "vpn_accounts"
DAY = 86400

PENDING = "pending"
ACTIVE = "active"
DENIED = "denied"

DEFAULT_DAYS = 30
# «none» — выдача только по заявке, без исключений по роли.
AUTO_ROLES = ("none",) + roles.ORDER

# Записи читаются и пишутся целиком одной строкой meta. Два нажатия
# подряд (одобрить одну заявку и тут же другую) иначе потеряли бы одно
# из изменений.
_lock = asyncio.Lock()


def _setting(key: str) -> str:
    from . import secrets

    return str(secrets.get(key) or "").strip()


def panel() -> Panel | None:
    """Клиент панели из настроек или None, если VPN_PANEL не задан."""
    groups = tuple(item.strip() for item in _setting("VPN_GROUPS").split(",")
                   if item.strip())
    inbound = _setting("VPN_XUI_INBOUND")
    return build(
        _setting("VPN_PANEL"),
        url=_setting("VPN_PANEL_URL"),
        token=_setting("VPN_PANEL_TOKEN"),
        user=_setting("VPN_PANEL_USER"),
        password=_setting("VPN_PANEL_PASS"),
        groups=groups,
        inbound=int(inbound) if inbound.isdigit() else 0,
        sub_url=_setting("VPN_SUB_URL"),
    )


def ready() -> tuple[bool, str]:
    """Можно ли выдавать. Вторым значением — причина отказа для человека."""
    if not features.enabled("vpn"):
        return False, "Раздел VPN выключен."
    client = panel()
    if client is None:
        return False, ("Панель не выбрана: задайте VPN_PANEL — "
                       "3xui, pasarguard или remnawave.")
    problems = client.problems()
    if problems:
        return False, "Панель не настроена: " + ", ".join(problems) + "."
    return True, ""


def default_days() -> int:
    value = _setting("VPN_DAYS")
    return int(value) if value.isdigit() and int(value) > 0 else DEFAULT_DAYS


def default_traffic() -> int:
    """Предел трафика новой записи в байтах, 0 — без предела."""
    value = _setting("VPN_TRAFFIC_GB")
    return int(value) * GB if value.isdigit() else 0


def auto_role() -> str:
    """С какой роли доступ выдаётся без заявки. По умолчанию — администрации."""
    value = _setting("VPN_AUTO_ROLE").lower()
    return value if value in AUTO_ROLES else roles.ADMIN


def issues_without_request(role: str | None) -> bool:
    threshold = auto_role()
    if threshold == "none":
        return False
    return roles.at_least(role, threshold)


# --------------------------------------------------------------------------
#  Записи о выдаче
# --------------------------------------------------------------------------

async def _load() -> dict[str, dict[str, Any]]:
    from . import storage

    value = await storage.meta_get(META_KEY, {})
    return dict(value) if isinstance(value, dict) else {}


async def _save(records: dict[str, dict[str, Any]]) -> None:
    from . import storage

    await storage.meta_set(META_KEY, records)


async def records() -> dict[str, dict[str, Any]]:
    return await _load()


async def record(uid: str | int) -> dict[str, Any] | None:
    return (await _load()).get(str(uid))


async def _update(uid: str | int, **fields: Any) -> dict[str, Any]:
    async with _lock:
        stored = await _load()
        entry = dict(stored.get(str(uid)) or {})
        entry.update(fields)
        stored[str(uid)] = entry
        await _save(stored)
        return entry


async def pending() -> list[str]:
    return [uid for uid, entry in (await _load()).items()
            if entry.get("state") == PENDING]


async def issued() -> list[str]:
    return [uid for uid, entry in (await _load()).items()
            if entry.get("state") == ACTIVE]


# --------------------------------------------------------------------------
#  Действия
# --------------------------------------------------------------------------

async def request(uid: str | int) -> str:
    """Заявка на доступ. Возвращает состояние после неё."""
    current = await record(uid)
    if current and current.get("state") in (ACTIVE, PENDING):
        return str(current["state"])
    await _update(uid, state=PENDING, requested=int(time.time()))
    log.info("Заявка на VPN от %s", uid)
    return PENDING


async def forget(uid: str | int) -> None:
    """Убирает запись о выдаче — когда в панели её больше нет."""
    async with _lock:
        stored = await _load()
        if stored.pop(str(uid), None) is not None:
            await _save(stored)


async def deny(uid: str | int, by: str | int) -> None:
    await _update(uid, state=DENIED, decided=int(time.time()), by=str(by))
    log.info("Заявка на VPN от %s отклонена (%s)", uid, by)


def _client() -> Panel:
    ok, reason = ready()
    if not ok:
        raise PanelError(reason)
    client = panel()
    assert client is not None  # ready() это уже проверил
    return client


async def issue(uid: str | int, by: str | int, *, days: int | None = None
                ) -> Account:
    """Выдаёт доступ. Если запись в панели уже есть — возвращает её же.

    Прежняя запись остаётся прежней: включается и, если срок истёк,
    получает новый. Ключ при этом не меняется — устройства, где он уже
    настроен, продолжают работать.
    """
    client = _client()
    name = account_name(uid)
    period = (days or default_days()) * DAY
    now = int(time.time())

    account = await client.get_user(name)
    if account is None:
        account = await client.create_user(name, now + period, default_traffic())
    else:
        if account.expire and account.expire < now:
            await client.set_expiry(name, now + period)
        if not account.enabled:
            await client.enable(name)
        account = await client.get_user(name) or account

    await _update(uid, state=ACTIVE, name=name, panel=client.kind,
                  issued=now, by=str(by))
    log.info("VPN выдан %s (%s, решение %s)", uid, client.kind, by)
    return account


async def extend(uid: str | int, days: int) -> Account:
    """Сдвигает срок на `days` дней от большего из «сейчас» и прежнего срока."""
    client = _client()
    name = account_name(uid)
    account = await client.get_user(name)
    if account is None:
        raise PanelError("Учётной записи в панели нет — выдайте доступ заново.")
    now = int(time.time())
    if account.expire == 0:
        # Бессрочную запись продлевать некуда: сдвиг превратил бы её
        # в срочную, а это уже урезание, а не продление.
        return account
    await client.set_expiry(name, max(now, account.expire) + days * DAY)
    if not account.enabled:
        await client.enable(name)
    log.info("VPN %s продлён на %s дн.", uid, days)
    return await client.get_user(name) or account


async def set_enabled(uid: str | int, value: bool) -> None:
    client = _client()
    name = account_name(uid)
    if value:
        await client.enable(name)
    else:
        await client.disable(name)
    log.info("VPN %s: %s", uid, "включён" if value else "выключен")


async def status(uid: str | int) -> Account | None:
    return await _client().get_user(account_name(uid))


async def subscription(uid: str | int) -> str:
    return await _client().subscription_url(account_name(uid))


async def check() -> tuple[bool, str]:
    """Проверка панели для кнопки в разделе и для диагностики."""
    try:
        return True, await _client().check()
    except PanelError as exc:
        return False, str(exc)


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
