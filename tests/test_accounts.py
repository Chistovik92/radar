#!/usr/bin/env python3
"""Живые и мёртвые аккаунты (с 5.9.4).

Закреплено то, что ломается тихо: удалённый аккаунт распознаётся только
по совокупности признаков, мёртвый получатель не получает запросов,
CAS не блокирует при своей недоступности, чистка не трогает тех, кого
не удалось проверить, а тайм-аут капчи работает только по флагу.
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
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import accounts, features, storage  # noqa: E402
from radar.db import repo  # noqa: E402
from radar.handlers import group  # noqa: E402


def user(first="Иван", last=None, username=None, uid=5):
    return NS(first_name=first, last_name=last, username=username, id=uid)


class Deleted(unittest.TestCase):
    def test_deleted_account_recognised(self):
        self.assertTrue(accounts.is_deleted_user(user("Deleted Account")))
        self.assertTrue(accounts.is_deleted_user(user("  deleted account ")))
        self.assertTrue(accounts.is_deleted_user(user("Удалённый аккаунт")))

    def test_real_people_are_not_deleted(self):
        self.assertFalse(accounts.is_deleted_user(user("Иван")))
        self.assertFalse(accounts.is_deleted_user(None))
        # Имя совпало, но есть имя пользователя или фамилия — живой человек.
        self.assertFalse(accounts.is_deleted_user(user("Deleted Account", username="x")))
        self.assertFalse(accounts.is_deleted_user(user("Deleted Account", last="Smith")))


class FakeStore:
    def __init__(self, people):
        self.people = people

    def __enter__(self):
        self._orig = (storage.get_user, storage.users)
        storage.get_user = lambda uid: self.people.get(str(uid))
        storage.users = lambda: self.people
        return self

    def __exit__(self, *exc):
        storage.get_user, storage.users = self._orig


class Dead(unittest.TestCase):
    def test_mark_and_revive(self):
        with FakeStore({"7": {"role": "user"}}) as store:
            self.assertFalse(accounts.is_dead(7))
            self.assertTrue(accounts.mark_dead(7))
            self.assertTrue(accounts.is_dead(7))
            self.assertFalse(accounts.mark_dead(7))          # повтор — не новость
            self.assertEqual([k for k, _ in accounts.stale()], ["7"])
            self.assertTrue(accounts.mark_alive(7))
            self.assertFalse(accounts.is_dead(7))
            self.assertNotIn("dead", store.people["7"])

    def test_groups_and_unknown_are_never_marked(self):
        with FakeStore({"-100": {"role": "user"}}):
            self.assertFalse(accounts.mark_dead(-100))       # группа
            self.assertFalse(accounts.mark_dead(99))         # нет такого
            self.assertFalse(accounts.mark_dead("vk:5"))     # не Telegram

    def test_send_skips_dead_recipient_without_api_call(self):
        from radar import tg

        calls = []

        class Bot:
            async def send_message(self, *a, **k):
                calls.append(a)

        original = tg.bot
        tg.bot = Bot()
        try:
            with FakeStore({"7": {"role": "user", "dead": 1}}):
                ok = asyncio.run(tg.send_html(7, "тревога"))
        finally:
            tg.bot = original
        self.assertFalse(ok)
        self.assertEqual(calls, [])


class Cas(unittest.TestCase):
    def check(self, fetch):
        return asyncio.run(accounts.cas_banned(1, fetch=fetch))

    def test_listed(self):
        async def fetch(_):
            return {"ok": True}
        self.assertIs(self.check(fetch), True)

    def test_not_listed(self):
        async def fetch(_):
            return {"ok": False, "description": "Record not found"}
        self.assertIs(self.check(fetch), False)

    def test_unavailable_is_unknown_not_banned(self):
        async def boom(_):
            raise OSError("down")

        async def empty(_):
            return None
        self.assertIsNone(self.check(boom))
        self.assertIsNone(self.check(empty))


class FakeBot:
    def __init__(self, members, total=None, failing=()):
        self.members = members          # id -> User
        self.total = total
        self.failing = set(failing)
        self.banned, self.unbanned, self.deleted_messages = [], [], []

    async def get_chat_member_count(self, chat_id):
        if self.total is None:
            raise RuntimeError("no")
        return self.total

    async def get_chat_member(self, chat_id, user_id):
        if user_id in self.failing:
            raise RuntimeError("left")
        return NS(user=self.members[user_id])

    async def ban_chat_member(self, chat_id, user_id, **_):
        self.banned.append(user_id)

    async def unban_chat_member(self, chat_id, user_id, **_):
        self.unbanned.append(user_id)

    async def delete_message(self, chat_id, message_id):
        self.deleted_messages.append(message_id)


class Scan(unittest.TestCase):
    def test_scan_finds_deleted_and_reports_coverage(self):
        bot = FakeBot({1: user("Аня", uid=1), 2: user("Deleted Account", uid=2),
                       3: user("Deleted Account", uid=3), 4: user("x", uid=4)},
                      total=40, failing=[4])
        result = asyncio.run(accounts.scan_chat(bot, -100, [1, 2, 3, 4], pause=0))
        self.assertEqual(result.deleted, [2, 3])
        self.assertEqual(result.checked, 3)
        self.assertEqual(result.failed, 1)          # не удалось — не «удалён»
        self.assertEqual(result.coverage, "4 / 40")

    def test_unknown_total_does_not_break(self):
        bot = FakeBot({1: user(uid=1)}, total=None)
        result = asyncio.run(accounts.scan_chat(bot, -100, [1], pause=0))
        self.assertIsNone(result.members_total)
        self.assertEqual(result.coverage, "1")

    def test_remove_bans_then_unbans_and_forgets(self):
        dropped = []

        async def drop(chat, uid):
            dropped.append((chat, uid))

        original = repo.member_drop
        repo.member_drop = drop
        try:
            bot = FakeBot({})
            removed = asyncio.run(accounts.remove_deleted(bot, -100, [2, 3], pause=0))
        finally:
            repo.member_drop = original
        self.assertEqual(removed, 2)
        self.assertEqual(bot.banned, [2, 3])
        self.assertEqual(bot.unbanned, [2, 3])      # бан сразу снимается
        self.assertEqual(dropped, [(-100, 2), (-100, 3)])


class Captcha(unittest.TestCase):
    def setUp(self):
        group._pending.clear()
        group._captcha_msgs.clear()
        self._settings = group._settings

        async def settings(chat_id):
            from radar import moderation

            return True, moderation.Settings(captcha_minutes=5)

        group._settings = settings
        self._flag = features.enabled("captcha_kick")

    def tearDown(self):
        group._settings = self._settings
        features.set_local("captcha_kick", self._flag)
        group._pending.clear()
        group._captcha_msgs.clear()

    def sweep(self, bot):
        """Один проход сторожа: второй sleep обрывает бесконечный цикл."""
        calls = {"n": 0}

        async def fake_sleep(_):
            calls["n"] += 1
            if calls["n"] > 1:
                raise asyncio.CancelledError

        original = group.asyncio.sleep
        group.asyncio.sleep = fake_sleep
        try:
            try:
                asyncio.run(group.captcha_sweeper(bot))
            except asyncio.CancelledError:
                pass
        finally:
            group.asyncio.sleep = original

    def test_flag_off_does_nothing(self):
        features.set_local("captcha_kick", False)
        group._pending[(-100, 7)] = time.time() - 3600
        bot = FakeBot({})
        self.sweep(bot)
        self.assertEqual(bot.banned, [])
        self.assertIn((-100, 7), group._pending)

    def test_overdue_is_kicked_not_banned_forever(self):
        features.set_local("captcha_kick", True)
        group._pending[(-100, 7)] = time.time() - 400          # > 5 минут
        group._captcha_msgs[(-100, 7)] = 55
        bot = FakeBot({})
        self.sweep(bot)
        self.assertEqual(bot.banned, [7])
        self.assertEqual(bot.unbanned, [7])                    # вернуться можно
        self.assertEqual(bot.deleted_messages, [55])
        self.assertNotIn((-100, 7), group._pending)

    def test_recent_is_left_alone(self):
        features.set_local("captcha_kick", True)
        group._pending[(-100, 8)] = time.time() - 30
        bot = FakeBot({})
        self.sweep(bot)
        self.assertEqual(bot.banned, [])
        self.assertIn((-100, 8), group._pending)

    def test_default_flags_are_off(self):
        for key in ("captcha_kick", "deleted_cleanup", "cas_check"):
            with self.subTest(flag=key):
                flag = features.resolve(key)
                self.assertIsNotNone(flag)
                self.assertFalse(flag.default)


class Remembering(unittest.TestCase):
    def test_remembered_once_and_only_with_flag(self):
        seen = []

        async def member_seen(chat, uid):
            seen.append((chat, uid))

        original, was = repo.member_seen, features.enabled("deleted_cleanup")
        repo.member_seen = member_seen
        group._remembered.clear()
        try:
            features.set_local("deleted_cleanup", False)
            asyncio.run(group._remember(-1, 5))
            self.assertEqual(seen, [])
            features.set_local("deleted_cleanup", True)
            asyncio.run(group._remember(-1, 5))
            asyncio.run(group._remember(-1, 5))
            self.assertEqual(seen, [(-1, 5)])               # один запрос к базе
        finally:
            repo.member_seen = original
            features.set_local("deleted_cleanup", was)
            group._remembered.clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
