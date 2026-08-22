"""Квоты загрузки видео.

Загрузка открыта всем, но не безгранично: двадцать роликов в сутки
бесплатно, дальше — подписка за десять звёзд на месяц.

Почему считаем именно штуки, а не мегабайты: человеку понятно «осталось
17 из 20», а «осталось 380 МБ» требует прикидывать размер каждого ролика
заранее. К тому же дорог здесь не трафик, а процессорное время слабого
одноплатника на перекодирование.

**Предел размера в 50 МБ подпиской не снимается.** Это ограничение
Telegram Bot API, а не наше решение: бот физически не может отправить
файл крупнее через api.telegram.org. Обещать за деньги то, чего не можешь
дать, нельзя — поэтому в описании подписки об этом сказано прямо.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

log = logging.getLogger("radar.mediaquota")

FREE_PER_DAY = 20
STARS_PRICE = 10
SUBSCRIPTION_DAYS = 30


@dataclass
class Quota:
    """Состояние квоты одного человека."""

    used: int = 0
    day: str = ""
    paid_until: str = ""

    # Служебный доступ администрации. В базе не хранится — вычисляется
    # по роли при каждом обращении, иначе понижение роли оставило бы
    # человеку безлимит навсегда.
    complimentary: bool = field(default=False, compare=False)

    @property
    def unlimited(self) -> bool:
        if self.complimentary:
            return True
        if not self.paid_until:
            return False
        try:
            until = datetime.fromisoformat(self.paid_until)
        except ValueError:
            return False
        return until.date() >= datetime.now(timezone.utc).date()

    @property
    def days_left(self) -> int:
        if self.complimentary or not self.paid_until:
            return 0
        if not self.unlimited:
            return 0
        until = datetime.fromisoformat(self.paid_until)
        return max(0, (until.date() - datetime.now(timezone.utc).date()).days)

    def left(self, today: str) -> int:
        """Сколько загрузок осталось сегодня."""
        if self.unlimited:
            return FREE_PER_DAY  # число не показывается, важен сам факт
        if self.day != today:
            return FREE_PER_DAY
        return max(0, FREE_PER_DAY - self.used)

    def allowed(self, today: str) -> bool:
        return self.unlimited or self.left(today) > 0

    def spend(self, today: str) -> None:
        """Отметить загрузку. У подписки счётчик тоже идёт — для статистики."""
        if self.day != today:
            self.day = today
            self.used = 0
        self.used += 1

    def extend(self, days: int = SUBSCRIPTION_DAYS) -> None:
        """Продлить подписку, сохранив остаток прежней."""
        base = datetime.now(timezone.utc)
        if self.unlimited:
            base = datetime.fromisoformat(self.paid_until)
        self.paid_until = (base + timedelta(days=days)).isoformat()

    def to_dict(self) -> dict[str, object]:
        return {"used": self.used, "day": self.day, "paid_until": self.paid_until}

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Quota":
        raw = raw or {}
        try:
            used = int(raw.get("used") or 0)
        except (TypeError, ValueError):
            used = 0
        return cls(
            used=max(0, used),
            day=str(raw.get("day") or ""),
            paid_until=str(raw.get("paid_until") or ""),
        )


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def quota_of(user: dict, role: str | None = None) -> Quota:
    """Квота человека с учётом единой подписки и роли.

    Оплата подборок снимает дневной предел на видео — подписка одна.
    Администрации предел не ставится вовсе: иначе ошибку в платной части
    первым найдёт не разработчик, а тот, кто заплатил.
    """
    quota = Quota.from_dict((user or {}).get("media_quota"))

    from . import subscription as common

    if common.complimentary(user, role):
        quota.complimentary = True
        return quota

    shared = common.paid_until(user)
    if shared and shared > (quota.paid_until or ""):
        quota.paid_until = shared
    return quota


def store_quota(user: dict, quota: Quota) -> None:
    user["media_quota"] = quota.to_dict()


def describe(quota: Quota, lang: str = "ru") -> str:
    """Текст о состоянии квоты."""
    from . import i18n

    if quota.unlimited:
        return i18n.t(
            "media.quota.unlimited", lang,
            f"Безлимит активен, осталось дней: {quota.days_left}",
        )
    left = quota.left(today())
    if left <= 0:
        return i18n.t(
            "media.quota.spent", lang,
            f"Дневной предел исчерпан ({FREE_PER_DAY} видео). "
            "Лимит обновится завтра.",
        )
    return i18n.t(
        "media.quota.left", lang,
        f"Осталось сегодня: {left} из {FREE_PER_DAY}",
    )
