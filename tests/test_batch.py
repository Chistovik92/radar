#!/usr/bin/env python3
"""Пакетный разбор новостей: предфильтр, кэш, нарезка на пачки, сопоставление индексов."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import ai, config  # noqa: E402
from radar.ratelimit import QuotaExceeded  # noqa: E402

UTILITY = "Отключение холодной воды по ул. Чапаева, д. 12 до 18:00."
MILITARY = "Внимание! Объявлена опасность атаки БПЛА."
NOISE = "Розыгрыш сертификата среди подписчиков канала!"


def run(coro):
    return asyncio.run(coro)


class FakeModel:
    """Подменяет ai.generate: считает вызовы и отдаёт правдоподобный JSON."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, prompt, **kwargs):
        self.calls.append(prompt)
        count = prompt.count("] источник «")
        payload = [
            {
                "index": position + 1,
                "relevant": True,
                "categories": ["jkh"],
                "severity": "warning",
                "scope": "street",
                "city": "Саратов",
                "districts": [],
                "streets": [{"street": "улица Чапаева", "houses": ["12"]}],
                "summary": f"Событие {position + 1}",
            }
            for position in range(count)
        ]
        return json.dumps(payload, ensure_ascii=False)


class TestAnalyzeBatch(unittest.TestCase):
    def setUp(self):
        ai._cache.clear()
        for key in ai._counters:
            ai._counters[key] = 0
        ai.limiter.__init__(rpm=1000, rpd=10000, reserve=0)
        self.original_generate = ai.generate
        self.original_enabled = ai.ENABLED
        self.fake = FakeModel()
        ai.generate = self.fake
        ai.ENABLED = True

    def tearDown(self):
        ai.generate = self.original_generate
        ai.ENABLED = self.original_enabled

    def test_noise_never_reaches_model(self):
        # тексты различаются, иначе повторы уйдут в кэш, а не в фильтр
        results = run(ai.analyze_batch([(f"{NOISE} №{i}", "chan") for i in range(5)]))
        self.assertEqual(self.fake.calls, [])
        self.assertTrue(all(not item.relevant for item in results))
        self.assertEqual(ai.counters()["prefiltered"], 5)

    def test_relevant_goes_to_model_in_one_request(self):
        items = [(f"{UTILITY} Вариант {i}", "vodokanal") for i in range(5)]
        results = run(ai.analyze_batch(items))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(item.relevant for item in results))
        self.assertEqual(ai.counters()["ai"], 5)

    def test_batch_is_chunked(self):
        original = config.AI_BATCH_SIZE
        config.AI_BATCH_SIZE = 3
        try:
            items = [(f"{UTILITY} №{i}", "vodokanal") for i in range(7)]
            run(ai.analyze_batch(items))
            self.assertEqual(len(self.fake.calls), 3)  # 3 + 3 + 1
        finally:
            config.AI_BATCH_SIZE = original

    def test_cache_prevents_second_request(self):
        items = [(UTILITY, "vodokanal")]
        run(ai.analyze_batch(items))
        run(ai.analyze_batch(items))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(ai.counters()["cached"], 1)

    def test_mixed_input_keeps_order(self):
        items = [(NOISE, "a"), (UTILITY, "b"), (NOISE, "c"), (MILITARY, "d")]
        results = run(ai.analyze_batch(items))
        self.assertEqual([item.relevant for item in results], [False, True, False, True])
        self.assertEqual(len(self.fake.calls), 1)

    def test_quota_exhausted_falls_back_to_heuristics(self):
        async def exhausted(prompt, **kwargs):
            raise QuotaExceeded("нет свободной квоты для фонового анализа")

        ai.generate = exhausted
        results = run(ai.analyze_batch([(UTILITY, "vodokanal")]))
        self.assertTrue(results[0].relevant)
        self.assertEqual(results[0].engine, "heuristic")
        self.assertEqual(ai.counters()["heuristic"], 1)

    def test_model_error_falls_back_to_heuristics(self):
        async def broken(prompt, **kwargs):
            raise ai.AIError("сервис недоступен")

        ai.generate = broken
        results = run(ai.analyze_batch([(UTILITY, "vodokanal")]))
        self.assertTrue(results[0].relevant)
        self.assertEqual(results[0].engine, "heuristic")

    def test_short_answer_from_model_is_padded(self):
        async def stingy(prompt, **kwargs):
            return json.dumps([{"index": 1, "relevant": True, "categories": ["jkh"],
                                "summary": "только первый"}])

        ai.generate = stingy
        items = [(f"{UTILITY} №{i}", "vodokanal") for i in range(3)]
        results = run(ai.analyze_batch(items))
        self.assertEqual(len(results), 3)
        self.assertTrue(all(item is not None for item in results))


if __name__ == "__main__":
    unittest.main(verbosity=2)
