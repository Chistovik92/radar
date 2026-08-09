"""Учёт квот Gemini: запросы в минуту, запросы в сутки, резерв под ассистента.

Бесплатный тариф Gemini ограничен по RPM и RPD (для 2.5-flash — порядка
10 запросов в минуту), поэтому фоновый анализ новостей обязан уступать
дорогу живому диалогу с ассистентом. Дневной счётчик сбрасывается в полночь
по тихоокеанскому времени — так, как это делает Google.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

log = logging.getLogger("radar.ratelimit")

# Тихоокеанское время: UTC-8 зимой, UTC-7 летом. Для суточной границы
# достаточно приблизительного смещения.
_PACIFIC_OFFSET = timedelta(hours=-8)


def pacific_day() -> str:
    return (datetime.now(timezone.utc) + _PACIFIC_OFFSET).strftime("%Y-%m-%d")


class QuotaExceeded(RuntimeError):
    """Лимит исчерпан; вызывающая сторона решает, ждать или деградировать."""


class RateLimiter:
    """Скользящее окно по минуте плюс суточный счётчик с резервом."""

    def __init__(self, rpm: int, rpd: int, reserve: int = 0, cooldown: int = 900) -> None:
        self.rpm = max(1, rpm)
        self.rpd = max(1, rpd)
        self.reserve = max(0, reserve)      # запросов, доступных только ассистенту
        self.cooldown = cooldown            # пауза фонового анализа после 429, сек
        self._minute: deque[float] = deque()
        self._day = pacific_day()
        self._used = 0
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    # -- внутреннее --------------------------------------------------------

    def _roll(self) -> None:
        now = time.monotonic()
        while self._minute and now - self._minute[0] >= 60:
            self._minute.popleft()
        today = pacific_day()
        if today != self._day:
            self._day = today
            self._used = 0
            self._blocked_until = 0.0
            log.info("Суточная квота Gemini обнулена (новый день %s по PT)", today)

    def _budget(self, priority: bool) -> int:
        return self.rpd if priority else max(0, self.rpd - self.reserve)

    # -- публичное ---------------------------------------------------------

    @property
    def paused(self) -> bool:
        """Фоновый анализ временно остановлен после ответа 429."""
        return time.monotonic() < self._blocked_until

    async def try_acquire(self, priority: bool = False) -> bool:
        """Берёт слот без ожидания. False — вызывающий переходит на эвристику."""
        async with self._lock:
            self._roll()
            if not priority and self.paused:
                return False
            if self._used >= self._budget(priority):
                return False
            if len(self._minute) >= self.rpm:
                return False
            self._minute.append(time.monotonic())
            self._used += 1
            return True

    async def wait_acquire(self, priority: bool = True, timeout: float = 45.0) -> None:
        """Ждёт свободный слот. Бросает QuotaExceeded, если не дождались."""
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                self._roll()
                if self._used >= self._budget(priority):
                    raise QuotaExceeded("суточная квота исчерпана")
                if len(self._minute) < self.rpm:
                    self._minute.append(time.monotonic())
                    self._used += 1
                    return
                oldest = self._minute[0]
            pause = max(0.5, 60 - (time.monotonic() - oldest))
            if time.monotonic() + pause > deadline:
                raise QuotaExceeded("лимит запросов в минуту, попробуйте позже")
            await asyncio.sleep(min(pause, 5.0))

    def note_rejection(self) -> None:
        """Google ответил 429: приостанавливаем фоновый анализ и считаем сутки занятыми."""
        self._blocked_until = time.monotonic() + self.cooldown
        self._used = max(self._used, self._budget(False))
        log.warning(
            "Получен 429: фоновый анализ приостановлен на %d мин, "
            "оставшаяся квота зарезервирована под ассистента",
            self.cooldown // 60,
        )

    def snapshot(self) -> dict[str, int | bool]:
        self._roll()
        return {
            "used_today": self._used,
            "limit_day": self.rpd,
            "in_minute": len(self._minute),
            "limit_minute": self.rpm,
            "paused": self.paused,
        }
