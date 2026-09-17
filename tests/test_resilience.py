#!/usr/bin/env python3
"""Устойчивость: что бот делает, когда что-то ломается.

Каждый случай здесь — из проверки кода перед 4.9.8.14, и каждый до неё
заканчивался молчанием: потерянной тревогой, умершим циклом или очередью,
исчезнувшей при перезапуске. Молчание — худший исход для системы
оповещения, поэтому проверяется именно оно.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from datetime import datetime
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import health, monitor, quiet, tg  # noqa: E402

# Классы исключений берём из самого модуля отправки, а не из aiogram:
# в общем прогоне заглушки ставит первый импортировавший их файл, и класс
# с тем же именем из второй заглушки был бы ДРУГИМ объектом — `except`
# его не ловит. Ровно так восемнадцать тестов когда-то были зелёными
# по отдельности и красными вместе.
TelegramNetworkError = tg.TelegramNetworkError
TelegramRetryAfter = tg.TelegramRetryAfter
from radar.web import auth  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class SendRetryTests(unittest.TestCase):
    """Отправка: сетевой сбой не должен означать потерянную тревогу."""

    def setUp(self) -> None:
        self.calls = 0

    def _send(self, behaviour):
        async def fake(chat_id, text, **kwargs):
            self.calls += 1
            outcome = behaviour(self.calls)
            if outcome is not None:
                raise outcome

        return fake

    def test_network_blip_retried(self):
        """Один обрыв связи — повтор, а не отказ."""
        def behaviour(call):
            return TelegramNetworkError() if call == 1 else None

        patched_send = mock.patch.object(tg.bot, "send_message", self._send(behaviour))
        patched_sleep = mock.patch.object(tg.asyncio, "sleep", new=fake_sleep)
        with patched_send, patched_sleep:
            self.assertTrue(run(tg.send_html(1, "Прорыв трубы")))
        self.assertEqual(self.calls, 2)

    def test_persistent_failure_reported(self):
        """Не ушло за все попытки — False, а не «доставлено»."""
        retry = TelegramRetryAfter()
        retry.retry_after = 1

        patched_send = mock.patch.object(tg.bot, "send_message", self._send(lambda _: retry))
        patched_sleep = mock.patch.object(tg.asyncio, "sleep", new=fake_sleep)
        with patched_send, patched_sleep:
            self.assertFalse(run(tg.send_html(1, "Прорыв трубы")))
        self.assertEqual(self.calls, tg.SEND_ATTEMPTS)


async def fake_sleep(_seconds):
    """Паузы в тестах не нужны: проверяется поведение, а не терпение."""
    return None


class HeldQueueTests(unittest.TestCase):
    """Придержанное тихими часами: чьё-то не должно вытеснять чужое."""

    def setUp(self) -> None:
        quiet.restore([])
        self.user = {"quiet_from": "23:00", "quiet_to": "08:00"}

    def test_own_limit_does_not_evict_others(self):
        for index in range(quiet.PER_USER + 10):
            quiet.hold("1", f"шумный {index}")
        quiet.hold("2", "тихий")

        self.assertEqual(
            [item.text for item in quiet._held if item.user_key == "2"],
            ["тихий"],
        )
        mine = [item for item in quiet._held if item.user_key == "1"]
        self.assertEqual(len(mine), quiet.PER_USER)

    def test_survives_restart(self):
        quiet.hold("7", "Отключение воды")
        snapshot = quiet.snapshot()

        quiet.restore([])
        self.assertEqual(quiet.held_count(), 0)

        self.assertEqual(quiet.restore(snapshot), 1)
        released = quiet.release("7", self.user, datetime(2026, 8, 15, 12, 0))
        self.assertEqual(released, ["Отключение воды"])

    def test_stale_entries_dropped(self):
        old = time.time() - (quiet.HOLD_TTL_HOURS + 1) * 3600
        rows = [{"user": "7", "text": "позавчерашнее", "created": old}]
        self.assertEqual(quiet.restore(rows), 0)

    def test_broken_snapshot_ignored(self):
        """Битый снимок не должен мешать боту подняться."""
        self.assertEqual(quiet.restore("не список"), 0)
        self.assertEqual(quiet.restore([{"text": "без адресата"}, 42]), 0)

    def test_undeliverable_dropped_after_attempts(self):
        self.assertTrue(quiet.hold("9", "текст", attempts=quiet.MAX_ATTEMPTS - 1))
        self.assertFalse(quiet.hold("9", "текст", attempts=quiet.MAX_ATTEMPTS))
        self.assertEqual(quiet.held_count(), 1)


class HeartbeatTests(unittest.TestCase):
    """Признак жизни цикла: по нему сторож понимает, что тревог не будет."""

    def test_silence_detected(self):
        monitor._stats["heartbeat"] = int(time.time()) - monitor.silence_limit() - 60
        healthy, silent = monitor.alive()
        self.assertFalse(healthy)
        self.assertGreater(silent, monitor.silence_limit())

    def test_fresh_beat_is_healthy(self):
        monitor._stats["heartbeat"] = int(time.time())
        healthy, _ = monitor.alive()
        self.assertTrue(healthy)

    def test_before_first_cycle_is_healthy(self):
        """Бот только поднялся — это не повод поднимать тревогу."""
        monitor._stats["heartbeat"] = 0
        self.assertEqual(monitor.alive(), (True, 0))


class HealthCheckTests(unittest.TestCase):
    """Проверка снаружи процесса: она читает файл, а не память."""

    def test_missing_file_is_healthy(self):
        with mock.patch.object(health.Path, "read_text",
                               side_effect=OSError("нет файла")):
            healthy, _ = health.check()
        self.assertTrue(healthy)

    def test_stale_file_is_unhealthy(self):
        stale = str(int(time.time()) - health.limit() - 60)
        with mock.patch.object(health.Path, "read_text", return_value=stale):
            healthy, reason = health.check()
        self.assertFalse(healthy)
        self.assertIn("молчит", reason)

    def test_fresh_file_is_healthy(self):
        with mock.patch.object(health.Path, "read_text",
                               return_value=str(int(time.time()))):
            healthy, _ = health.check()
        self.assertTrue(healthy)


class AttemptsMemoryTests(unittest.TestCase):
    """Попытки входа в панель не должны копиться вечно."""

    def setUp(self) -> None:
        auth._attempts.clear()

    def test_stale_addresses_forgotten(self):
        auth._attempts["1.2.3.4"] = [time.time() - auth.ATTEMPT_WINDOW - 10]
        auth._attempts["5.6.7.8"] = [time.time()]

        auth.forget_stale_attempts()

        self.assertNotIn("1.2.3.4", auth._attempts)
        self.assertIn("5.6.7.8", auth._attempts)


if __name__ == "__main__":
    unittest.main()
