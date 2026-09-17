#!/usr/bin/env python3
"""Правила модерации групп (с 4.9.8.11).

Решения проверяются таблицей случаев и без Telegram: ошибка здесь стоит
забаненного живого человека, и обнаруживать её надо на тесте.
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import moderation  # noqa: E402


def author(**kwargs) -> moderation.Author:
    base = {"user_id": 42, "joined_ago_hours": 999.0, "warns": 0,
            "is_admin": False}
    base.update(kwargs)
    return moderation.Author(**base)


class Untouched(unittest.TestCase):
    def test_clean_message_passes(self):
        decision = moderation.decide("Привет, как дела?", author(),
                                     moderation.Settings())
        self.assertEqual(decision.action, moderation.NONE)
        self.assertFalse(decision.acts)

    def test_admin_is_never_moderated(self):
        settings = moderation.Settings(stopwords=["казино"])
        decision = moderation.decide("казино тут", author(is_admin=True),
                                     settings)
        self.assertFalse(decision.acts)

    def test_old_member_may_post_links(self):
        settings = moderation.Settings(links_from_newcomers=True,
                                       delete_spam_links=False)
        decision = moderation.decide("смотри https://example.com/page",
                                     author(joined_ago_hours=500), settings)
        self.assertFalse(decision.acts)


class Violations(unittest.TestCase):
    def test_stopword_deletes_and_warns(self):
        settings = moderation.Settings(stopwords=["Казино"])
        decision = moderation.decide("лучшее казино тут", author(), settings)
        self.assertEqual(decision.action, moderation.WARN)
        self.assertTrue(decision.delete_message)
        self.assertIn("стоп-слово", decision.reason)

    def test_newcomer_link_is_removed(self):
        decision = moderation.decide("https://example.com",
                                     author(joined_ago_hours=1),
                                     moderation.Settings())
        self.assertTrue(decision.delete_message)
        self.assertIn("новичк", decision.reason)

    def test_bare_domain_counts_as_link(self):
        # Спам чаще приходит без схемы: «заходи на example.com».
        self.assertTrue(moderation.extract_urls("заходи на example.com"))
        self.assertTrue(moderation.extract_urls("вот t.me/joinchat/xxx"))

    def test_flood_is_caught(self):
        settings = moderation.Settings(flood_messages=3)
        decision = moderation.decide("ок", author(), settings, flood_count=4)
        self.assertEqual(decision.action, moderation.WARN)
        # Флуд не удаляет сообщение: удалять реплику за темп — перебор.
        self.assertFalse(decision.delete_message)


class Ladder(unittest.TestCase):
    """Лестница считается по накопленным плюс текущее нарушение."""

    def setUp(self) -> None:
        self.settings = moderation.Settings(stopwords=["спам"],
                                            warns_before_mute=3,
                                            warns_before_ban=5)

    def _action(self, warns: int) -> str:
        return moderation.decide("спам", author(warns=warns),
                                 self.settings).action

    def test_first_violations_only_warn(self):
        self.assertEqual(self._action(0), moderation.WARN)
        self.assertEqual(self._action(1), moderation.WARN)

    def test_third_violation_mutes(self):
        self.assertEqual(self._action(2), moderation.MUTE)

    def test_fifth_violation_bans(self):
        self.assertEqual(self._action(4), moderation.BAN)

    def test_description_is_human(self):
        decision = moderation.decide("спам", author(warns=2), self.settings)
        text = moderation.describe(decision, self.settings)
        self.assertIn("Ограничение", text)
        self.assertIn(str(self.settings.mute_minutes), text)


class Flood(unittest.TestCase):
    def test_window_forgets_old_messages(self):
        tracker = moderation.FloodTracker()
        for moment in range(5):
            count = tracker.hit(1, 1, window=10, now=float(moment))
        self.assertEqual(count, 5)
        # Спустя окно счёт начинается заново.
        self.assertEqual(tracker.hit(1, 1, window=10, now=100.0), 1)

    def test_users_are_counted_separately(self):
        tracker = moderation.FloodTracker()
        tracker.hit(1, 1, window=10, now=1.0)
        self.assertEqual(tracker.hit(1, 2, window=10, now=1.0), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
