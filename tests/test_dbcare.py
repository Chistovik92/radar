#!/usr/bin/env python3
"""Компактность базы — пункт 5 раздела 4.8.

Суть, которую легко упустить: **SQLite не отдаёт место операционной
системе после DELETE.** Строки помечаются свободными и переиспользуются
внутри файла, но сам файл не уменьшается никогда. То есть чистка истории
без `VACUUM` не освобождает ни байта — она лишь замедляет рост.

На одноплатнике это разница между «работает» и «база не пишется», поэтому
здесь проверяется не только арифметика, но и поведение настоящего файла
SQLite: он есть в стандартной библиотеке, и притворяться не нужно.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import dbcare  # noqa: E402

MB = 1024 * 1024


class TestSchedule(unittest.TestCase):
    """Та же логика, что у резервных копий: сравнение по дате."""

    def test_not_before_the_hour(self):
        now = datetime(2026, 8, 25, dbcare.SCHEDULE_HOUR - 1, tzinfo=timezone.utc)
        self.assertFalse(dbcare.due_today("", now))

    def test_after_the_hour(self):
        now = datetime(2026, 8, 25, dbcare.SCHEDULE_HOUR + 1, tzinfo=timezone.utc)
        self.assertTrue(dbcare.due_today("", now))

    def test_not_twice_a_day(self):
        now = datetime(2026, 8, 25, 10, tzinfo=timezone.utc)
        self.assertFalse(dbcare.due_today("2026-08-25", now))

    def test_missed_day_runs_later(self):
        """Сервер был выключен ночью — обслужим при первой возможности."""
        now = datetime(2026, 8, 25, 23, tzinfo=timezone.utc)
        self.assertTrue(dbcare.due_today("2026-08-24", now))

    def test_runs_at_night(self):
        """Переписывание файла нагружает слабый процессор."""
        self.assertLess(dbcare.SCHEDULE_HOUR, 7)


class TestFormatSize(unittest.TestCase):
    def test_units(self):
        self.assertIn("Б", dbcare.format_size(512))
        self.assertIn("КБ", dbcare.format_size(2 * 1024))
        self.assertIn("МБ", dbcare.format_size(5 * MB))
        self.assertIn("ГБ", dbcare.format_size(3 * 1024 * MB))

    def test_zero(self):
        self.assertEqual(dbcare.format_size(0), "0 Б")


class TestCanVacuum(unittest.TestCase):
    """VACUUM строит новый файл рядом со старым — нужно вдвое больше места."""

    def test_needs_double_the_size(self):
        allowed, why = dbcare.can_vacuum(100 * MB, 150 * MB)
        self.assertFalse(allowed)
        self.assertIn("свободного места", why)

    def test_allowed_with_room(self):
        allowed, why = dbcare.can_vacuum(100 * MB, 500 * MB)
        self.assertTrue(allowed)
        self.assertEqual(why, "")

    def test_tiny_database_not_worth_it(self):
        """Выигрыш меньше стоимости блокировки."""
        allowed, why = dbcare.can_vacuum(1024, 100 * MB)
        self.assertFalse(allowed)
        self.assertIn("меньше порога", why)

    def test_exact_double_allowed(self):
        size = 10 * MB
        allowed, _ = dbcare.can_vacuum(size, size * 2)
        self.assertTrue(allowed)


class TestSizeReport(unittest.TestCase):
    def test_quiet_when_small(self):
        text = dbcare.size_report(10 * MB, "SQLite")
        self.assertIn("10.0 МБ", text)
        self.assertNotIn("⚠️", text)

    def test_warns_when_large(self):
        text = dbcare.size_report((dbcare.WARN_SIZE_MB + 50) * MB, "SQLite")
        self.assertIn("⚠️", text)
        self.assertIn("EVENT_RETENTION_DAYS", text)

    def test_backend_named(self):
        self.assertIn("PostgreSQL", dbcare.size_report(MB, "PostgreSQL"))


class TestMeasure(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "radar.db")

    def test_missing_file_is_zero(self):
        self.assertEqual(dbcare.measure_sqlite(self.path), 0)

    def test_counts_wal_and_shm(self):
        """Журнал WAL может весить больше самой базы: считать только
        основной файл — показывать не тот размер, что видно в `du`."""
        for name, size in ((self.path, 100), (f"{self.path}-wal", 400),
                           (f"{self.path}-shm", 32)):
            with open(name, "wb") as handle:
                handle.write(b"x" * size)
        self.assertEqual(dbcare.measure_sqlite(self.path), 532)

    def test_companion_files_listed(self):
        names = dbcare.sqlite_files("/tmp/base.db")
        self.assertIn("/tmp/base.db-wal", names)
        self.assertIn("/tmp/base.db-shm", names)

    def test_free_space_positive(self):
        self.assertGreater(dbcare.free_space(self.path), 0)

    def test_free_space_on_nonsense_path(self):
        self.assertGreater(dbcare.free_space(""), 0)


class TestSqliteReallyDoesNotShrink(unittest.TestCase):
    """Главное утверждение модуля — на настоящем файле SQLite.

    Если оно однажды перестанет быть верным, весь VACUUM станет лишней
    блокировкой, и узнать об этом надо из теста, а не из догадок.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "probe.db")

    def _fill_and_delete(self) -> tuple[int, int]:
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE junk (id INTEGER PRIMARY KEY, body TEXT)")
        connection.executemany(
            "INSERT INTO junk (body) VALUES (?)",
            [("я" * 500,) for _ in range(4000)],
        )
        connection.commit()
        filled = os.path.getsize(self.path)

        connection.execute("DELETE FROM junk")
        connection.commit()
        after_delete = os.path.getsize(self.path)
        connection.close()
        return filled, after_delete

    def test_delete_alone_frees_nothing(self):
        filled, after_delete = self._fill_and_delete()
        self.assertGreater(filled, 0)
        self.assertGreaterEqual(
            after_delete, filled * 0.9,
            "SQLite вдруг стал отдавать место после DELETE — "
            "проверьте, нужен ли ещё VACUUM",
        )

    def test_vacuum_actually_frees(self):
        filled, after_delete = self._fill_and_delete()

        connection = sqlite3.connect(self.path)
        connection.execute("VACUUM")
        connection.close()
        after_vacuum = os.path.getsize(self.path)

        self.assertLess(after_vacuum, after_delete / 2,
                        "VACUUM не освободил место — сжатие бессмысленно")


class TestThresholds(unittest.TestCase):
    def test_warning_threshold_is_sane(self):
        """Полгигабайта на одноплатнике — уже повод посмотреть."""
        self.assertGreaterEqual(dbcare.WARN_SIZE_MB, 100)
        self.assertLessEqual(dbcare.WARN_SIZE_MB, 2000)

    def test_vacuum_floor_below_warning(self):
        self.assertLess(dbcare.MIN_VACUUM_MB, dbcare.WARN_SIZE_MB)


if __name__ == "__main__":
    unittest.main(verbosity=2)
