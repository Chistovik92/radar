#!/usr/bin/env python3
"""Новостные подборки, тихие часы, антиспам и веб-панель."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import digest, quiet  # noqa: E402
from radar.web import auth  # noqa: E402


# ==========================================================================
#  Подборки
# ==========================================================================

class TestTopics(unittest.TestCase):
    def test_twelve_topics(self):
        self.assertEqual(len(digest.TOPICS), 12)

    def test_keys_unique(self):
        keys = [item.key for item in digest.TOPICS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_classification(self):
        cases = {
            "Отключение отопления по улице Чапаева": "utilities",
            "ДТП на трассе, пострадали двое": "incidents",
            "Открылась выставка в музее": "culture",
            "Губернатор подписал постановление": "city",
        }
        for text, expected in cases.items():
            self.assertEqual(digest.topic_of(text), expected, text)

    def test_unknown_text_gives_none(self):
        self.assertIsNone(digest.topic_of("абракадабра ъъъ"))


class TestSubscription(unittest.TestCase):
    def setUp(self):
        self.subscription = digest.Subscription()

    def test_free_limit(self):
        self.assertEqual(self.subscription.limit, digest.FREE_TOPICS)

    def test_toggle_within_limit(self):
        enabled, reason = self.subscription.toggle("city")
        self.assertTrue(enabled)
        self.assertEqual(reason, "")

    def test_toggle_beyond_free_limit(self):
        self.subscription.toggle("city")
        enabled, reason = self.subscription.toggle("incidents")
        self.assertFalse(enabled)
        self.assertIn("подписк", reason.lower())

    def test_toggle_off(self):
        self.subscription.toggle("city")
        enabled, _reason = self.subscription.toggle("city")
        self.assertFalse(enabled)
        self.assertEqual(self.subscription.topics, [])

    def test_unknown_topic_rejected(self):
        enabled, reason = self.subscription.toggle("выдуманная")
        self.assertFalse(enabled)
        self.assertIn("Неизвестная", reason)

    def test_paid_unlocks_all(self):
        self.subscription.extend(30)
        self.assertTrue(self.subscription.active)
        self.assertEqual(self.subscription.limit, len(digest.TOPICS))

    def test_extend_keeps_remainder(self):
        self.subscription.extend(10)
        first = self.subscription.days_left
        self.subscription.extend(10)
        self.assertGreater(self.subscription.days_left, first)

    def test_expired_subscription_inactive(self):
        past = datetime.now(timezone.utc) - timedelta(days=3)
        self.subscription.paid_until = past.isoformat()
        self.assertFalse(self.subscription.active)
        self.assertEqual(self.subscription.days_left, 0)

    def test_broken_date_is_inactive(self):
        self.subscription.paid_until = "не дата"
        self.assertFalse(self.subscription.active)

    def test_allowed_trimmed_without_payment(self):
        self.subscription.topics = ["city", "incidents", "culture"]
        self.assertEqual(len(self.subscription.allowed_topics()), digest.FREE_TOPICS)

    def test_serialization_roundtrip(self):
        self.subscription.toggle("city")
        self.subscription.extend(30)
        restored = digest.Subscription.from_dict(self.subscription.to_dict())
        self.assertEqual(restored.topics, ["city"])
        self.assertTrue(restored.active)

    def test_garbage_topics_dropped(self):
        restored = digest.Subscription.from_dict({"topics": ["city", "чепуха", 5]})
        self.assertEqual(restored.topics, ["city"])


class TestSchedule(unittest.TestCase):
    def setUp(self):
        self.subscription = digest.Subscription(topics=["city"], times=["08:30"])

    def test_due_in_window(self):
        moment = datetime(2026, 8, 15, 8, 32)
        self.assertIsNotNone(digest.due(self.subscription, moment))

    def test_not_due_before(self):
        self.assertIsNone(digest.due(self.subscription, datetime(2026, 8, 15, 8, 25)))

    def test_not_due_long_after(self):
        self.assertIsNone(digest.due(self.subscription, datetime(2026, 8, 15, 9, 30)))

    def test_not_sent_twice(self):
        moment = datetime(2026, 8, 15, 8, 31)
        marker = digest.due(self.subscription, moment)
        self.subscription.last_sent = marker
        self.assertIsNone(digest.due(self.subscription, moment))

    def test_no_topics_means_no_delivery(self):
        empty = digest.Subscription(times=["08:30"])
        self.assertIsNone(digest.due(empty, datetime(2026, 8, 15, 8, 31)))

    def test_broken_time_ignored(self):
        broken = digest.Subscription(topics=["city"], times=["25:99", "08:30"])
        self.assertIsNotNone(digest.due(broken, datetime(2026, 8, 15, 8, 31)))


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.entries = [
            digest.Entry(topic="city", summary="Открыт новый сквер"),
            digest.Entry(topic="incidents", summary="ДТП на кольце",
                         link="https://example.ru/1"),
        ]

    def test_only_allowed_topics(self):
        subscription = digest.Subscription(topics=["city", "incidents"])
        text = digest.build(self.entries, subscription, datetime(2026, 8, 15, 8, 30))
        self.assertIn("сквер", text)
        self.assertNotIn("ДТП", text)   # вторая тематика недоступна без подписки

    def test_paid_gets_everything(self):
        subscription = digest.Subscription(topics=["city", "incidents"])
        subscription.extend(30)
        text = digest.build(self.entries, subscription, datetime(2026, 8, 15, 8, 30))
        self.assertIn("сквер", text)
        self.assertIn("ДТП", text)

    def test_link_rendered(self):
        subscription = digest.Subscription(topics=["incidents"])
        text = digest.build(self.entries, subscription, datetime(2026, 8, 15, 8, 30))
        self.assertIn("https://example.ru/1", text)

    def test_empty_gives_nothing(self):
        subscription = digest.Subscription(topics=["city"])
        self.assertEqual(digest.build([], subscription, datetime.now()), "")

    def test_separated_from_alerts(self):
        subscription = digest.Subscription(topics=["city"])
        text = digest.build(self.entries, subscription, datetime(2026, 8, 15, 8, 30))
        self.assertIn("Об опасности бот сообщает отдельно", text)

    def test_period_titles(self):
        self.assertIn("утренняя", digest.period_title(datetime(2026, 8, 15, 9, 0)))
        self.assertIn("вечерняя", digest.period_title(datetime(2026, 8, 15, 20, 0)))


# ==========================================================================
#  Тихие часы и антиспам
# ==========================================================================

class TestQuietHours(unittest.TestCase):
    def setUp(self):
        self.user = {"quiet_from": "23:00", "quiet_to": "07:00"}

    def test_inside_overnight_interval(self):
        self.assertTrue(quiet.in_quiet_hours(self.user, datetime(2026, 8, 15, 2, 0)))
        self.assertTrue(quiet.in_quiet_hours(self.user, datetime(2026, 8, 15, 23, 30)))

    def test_outside_interval(self):
        self.assertFalse(quiet.in_quiet_hours(self.user, datetime(2026, 8, 15, 12, 0)))

    def test_daytime_interval(self):
        user = {"quiet_from": "10:00", "quiet_to": "12:00"}
        self.assertTrue(quiet.in_quiet_hours(user, datetime(2026, 8, 15, 11, 0)))
        self.assertFalse(quiet.in_quiet_hours(user, datetime(2026, 8, 15, 13, 0)))

    def test_not_set_means_off(self):
        self.assertFalse(quiet.in_quiet_hours({}, datetime(2026, 8, 15, 3, 0)))

    def test_broken_values_ignored(self):
        user = {"quiet_from": "мусор", "quiet_to": "07:00"}
        self.assertFalse(quiet.in_quiet_hours(user, datetime(2026, 8, 15, 3, 0)))

    def test_urgent_always_passes(self):
        """Военные угрозы и МЧС должны будить — в этом смысл системы."""
        night = datetime(2026, 8, 15, 3, 0)
        self.assertFalse(quiet.should_hold({"bpla"}, self.user, night))
        self.assertFalse(quiet.should_hold({"mchs"}, self.user, night))

    def test_utility_held_at_night(self):
        night = datetime(2026, 8, 15, 3, 0)
        self.assertTrue(quiet.should_hold({"jkh"}, self.user, night))

    def test_utility_passes_by_day(self):
        noon = datetime(2026, 8, 15, 12, 0)
        self.assertFalse(quiet.should_hold({"jkh"}, self.user, noon))

    def test_hold_and_release(self):
        quiet._held.clear()
        quiet.hold("42", "Нет воды")
        self.assertEqual(quiet.release("42", self.user, datetime(2026, 8, 15, 3, 0)), [])
        released = quiet.release("42", self.user, datetime(2026, 8, 15, 12, 0))
        self.assertEqual(released, ["Нет воды"])
        self.assertEqual(quiet.held_count(), 0)


class TestAntispam(unittest.TestCase):
    def setUp(self):
        quiet.deliveries.seen.clear()

    def test_same_text_detected(self):
        text = "Отключение воды по улице Чапаева, дома 12 и 14"
        self.assertFalse(quiet.deliveries.already("1", "loc", text))
        quiet.deliveries.remember("1", "loc", text)
        self.assertTrue(quiet.deliveries.already("1", "loc", text))

    def test_reworded_text_detected(self):
        """Городские каналы пересказывают одно событие по-разному."""
        first = "Внимание! Отключение воды по улице Чапаева, дома 12 и 14"
        second = "Отключение воды: улица Чапаева, дома 12 и 14. Внимание!"
        self.assertEqual(quiet.fingerprint(first), quiet.fingerprint(second))

    def test_different_events_not_confused(self):
        first = "Отключение воды по улице Чапаева"
        second = "Отключение электричества по проспекту Кирова"
        self.assertNotEqual(quiet.fingerprint(first), quiet.fingerprint(second))

    def test_separate_users_independent(self):
        text = "Нет воды"
        quiet.deliveries.remember("1", "loc", text)
        self.assertFalse(quiet.deliveries.already("2", "loc", text))

    def test_memory_expires(self):
        text = "Нет воды"
        old = time.time() - (quiet.MEMORY_HOURS + 1) * 3600
        quiet.deliveries.remember("1", "loc", text, now=old)
        self.assertFalse(quiet.deliveries.already("1", "loc", text))

    def test_merge_similar_in_batch(self):
        messages = [
            ("city", "Отключение воды по улице Чапаева дома 12"),
            ("city", "По улице Чапаева отключение воды, дома 12"),
            ("city", "Гроза с усилением ветра до 25 метров"),
        ]
        self.assertEqual(len(quiet.merge_similar(messages)), 2)


# ==========================================================================
#  Веб-панель
# ==========================================================================

class TestWebAuth(unittest.TestCase):
    TOKEN = "123456:TESTTOKEN"

    def _sign(self, data: dict) -> dict:
        pairs = sorted(f"{key}={value}" for key, value in data.items())
        secret = hashlib.sha256(self.TOKEN.encode()).digest()
        signature = hmac.new(secret, "\n".join(pairs).encode(), hashlib.sha256).hexdigest()
        return {**data, "hash": signature}

    def test_valid_signature(self):
        data = self._sign({"id": "42", "auth_date": str(int(time.time()))})
        self.assertTrue(auth.check_signature(data, self.TOKEN))

    def test_tampered_data_rejected(self):
        data = self._sign({"id": "42", "auth_date": str(int(time.time()))})
        data["id"] = "43"
        self.assertFalse(auth.check_signature(data, self.TOKEN))

    def test_wrong_token_rejected(self):
        data = self._sign({"id": "42", "auth_date": str(int(time.time()))})
        self.assertFalse(auth.check_signature(data, "другой:токен"))

    def test_missing_hash_rejected(self):
        self.assertFalse(auth.check_signature({"id": "42"}, self.TOKEN))

    def test_fresh_auth_date(self):
        self.assertTrue(auth.check_freshness({"auth_date": str(int(time.time()))}))

    def test_stale_auth_date_rejected(self):
        old = int(time.time()) - auth.AUTH_TTL - 100
        self.assertFalse(auth.check_freshness({"auth_date": str(old)}))

    def test_missing_auth_date_rejected(self):
        self.assertFalse(auth.check_freshness({}))

    def test_plain_user_rejected(self):
        """Панель — контур управления: обычному пользователю в ней нечего делать."""
        data = self._sign({"id": "42", "auth_date": str(int(time.time()))})
        session, reason = auth.authenticate(data, self.TOKEN, lambda _key: "user")
        self.assertIsNone(session)
        self.assertIn("модератор", reason)

    def test_moderator_allowed(self):
        data = self._sign({"id": "42", "auth_date": str(int(time.time()))})
        session, reason = auth.authenticate(data, self.TOKEN, lambda _key: "moderator")
        self.assertIsNotNone(session)
        self.assertEqual(session.role, "moderator")

    def test_sections_scoped_by_role(self):
        """Разделы панели повторяют права бота, а не расширяют их."""
        from radar.web.panel import _links_for

        moderator = {key for _href, _name, key in _links_for("moderator")}
        admin = {key for _href, _name, key in _links_for("admin")}
        owner = {key for _href, _name, key in _links_for("superadmin")}

        self.assertNotIn("features", moderator)
        self.assertNotIn("audit", moderator)
        self.assertNotIn("backup", admin)
        self.assertIn("events", admin)
        self.assertIn("backup", owner)
        self.assertIn("audit", owner)
        self.assertTrue(moderator < admin < owner)

    def test_full_flow_admin_passes(self):
        data = self._sign({"id": "42", "auth_date": str(int(time.time()))})
        session, reason = auth.authenticate(data, self.TOKEN, lambda _key: "admin")
        self.assertIsNotNone(session)
        self.assertEqual(reason, "")
        self.assertIsNotNone(auth.session_by_token(session.token))

    def test_unknown_user_rejected(self):
        data = self._sign({"id": "99", "auth_date": str(int(time.time()))})
        session, reason = auth.authenticate(data, self.TOKEN, lambda _key: "")
        self.assertIsNone(session)
        self.assertIn("не зарегистрирован", reason)

    def test_session_dropped(self):
        data = self._sign({"id": "42", "auth_date": str(int(time.time()))})
        session, _reason = auth.authenticate(data, self.TOKEN, lambda _key: "superadmin")
        auth.drop_session(session.token)
        self.assertIsNone(auth.session_by_token(session.token))

    def test_rate_limit_blocks(self):
        address = "203.0.113.7"
        for _ in range(auth.MAX_ATTEMPTS):
            auth.note_failure(address)
        self.assertTrue(auth.rate_limited(address))
        auth.clear_failures(address)
        self.assertFalse(auth.rate_limited(address))


class TestWebAudit(unittest.TestCase):
    def setUp(self):
        from radar.web import audit

        self.audit = audit
        audit.clear()

    def test_record_and_read(self):
        self.audit.record("42", "вход в панель", "admin")
        entries = self.audit.recent()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].actor, "42")

    def test_newest_first(self):
        self.audit.record("1", "первое")
        self.audit.record("2", "второе")
        self.assertEqual(self.audit.recent()[0].action, "второе")


class TestBackup(unittest.TestCase):
    """Резервные копии: общий модуль для бота и панели."""

    def setUp(self):
        import tempfile

        from radar import backup as backup_module

        self.backup = backup_module
        self.tmp = tempfile.mkdtemp()
        self.saved = backup_module.DIRECTORY
        backup_module.DIRECTORY = os.path.join(self.tmp, "backups")

    def tearDown(self):
        import shutil

        self.backup.DIRECTORY = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_listing(self):
        self.assertEqual(self.backup.listing(), [])

    def test_summary_without_copies(self):
        self.assertIn("пока нет", self.backup.summary())

    def test_find_rejects_traversal(self):
        self.assertIsNone(self.backup.find("../../etc/passwd"))
        self.assertIsNone(self.backup.find(".hidden"))
        self.assertIsNone(self.backup.find(""))

    def test_create_makes_archive(self):
        path, error = self.backup.create_sync("тест")
        self.assertEqual(error, "")
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        self.assertEqual(len(self.backup.listing()), 1)

    def test_archive_contains_manifest(self):
        import tarfile

        path, _error = self.backup.create_sync("тест")
        with tarfile.open(path) as bundle:
            self.assertIn("manifest.txt", bundle.getnames())

    def test_summary_lists_copies(self):
        self.backup.create_sync("тест")
        self.assertIn("radar-backup-", self.backup.summary())


class TestMenus(unittest.TestCase):
    """Структура меню: без дублей и с учётом флагов."""

    def setUp(self):
        from radar import features, keyboards

        self.keyboards = keyboards
        self.features = features
        features.apply({})

    def tearDown(self):
        self.features.apply({})

    def _callbacks(self, markup) -> list[str]:
        return [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if getattr(button, "callback_data", None)
        ]

    def test_manage_menu_has_single_ai_entry(self):
        """Раньше проверка ИИ открывалась из двух мест сразу."""
        calls = self._callbacks(self.keyboards.manage_menu("superadmin"))
        self.assertIn("ai:menu", calls)
        self.assertNotIn("bench:menu", calls)
        self.assertNotIn("prov:menu", calls)

    def test_manage_menu_no_duplicates(self):
        for role in ("moderator", "admin", "superadmin"):
            calls = self._callbacks(self.keyboards.manage_menu(role))
            self.assertEqual(len(calls), len(set(calls)), role)

    def test_manage_menu_scoped_by_role(self):
        moderator = set(self._callbacks(self.keyboards.manage_menu("moderator")))
        owner = set(self._callbacks(self.keyboards.manage_menu("superadmin")))
        self.assertNotIn("feat:list", moderator)
        self.assertIn("feat:list", owner)
        self.assertTrue(moderator < owner)

    def test_ai_menu_gathers_everything(self):
        calls = self._callbacks(self.keyboards.ai_menu())
        for expected in ("prov:menu", "bench:menu", "ai:models"):
            self.assertIn(expected, calls)

    def test_main_menu_has_invite_for_everyone(self):
        calls = self._callbacks(self.keyboards.main_menu("user"))
        self.assertIn("usr:invite", calls)

    def test_main_menu_no_duplicates(self):
        for role in ("user", "moderator", "admin", "superadmin"):
            calls = self._callbacks(self.keyboards.main_menu(role))
            self.assertEqual(len(calls), len(set(calls)), role)


class TestWeatherFormat(unittest.TestCase):
    """Переключатель вида сводки погоды."""

    def setUp(self):
        from radar import features, keyboards

        self.keyboards = keyboards
        self.features = features

    def tearDown(self):
        self.features.apply({})

    def _callbacks(self, markup) -> list[str]:
        return [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if getattr(button, "callback_data", None)
        ]

    def test_hidden_when_flag_off(self):
        self.features.apply({})
        calls = self._callbacks(self.keyboards.settings_menu({"settings": {}}))
        self.assertNotIn("set:wformat", calls)

    def test_shown_when_flag_on(self):
        self.features.apply({"weather_image": True})
        calls = self._callbacks(self.keyboards.settings_menu({"settings": {}}))
        self.assertIn("set:wformat", calls)

    def test_quiet_hours_shown_when_enabled(self):
        self.features.apply({"quiet_hours": True})
        calls = self._callbacks(self.keyboards.settings_menu({"settings": {}}))
        self.assertIn("set:quiet", calls)

    def test_format_menu_offers_both(self):
        calls = self._callbacks(self.keyboards.weather_format_menu())
        self.assertIn("set:wfmt:text", calls)
        self.assertIn("set:wfmt:image", calls)

    def test_not_shown_for_other_user(self):
        """Администратор правит чужие настройки — вид сводки выбирает сам владелец."""
        self.features.apply({"weather_image": True})
        calls = self._callbacks(
            self.keyboards.settings_menu({"settings": {}}, target="42")
        )
        self.assertNotIn("set:wformat", calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
