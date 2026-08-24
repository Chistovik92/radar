#!/usr/bin/env python3
"""Ответ тем, кто писал боту во время технических работ.

При обновлении контейнер стоит несколько минут, а на старте выполняется
`delete_webhook(drop_pending_updates=True)` — накопившиеся сообщения
стираются без следа. Человек написал и не получил ответа никогда.

Главное, что закрепляют тесты: сами обновления **не обрабатываются**.
Из них берутся только адресаты. Повторить нажатие SOS десятиминутной
давности или заново разобрать присланную геопозицию нельзя — это
выглядело бы как событие, происходящее сейчас.
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
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import restartnotice  # noqa: E402


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeSource:
    def __init__(self, uid):
        self.from_user = FakeUser(uid)


class FakeUpdate:
    """Обновление Telegram: сообщение, нажатие кнопки или что-то ещё."""

    def __init__(self, *, message=None, callback=None):
        self.message = message
        self.callback_query = callback


def message_from(uid):
    return FakeUpdate(message=FakeSource(uid))


def callback_from(uid):
    return FakeUpdate(callback=FakeSource(uid))


class FakeBot:
    def __init__(self, updates=None, boom=False):
        self._updates = updates or []
        self._boom = boom
        self.calls = 0

    async def get_updates(self, **_kwargs):
        self.calls += 1
        if self._boom:
            raise RuntimeError("сеть недоступна")
        return self._updates


def run(coro):
    return asyncio.run(coro)


class Recorder:
    def __init__(self, failing=()):
        self.sent = []
        self.failing = set(failing)

    async def send(self, uid, text):
        if uid in self.failing:
            raise RuntimeError("бот заблокирован")
        self.sent.append((uid, text))


def notify(bot, users, recorder):
    return run(restartnotice.notify(
        bot, users, recorder.send,
        lambda user: (user or {}).get("lang", "ru"),
        lambda lang: f"текст[{lang}]",
    ))


class TestChatIds(unittest.TestCase):
    def test_messages_and_callbacks_both_counted(self):
        updates = [message_from(1), callback_from(2)]
        self.assertEqual(restartnotice.chat_ids(updates), ["1", "2"])

    def test_duplicates_removed_order_kept(self):
        updates = [message_from(7), message_from(3), callback_from(7)]
        self.assertEqual(restartnotice.chat_ids(updates), ["7", "3"])

    def test_updates_without_sender_ignored(self):
        updates = [FakeUpdate(), message_from(5)]
        self.assertEqual(restartnotice.chat_ids(updates), ["5"])

    def test_empty_and_none(self):
        self.assertEqual(restartnotice.chat_ids([]), [])
        self.assertEqual(restartnotice.chat_ids(None), [])


class TestNotify(unittest.TestCase):
    def setUp(self):
        restartnotice.PAUSE = 0        # в тестах ждать незачем
        self.users = {"1": {"lang": "ru"}, "2": {"lang": "en"}}

    def test_writes_to_everyone_who_wrote(self):
        recorder = Recorder()
        count = notify(FakeBot([message_from(1), message_from(2)]),
                       self.users, recorder)
        self.assertEqual(count, 2)
        self.assertEqual([uid for uid, _ in recorder.sent], ["1", "2"])

    def test_language_respected(self):
        recorder = Recorder()
        notify(FakeBot([message_from(1), message_from(2)]), self.users, recorder)
        self.assertEqual(dict(recorder.sent)["1"], "текст[ru]")
        self.assertEqual(dict(recorder.sent)["2"], "текст[en]")

    def test_strangers_are_not_written_to(self):
        """Посторонний и так получил бы «доступ закрыт» — писать ему нечего."""
        recorder = Recorder()
        count = notify(FakeBot([message_from(999)]), self.users, recorder)
        self.assertEqual(count, 0)
        self.assertEqual(recorder.sent, [])

    def test_nobody_wrote(self):
        recorder = Recorder()
        self.assertEqual(notify(FakeBot([]), self.users, recorder), 0)

    def test_blocked_user_does_not_stop_the_rest(self):
        recorder = Recorder(failing={"1"})
        count = notify(FakeBot([message_from(1), message_from(2)]),
                       self.users, recorder)
        self.assertEqual(count, 1)
        self.assertEqual([uid for uid, _ in recorder.sent], ["2"])

    def test_unreadable_queue_is_not_fatal(self):
        """Не смогли прочитать очередь — бот всё равно обязан подняться."""
        recorder = Recorder()
        self.assertEqual(notify(FakeBot(boom=True), self.users, recorder), 0)

    def test_flood_is_capped(self):
        many = {str(i): {"lang": "ru"} for i in range(restartnotice.MAX_NOTIFIED + 20)}
        updates = [message_from(i) for i in range(restartnotice.MAX_NOTIFIED + 20)]
        recorder = Recorder()
        count = notify(FakeBot(updates), many, recorder)
        self.assertEqual(count, restartnotice.MAX_NOTIFIED)

    def test_queue_read_exactly_once(self):
        """Повторное чтение подтвердило бы обновления и сломало сброс."""
        bot = FakeBot([message_from(1)])
        notify(bot, self.users, Recorder())
        self.assertEqual(bot.calls, 1)


class TestUpdatesAreNotProcessed(unittest.TestCase):
    """Самое важное: старые события не должны проигрываться заново."""

    def test_module_does_not_touch_handlers(self):
        source = (
            os.path.join(ROOT, "radar", "restartnotice.py")
        )
        with open(source, encoding="utf-8") as handle:
            text = handle.read()

        for forbidden in ("feed_update", "process_update", "dp.", "Dispatcher"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, text,
                    "обновления из простоя нельзя передавать обработчикам: "
                    "нажатие SOS или геопозиция сработали бы как новые",
                )

    def test_only_sender_ids_are_read(self):
        """Из обновления берётся идентификатор — и ничего больше."""
        class Trap:
            """Падает, если кто-то полезет в содержимое сообщения."""

            def __init__(self):
                self.from_user = FakeUser(1)

            def __getattr__(self, name):
                raise AssertionError(f"обращение к содержимому: {name}")

        self.assertEqual(restartnotice.chat_ids([FakeUpdate(message=Trap())]), ["1"])


class TestLimits(unittest.TestCase):
    def test_cap_is_sane(self):
        self.assertGreater(restartnotice.MAX_NOTIFIED, 0)
        self.assertLessEqual(restartnotice.MAX_NOTIFIED, 200,
                             "похоже уже на рассылку, а не на извинение")


if __name__ == "__main__":
    unittest.main(verbosity=2)
