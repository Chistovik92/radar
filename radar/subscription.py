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
from datetime import datetime, timedelta, timezone
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


# Пробный период. Даётся один раз и сам: требовать нажатия «начать пробный
# период» значит терять тех, кто до этой кнопки не дошёл, — а весь смысл
# пробы в том, чтобы человек увидел платную часть в деле.
TRIAL_DAYS = 7

# Хранилище общей подписки. Раньше срок жил в двух местах — у подборок
# и у видео, — и подарить дни было некуда: любой выбор выглядел бы
# как оплата не того. Здесь третий, свой источник, а paid_until
# по-прежнему берёт наибольшее из всех.
SLOT = "sub"


def _slot(user: dict[str, Any] | None) -> dict[str, Any]:
    data = (user or {}).get(SLOT)
    return data if isinstance(data, dict) else {}


def trial_started(user: dict[str, Any] | None) -> str:
    return str(_slot(user).get("trial_started") or "")


def trial_used(user: dict[str, Any] | None) -> bool:
    """Был ли пробный период. Второй раз он не даётся."""
    return bool(trial_started(user))


def start_trial(user: dict[str, Any]) -> bool:
    """Включает пробный период. False — он уже был.

    Дни кладутся в общий срок: пробный период отличается от оплаченного
    только тем, как он появился, и разделять их пришлось бы во всех
    проверках сразу.
    """
    if trial_used(user):
        return False
    now = datetime.now(timezone.utc)
    slot = dict(_slot(user))
    slot["trial_started"] = now.isoformat()
    slot["until"] = (now + timedelta(days=TRIAL_DAYS)).isoformat()
    user[SLOT] = slot
    log.info("Пробный период на %d дней начат", TRIAL_DAYS)
    return True


def grant(user: dict[str, Any], days: int) -> str:
    """Добавляет дни к общему сроку. Возвращает новую дату окончания.

    Продлевает от конца текущего срока, а не от сегодня: иначе подарок
    поверх оплаченного укоротил бы оплаченное.
    """
    now = datetime.now(timezone.utc)
    current = _parse(paid_until(user))
    base = current if current and current > now else now
    until = (base + timedelta(days=max(0, int(days)))).isoformat()
    slot = dict(_slot(user))
    slot["until"] = until
    user[SLOT] = slot
    return until


def on_trial(user: dict[str, Any] | None) -> bool:
    """Идёт ли пробный период прямо сейчас."""
    if not trial_used(user) or not paid(user):
        return False
    started = _parse(trial_started(user))
    if started is None:
        return False
    return (datetime.now(timezone.utc) - started).days < TRIAL_DAYS


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

    own_until = _parse(_slot(user).get("until"))
    if own_until:
        candidates.append(own_until)

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
    if on_trial(user):
        return f"🎁 Пробный период, осталось дней: {days_left(user)}"
    if paid(user):
        return f"✅ Подписка активна, осталось дней: {days_left(user)}"
    if trial_used(user):
        return "Подписка не оформлена, пробный период уже был."
    return f"Подписка не оформлена. Есть пробный период — {TRIAL_DAYS} дней."
