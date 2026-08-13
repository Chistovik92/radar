#!/usr/bin/env python3
"""Тесты учёта квот Gemini."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.ratelimit import QuotaExceeded, RateLimiter, pacific_day  # noqa: E402

def run(coro):
    return asyncio.run(coro)


class TestRateLimiter(unittest.TestCase):
    def test_minute_window(self):
        limiter = RateLimiter(rpm=3, rpd=100)
        self.assertTrue(all(run(limiter.try_acquire()) for _ in range(3)))
        self.assertFalse(run(limiter.try_acquire()))

    def test_daily_budget(self):
        limiter = RateLimiter(rpm=100, rpd=5)
        for _ in range(5):
            self.assertTrue(run(limiter.try_acquire(priority=True)))
        self.assertFalse(run(limiter.try_acquire(priority=True)))

    def test_reserve_protects_assistant(self):
        """Фон исчерпывает бюджет, ассистенту остаётся резерв."""
        limiter = RateLimiter(rpm=100, rpd=10, reserve=4)
        background = 0
        while run(limiter.try_acquire(priority=False)):
            background += 1
        self.assertEqual(background, 6)          # 10 − 4 резерва
        self.assertTrue(run(limiter.try_acquire(priority=True)))

    def test_429_pauses_background_only(self):
        limiter = RateLimiter(rpm=100, rpd=100, reserve=10, cooldown=900)
        limiter.note_rejection()
        self.assertTrue(limiter.paused)
        self.assertFalse(run(limiter.try_acquire(priority=False)))
        self.assertTrue(run(limiter.try_acquire(priority=True)))

    def test_wait_acquire_raises_when_day_exhausted(self):
        limiter = RateLimiter(rpm=100, rpd=1)
        run(limiter.wait_acquire(priority=True))
        with self.assertRaises(QuotaExceeded):
            run(limiter.wait_acquire(priority=True, timeout=0.1))

    def test_wait_acquire_times_out_on_rpm(self):
        limiter = RateLimiter(rpm=1, rpd=100)
        run(limiter.wait_acquire(priority=True))
        with self.assertRaises(QuotaExceeded):
            run(limiter.wait_acquire(priority=True, timeout=0.2))

    def test_snapshot_fields(self):
        limiter = RateLimiter(rpm=10, rpd=250, reserve=40)
        run(limiter.try_acquire(priority=True))
        snapshot = limiter.snapshot()
        self.assertEqual(snapshot["used_today"], 1)
        self.assertEqual(snapshot["limit_day"], 250)
        self.assertEqual(snapshot["limit_minute"], 10)
        self.assertFalse(snapshot["paused"])

    def test_pacific_day_format(self):
        self.assertRegex(pacific_day(), r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
