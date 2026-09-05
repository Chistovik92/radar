#!/usr/bin/env python3
"""Проверка источников по расписанию: логика «пора/не пора».

Та же схема, что у копий и обслуживания базы: сравнение по дате,
чтобы выключенный ночью сервер не терял сутки. Проверять сетевую
часть здесь незачем — она общая с кнопкой модератора и проверена
своими тестами.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import sourcecheck  # noqa: E402


class TestSchedule(unittest.TestCase):
    """Логика та же, что у копий и dbcare: сравнение по дате."""

    def test_not_before_the_hour(self):
        now = datetime(2026, 9, 6, sourcecheck.SCHEDULE_HOUR - 1,
                       tzinfo=timezone.utc)
        self.assertFalse(sourcecheck.due_today("", now))

    def test_after_the_hour(self):
        now = datetime(2026, 9, 6, sourcecheck.SCHEDULE_HOUR + 1,
                       tzinfo=timezone.utc)
        self.assertTrue(sourcecheck.due_today("", now))

    def test_not_twice_a_day(self):
        now = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)
        self.assertFalse(sourcecheck.due_today("2026-09-06", now))

    def test_missed_day_runs_later(self):
        """Сервер был выключен ночью — проверим при первой возможности."""
        now = datetime(2026, 9, 6, 23, tzinfo=timezone.utc)
        self.assertTrue(sourcecheck.due_today("2026-09-05", now))

    def test_runs_at_night(self):
        """Паузы между запросами никому не мешают ночью."""
        self.assertLess(sourcecheck.SCHEDULE_HOUR, 7)

    def test_hour_matches_dbcare(self):
        """Ночные дела идут одним часом: база, копии, источники."""
        from radar import dbcare

        self.assertEqual(sourcecheck.SCHEDULE_HOUR, dbcare.SCHEDULE_HOUR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
