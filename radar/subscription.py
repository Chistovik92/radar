"""Единая подписка.

Подписок в системе две — на новостные подборки и на загрузку видео без
дневного предела, — но для человека это одна вещь: он заплатил и ждёт,
что работает всё оплаченное. Держать их раздельно означало бы продавать
дважды за одно и то же ощущение.

Поэтому здесь один источник правды: оплата любой части открывает обе,
а срок берётся наибольший из двух. Продление одной не укорачивает другую.

Администрации подписка не нужна: у неё всё открыто всегда — иначе ошибку
в платной части первым обнаружит не разработчик, а тот, кто заплатил.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import roles

log = logging.getLogger("radar.subscription")


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def paid_until(user: dict[str, Any] | None) -> str:
    """Наибольший срок из всех оплаченных частей, ISO-строкой."""
    user = user or {}
    candidates = []

    digest_until = _parse((user.get("digest") or {}).get("paid_until"))
    if digest_until:
        candidates.append(digest_until)

    media_until = _parse((user.get("media_quota") or {}).get("paid_until"))
    if media_until:
        candidates.append(media_until)

    if not candidates:
        return ""
    return max(candidates).isoformat()


def paid(user: dict[str, Any] | None) -> bool:
    """Оплачена ли подписка на сегодня — любая из частей."""
    until = _parse(paid_until(user))
    if until is None:
        return False
    return until.date() >= datetime.now(timezone.utc).date()


def complimentary(user: dict[str, Any] | None, role: str | None = None) -> bool:
    """Служебный доступ администрации — без оплаты и без срока."""
    return roles.is_admin(role or (user or {}).get("role"))


def active(user: dict[str, Any] | None, role: str | None = None) -> bool:
    """Открыты ли платные возможности: по оплате или по служебному доступу."""
    return complimentary(user, role) or paid(user)


def days_left(user: dict[str, Any] | None) -> int:
    """Остаток оплаченных дней. У служебного доступа срока нет — ноль."""
    until = _parse(paid_until(user))
    if until is None:
        return 0
    return max(0, (until.date() - datetime.now(timezone.utc).date()).days)


def describe(user: dict[str, Any] | None, role: str | None = None) -> str:
    """Строка о состоянии подписки — одна на обе части."""
    if complimentary(user, role):
        return "🛠 Служебный доступ — всё открыто без оплаты."
    if paid(user):
        return f"✅ Подписка активна, осталось дней: {days_left(user)}"
    return "Подписка не оформлена."
