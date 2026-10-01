"""Добавление, правка и удаление VPN-панелей (слотов) из веб-панели (5.9.2.1).

До 5.9.2.1 панель можно было завести только правкой десяти отдельных
ключей `VPN<n>_*` в разделе «Ключи» — без проверки вида и адреса и без
подсказки, какие поля нужны именно этой панели. Здесь — осмысленная форма
на слот: вид выбирается из списка, поля проверяются, секреты не стираются
пустым полем, удаление предупреждает о выданных доступах.

Значения хранятся там же, где и раньше (`VPN<n>_KIND`, `VPN<n>_URL` …,
файл `.env`), поэтому бот, CLI и прежние установки ничего не замечают.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from . import secrets, vpn, vpnpanels

log = logging.getLogger("radar.vpnslots")

FIELDS = vpn.FIELDS            # KIND TITLE URL TOKEN USER PASS INBOUND SUB_URL GROUPS CERT
SECRET_FIELDS = ("TOKEN", "PASS")


@dataclass(frozen=True)
class KindInfo:
    kind: str
    title: str
    needs: str        # что нужно этой панели — одной фразой для формы


# Что нужно каждому виду. Сверено с тем, как клиенты в vpnpanels.py входят
# в панель; подсказка не заменяет проверку, а только экономит попытки.
_NEEDS = {
    "3xui": "токен (Bearer) или логин и пароль; номер подключения (inbound); адрес службы подписки",
    "xui": "логин и пароль; номер подключения (inbound); адрес службы подписки",
    "sui": "токен из «Настройки → API»; адрес службы подписки",
    "marzban": "логин и пароль администратора",
    "pasarguard": "ключ API (токен) или логин и пароль; группы — по желанию",
    "marzneshin": "логин и пароль администратора; сервисы — по желанию",
    "remnawave": "токен из раздела API Tokens; отряды (squads) — по желанию",
    "hiddify": "uuid администратора в поле токена; клиентский путь в адресе подписки",
    "outline": "адрес — это apiUrl целиком; отпечаток сертификата обязателен",
    "wgeasy": "пароль; ссылка — файл настроек WireGuard",
}

_TITLES = {
    "3xui": "3x-ui (2.x и 3.x)", "xui": "x-ui (alireza0)", "sui": "s-ui",
    "marzban": "Marzban", "pasarguard": "PasarGuard", "marzneshin": "Marzneshin",
    "remnawave": "Remnawave", "hiddify": "Hiddify", "outline": "Outline", "wgeasy": "wg-easy",
}


def kinds() -> list[KindInfo]:
    return [KindInfo(kind, _TITLES.get(kind, kind), _NEEDS.get(kind, ""))
            for kind in vpnpanels.KINDS]


def numbers() -> range:
    return range(1, vpn.SLOTS + 1)


def read(number: int) -> dict[str, str]:
    """Значения слота. Секреты возвращаются как есть — для проверки «задан ли»."""
    return {field: vpn.slot_value(number, field) for field in FIELDS}


def configured(number: int) -> bool:
    return bool(vpn.slot_value(number, "KIND"))


def free_number() -> int | None:
    for number in numbers():
        if not configured(number):
            return number
    return None


def _valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate(values: dict[str, str]) -> str:
    """Причина отказа по-человечески. Пусто — можно сохранять."""
    kind = vpnpanels.normalize_kind(values.get("KIND", ""))
    if not kind:
        return "Не выбран вид панели."
    if kind not in vpnpanels.KINDS:
        if kind in vpnpanels.UNSUPPORTED:
            return vpnpanels.UNSUPPORTED[kind]
        return f"Незнакомый вид панели: «{kind}»."
    url = values.get("URL", "").strip()
    if not url:
        return "Не указан адрес панели."
    if not _valid_url(url):
        return "Адрес панели должен начинаться с http:// или https://."
    inbound = values.get("INBOUND", "").strip()
    if inbound and not inbound.isdigit():
        return "Номер подключения (inbound) — число."
    sub_url = values.get("SUB_URL", "").strip()
    if sub_url and not _valid_url(sub_url):
        return "Адрес подписки должен начинаться с http:// или https://."
    cert = values.get("CERT", "").strip().replace(":", "").lower()
    if cert and (len(cert) != 64 or any(ch not in "0123456789abcdef" for ch in cert)):
        return "Отпечаток сертификата — 64 шестнадцатеричных знака (SHA-256)."
    if kind == "outline" and not cert:
        return "Для Outline отпечаток сертификата обязателен."
    has_token = bool(values.get("TOKEN", "").strip())
    has_login = bool(values.get("USER", "").strip() and values.get("PASS", "").strip())
    if kind == "wgeasy":
        if not values.get("PASS", "").strip():
            return "Для wg-easy нужен пароль."
    elif kind != "outline" and not (has_token or has_login):
        return "Нужен токен либо логин с паролем."
    return ""


def save(number: int, form: dict[str, str]) -> str:
    """Записывает слот. Возвращает причину отказа или пустую строку.

    Пустой токен или пароль при правке уже настроенного слота означает
    «не менять»: панель не показывает секреты, и иначе любое сохранение
    стирало бы их. Остальные пустые поля очищаются.
    """
    if number not in numbers():
        return "Нет такого слота."
    merged: dict[str, str] = {}
    for field in FIELDS:
        value = (form.get(field) or "").strip()
        if field in SECRET_FIELDS and not value:
            value = vpn.slot_value(number, field)
        merged[field] = value
    merged["KIND"] = vpnpanels.normalize_kind(merged["KIND"])
    merged["CERT"] = merged["CERT"].replace(":", "").lower()
    # Адрес из браузера приходит с /dashboard/: храним корень API (5.9.2.3).
    cls = vpnpanels.KINDS.get(merged["KIND"])
    if cls is not None and cls.url_stop:
        merged["URL"] = vpnpanels.api_root(merged["URL"], cls.url_stop)

    problem = validate(merged)
    if problem:
        return problem

    if not secrets.write_many({vpn.env_name(number, field): merged[field] for field in FIELDS}):
        return "Записать не удалось — проверьте права на .env."
    log.info("VPN: слот %d сохранён (%s)", number, merged["KIND"])
    return ""


async def issued_on(number: int) -> int:
    """Сколько людей получили доступ именно на этом слоте."""
    records = await vpn.records()
    return sum(1 for entry in records.values() if str(number) in (entry.get("panels") or {}))


def remove(number: int) -> bool:
    """Освобождает слот. Выданные на нём доступы в панели не трогаются."""
    if number not in numbers():
        return False
    cleared = {vpn.env_name(number, field): "" for field in FIELDS}
    if number == 1:
        # Слот 1 читает и прежние имена (VPN_PANEL, …) — их тоже нужно снять,
        # иначе удалённая панель «воскреснет» из старых настроек.
        cleared.update({legacy: "" for legacy in vpn.LEGACY.values()})
    ok = secrets.write_many(cleared)
    log.info("VPN: слот %d освобождён", number)
    return ok


async def check(number: int) -> tuple[bool, str]:
    """Живая проверка одного слота: вход в панель и чтение."""
    target = vpn.slot(number)
    if target is None:
        return False, "Слот не настроен или вид панели незнаком."
    results = await vpn.check_all()
    return results.get(str(number), (False, "нет ответа"))


__all__ = ["KindInfo", "FIELDS", "SECRET_FIELDS", "kinds", "numbers", "read", "configured",
           "free_number", "validate", "save", "issued_on", "remove", "check"]
