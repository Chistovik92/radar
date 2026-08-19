#!/usr/bin/env python3
"""Замер стадий цикла: накопление показаний и устойчивость к сбоям."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import profiling  # noqa: E402


class TestMeasure(unittest.TestCase):
    def setUp(self):
        profiling.reset()

    def test_records_call(self):
        with profiling.measure("sources"):
            pass
        stage = profiling.snapshot()["sources"]
        self.assertEqual(stage.calls, 1)
        self.assertGreaterEqual(stage.total, 0.0)

    def test_accumulates(self):
        for _ in range(3):
            with profiling.measure("ai"):
                pass
        self.assertEqual(profiling.snapshot()["ai"].calls, 3)

    def test_failure_still_measured(self):
        """Обращение, висевшее до таймаута, — тоже потерянное время."""
        with self.assertRaises(RuntimeError):
            with profiling.measure("ai"):
                raise RuntimeError("сервис недоступен")
        self.assertEqual(profiling.snapshot()["ai"].calls, 1)

    def test_history_bounded(self):
        """Память не растёт: замер не должен становиться дороже измеряемого."""
        for _ in range(profiling.HISTORY + 15):
            with profiling.measure("dispatch"):
                pass
        stage = profiling.snapshot()["dispatch"]
        self.assertEqual(len(stage.recent), profiling.HISTORY)
        self.assertEqual(stage.calls, profiling.HISTORY + 15)

    def test_average_and_worst(self):
        stage = profiling.Stage()
        stage.add(1.0)
        stage.add(3.0)
        self.assertAlmostEqual(stage.average, 2.0)
        self.assertAlmostEqual(stage.worst, 3.0)
        self.assertAlmostEqual(stage.last, 3.0)

    def test_empty_stage_no_division_error(self):
        self.assertEqual(profiling.Stage().average, 0.0)
        self.assertEqual(profiling.Stage().last, 0.0)

    def test_reset_clears(self):
        with profiling.measure("save"):
            pass
        profiling.reset()
        self.assertEqual(profiling.snapshot(), {})

    def test_snapshot_ordered_by_cycle(self):
        """Порядок стадий — как в цикле, иначе отчёт трудно читать."""
        for name in ("dispatch", "sources", "ai"):
            with profiling.measure(name):
                pass
        self.assertEqual(list(profiling.snapshot()), ["sources", "ai", "dispatch"])

    def test_unknown_stage_goes_last(self):
        with profiling.measure("самодельная"):
            pass
        with profiling.measure("sources"):
            pass
        self.assertEqual(list(profiling.snapshot())[-1], "самодельная")


class TestResources(unittest.TestCase):
    def test_memory_non_negative(self):
        self.assertGreaterEqual(profiling.memory_mb(), 0.0)

    def test_cpu_non_negative(self):
        self.assertGreaterEqual(profiling.cpu_seconds(), 0.0)

    def test_load_average_triple(self):
        self.assertEqual(len(profiling.load_average()), 3)

    def test_cpu_count_at_least_one(self):
        self.assertGreaterEqual(profiling.cpu_count(), 1)

    def test_uptime_grows(self):
        profiling.reset()
        self.assertGreaterEqual(profiling.uptime(), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
