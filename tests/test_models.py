#!/usr/bin/env python3
"""Выбор модели, автопереключение при 404 и различия поколений Gemini."""

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import ai  # noqa: E402

def run(coro):
    return asyncio.run(coro)


class TestGeneration(unittest.TestCase):
    def test_gen3_detected(self):
        for name in ("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                     "gemini-3-flash-preview", "gemini-4.0-flash"):
            self.assertTrue(ai.is_gen3(name), name)

    def test_gen25_detected(self):
        for name in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"):
            self.assertFalse(ai.is_gen3(name), name)

    def test_unknown_name_is_not_gen3(self):
        self.assertFalse(ai.is_gen3(""))
        self.assertFalse(ai.is_gen3("gemini-flash-latest"))


class TestModelChain(unittest.TestCase):
    def setUp(self):
        self.saved_chain = {role: list(chain) for role, chain in ai._chain.items()}
        self.saved_current = dict(ai._current)
        self.saved_unavailable = set(ai._unavailable)
        ai._chain[ai.ASSISTANT] = ["model-a", "model-b", "model-c"]
        ai._current[ai.ASSISTANT] = "model-a"
        ai._unavailable.clear()

    def tearDown(self):
        ai._chain.clear()
        ai._chain.update(self.saved_chain)
        ai._current.clear()
        ai._current.update(self.saved_current)
        ai._unavailable.clear()
        ai._unavailable.update(self.saved_unavailable)

    def test_demote_moves_to_next(self):
        self.assertEqual(ai._demote(ai.ASSISTANT, "model-a"), "model-b")
        self.assertEqual(ai.current_model(ai.ASSISTANT), "model-b")

    def test_demote_skips_known_bad(self):
        ai._demote(ai.ASSISTANT, "model-a")
        ai._demote(ai.ASSISTANT, "model-b")
        self.assertEqual(ai.current_model(ai.ASSISTANT), "model-c")

    def test_demote_returns_none_when_exhausted(self):
        for name in ("model-a", "model-b", "model-c"):
            ai._demote(ai.ASSISTANT, name)
        self.assertIsNone(ai._demote(ai.ASSISTANT, "model-c"))

    def test_report_contains_roles(self):
        report = ai.models_report()
        self.assertIn("assistant", report)
        self.assertIn("analysis", report)
        self.assertIn("available", report)


class TestConfigCompatibility(unittest.TestCase):
    """У Gemini 3.x свои правила: без temperature, thinking_level вместо budget."""

    def setUp(self):
        self.saved = dict(ai._features)

    def tearDown(self):
        ai._features.clear()
        ai._features.update(self.saved)

    def _kwargs(self, model):
        captured = {}
        original = ai.types.GenerateContentConfig

        def spy(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        ai.types.GenerateContentConfig = spy
        try:
            ai._build_config(model, "system", False, 1000, 0.5, False)
        finally:
            ai.types.GenerateContentConfig = original
        return captured

    def test_gen3_has_no_temperature(self):
        self.assertNotIn("temperature", self._kwargs("gemini-3.6-flash"))

    def test_gen25_keeps_temperature(self):
        self.assertEqual(self._kwargs("gemini-2.5-flash")["temperature"], 0.5)

    def test_max_tokens_always_present(self):
        self.assertEqual(self._kwargs("gemini-3.6-flash")["max_output_tokens"], 1000)

    def test_json_mode_sets_mime_type(self):
        captured = {}
        original = ai.types.GenerateContentConfig

        def spy(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        ai.types.GenerateContentConfig = spy
        try:
            ai._build_config("gemini-3.6-flash", None, True, 500, 0.1, True)
        finally:
            ai.types.GenerateContentConfig = original
        self.assertEqual(captured["response_mime_type"], "application/json")
        # поиск несовместим со строгим JSON — инструментов быть не должно
        self.assertNotIn("tools", captured)


class FakeTurn:
    def __init__(self, role):
        self.role = role


class TestTurnValidation(unittest.TestCase):
    """Gemini 3.x отвергает запрос, заканчивающийся ходом роли model."""

    def test_trailing_model_turn_removed(self):
        turns = [FakeTurn("user"), FakeTurn("model"), FakeTurn("user"), FakeTurn("model")]
        result = ai._strip_trailing_model_turn(turns)
        self.assertEqual([t.role for t in result], ["user", "model", "user"])

    def test_user_ending_untouched(self):
        turns = [FakeTurn("user"), FakeTurn("model"), FakeTurn("user")]
        self.assertEqual(len(ai._strip_trailing_model_turn(turns)), 3)

    def test_plain_string_untouched(self):
        self.assertEqual(ai._strip_trailing_model_turn("просто текст"), "просто текст")


if __name__ == "__main__":
    unittest.main(verbosity=2)
