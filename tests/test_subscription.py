#!/usr/bin/env python3
"""Единая подписка: оплата одной части открывает обе."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import digest, mediaquota, subscription  # noqa: E402


def ahead(days=20):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def behind(days=5):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def user(role="user", digest_until="", media_until=""):
    return {
        "role": role,
        "digest": {"paid_until": digest_until},
        "media_quota": {"paid_until": media_until},
    }


class TestSharedSubscription(unittest.TestCase):
    """Для человека подписка одна: он заплатил и ждёт, что работает всё."""

    def test_digest_payment_unlocks_media(self):
        record = user(digest_until=ahead())
        self.assertTrue(mediaquota.quota_of(record, "user").unlimited)

    def test_media_payment_unlocks_digest(self):
        record = user(media_until=ahead())
        self.assertTrue(digest.subscription_of(record).active)

    def test_nothing_paid(self):
        record = user()
        self.assertFalse(digest.subscription_of(record).active)
        self.assertFalse(mediaquota.quota_of(record, "user").unlimited)

    def test_expired_does_not_unlock(self):
        record = user(digest_until=behind())
        self.assertFalse(mediaquota.quota_of(record, "user").unlimited)

    def test_longest_term_wins(self):
        """Продление одной части не укорачивает другую."""
        record = user(digest_until=ahead(5), media_until=ahead(40))
        self.assertGreater(subscription.days_left(record), 30)

    def test_broken_date_ignored(self):
        record = user(digest_until="не дата", media_until=ahead())
        self.assertTrue(subscription.paid(record))


class TestAdminAccess(unittest.TestCase):
    """Администрации всё открыто — иначе ошибку в платной части
    первым найдёт тот, кто заплатил."""

    def test_admin_gets_everything(self):
        for role in ("admin", "superadmin"):
            with self.subTest(role=role):
                record = user(role=role)
                self.assertTrue(digest.subscription_of(record).active)
                self.assertTrue(mediaquota.quota_of(record, role).unlimited)

    def test_admin_has_all_topics(self):
        record = user(role="admin")
        self.assertEqual(
            digest.subscription_of(record).limit, len(digest.TOPICS)
        )

    def test_admin_quota_never_runs_out(self):
        record = user(role="admin")
        quota = mediaquota.quota_of(record, "admin")
        for _ in range(mediaquota.FREE_PER_DAY * 3):
            quota.spend(mediaquota.today())
        self.assertTrue(quota.allowed(mediaquota.today()))

    def test_moderator_and_user_stay_limited(self):
        for role in ("user", "moderator"):
            with self.subTest(role=role):
                record = user(role=role)
                self.assertFalse(digest.subscription_of(record).active)
                self.assertFalse(mediaquota.quota_of(record, role).unlimited)

    def test_complimentary_not_stored(self):
        """Понижение роли обязано закрывать доступ сразу."""
        record = user(role="admin")
        quota = mediaquota.quota_of(record, "admin")
        self.assertNotIn("complimentary", quota.to_dict())
        self.assertFalse(mediaquota.quota_of(record, "user").unlimited)

    def test_admin_has_no_fake_days(self):
        """Служебный доступ не выдаёт себя за оплаченную подписку."""
        record = user(role="admin")
        self.assertEqual(mediaquota.quota_of(record, "admin").days_left, 0)
        self.assertEqual(subscription.days_left(record), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
