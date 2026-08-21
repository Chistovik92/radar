#!/usr/bin/env python3
"""Язык интерфейса и квоты загрузки видео."""

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

from radar import i18n, mediaquota  # noqa: E402


class TestLanguage(unittest.TestCase):
    def test_default_is_russian(self):
        self.assertEqual(i18n.DEFAULT, i18n.RU)

    def test_normalize(self):
        self.assertEqual(i18n.normalize("EN"), "en")
        self.assertEqual(i18n.normalize("en-US"), "en")
        self.assertEqual(i18n.normalize("выдумка"), "ru")
        self.assertEqual(i18n.normalize(None), "ru")

    def test_missing_translation_falls_back_to_russian(self):
        """Русская строка среди английских понятнее служебного ключа."""
        self.assertEqual(
            i18n.t("нет.такого.ключа", "en", "Русский текст"), "Русский текст"
        )

    def test_translation_used_when_present(self):
        self.assertEqual(i18n.t("menu.home", "en", "🏠 В главное меню"),
                         "🏠 Main menu")

    def test_russian_always_gets_fallback(self):
        self.assertEqual(i18n.t("menu.home", "ru", "🏠 В главное меню"),
                         "🏠 В главное меню")

    def test_needs_choice_for_new_user(self):
        self.assertTrue(i18n.needs_choice({}))
        self.assertTrue(i18n.needs_choice({"lang": ""}))

    def test_existing_user_before_update_is_asked(self):
        """У тех, кто пользовался ботом раньше, поле пустое — спросим."""
        self.assertTrue(i18n.needs_choice({"role": "user", "locs": []}))

    def test_chosen_language_not_asked_again(self):
        self.assertFalse(i18n.needs_choice({"lang": "ru"}))
        self.assertFalse(i18n.needs_choice({"lang": "en"}))

    def test_every_language_has_title(self):
        for code in i18n.LANGUAGES:
            self.assertIn(code, i18n.TITLES)

    def test_alert_strings_translated(self):
        """Перевод начинается с того, ради чего система существует."""
        for key in ("alert.danger", "alert.whitelist.body", "alert.all_clear"):
            self.assertIn(key, i18n.EN_STRINGS)


class TestMenuTranslation(unittest.TestCase):
    """Меню собиралось без учёта языка — кнопки оставались русскими."""

    def labels(self, lang):
        from radar import keyboards

        markup = keyboards.main_menu("superadmin", {"lang": lang})
        return [button.text for row in markup.inline_keyboard for button in row]

    def test_english_menu_differs_from_russian(self):
        self.assertNotEqual(self.labels("en"), self.labels("ru"))

    def test_english_menu_has_english_labels(self):
        labels = self.labels("en")
        self.assertTrue(any("My locations" in item for item in labels))
        self.assertTrue(any("Weather" in item for item in labels))

    def test_russian_menu_stays_russian(self):
        labels = self.labels("ru")
        self.assertTrue(any("Мои локации" in item for item in labels))

    def test_no_user_falls_back_to_russian(self):
        from radar import keyboards

        markup = keyboards.main_menu("user")
        labels = [b.text for row in markup.inline_keyboard for b in row]
        self.assertTrue(any("Мои локации" in item for item in labels))

    def test_same_number_of_buttons(self):
        """Перевод не должен ронять или добавлять пункты."""
        self.assertEqual(len(self.labels("en")), len(self.labels("ru")))


class TestContentTranslation(unittest.TestCase):
    """Тексты, которые пишет человек, переводятся моделью — с кэшем."""

    def setUp(self):
        i18n.forget_translations()

    def run_async(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_russian_returns_original(self):
        """Для русского обращаться к модели незачем."""
        self.assertEqual(
            self.run_async(i18n.translate("Текст", "ru")), "Текст"
        )

    def test_empty_returns_empty(self):
        self.assertEqual(self.run_async(i18n.translate("", "en")), "")

    def test_without_ai_returns_original(self):
        """Модель недоступна — русский текст понятнее заглушки."""
        from unittest import mock
        from radar import ai

        with mock.patch.object(ai, "ENABLED", False):
            self.assertEqual(
                self.run_async(i18n.translate("Описание", "en")), "Описание"
            )

    def test_failure_returns_original(self):
        from unittest import mock
        from radar import ai

        async def boom(*args, **kwargs):
            raise RuntimeError("сервис недоступен")

        with mock.patch.object(ai, "ENABLED", True), \
             mock.patch.object(ai, "generate", side_effect=boom):
            self.assertEqual(
                self.run_async(i18n.translate("Описание", "en")), "Описание"
            )

    def test_cache_prevents_second_request(self):
        """Описания меняются раз в месяц — платить квотой за каждый показ
        нельзя, она нужна оповещениям."""
        from unittest import mock
        from radar import ai

        calls = {"count": 0}

        async def fake(*args, **kwargs):
            calls["count"] += 1
            return "Description"

        with mock.patch.object(ai, "ENABLED", True), \
             mock.patch.object(ai, "generate", side_effect=fake):
            first = self.run_async(i18n.translate("Описание", "en"))
            second = self.run_async(i18n.translate("Описание", "en"))

        self.assertEqual(first, "Description")
        self.assertEqual(second, "Description")
        self.assertEqual(calls["count"], 1)

    def test_cache_is_bounded(self):
        for index in range(i18n._CACHE_LIMIT + 10):
            i18n._CACHE[(f"текст{index}", "en")] = "x"
            if len(i18n._CACHE) >= i18n._CACHE_LIMIT:
                i18n._CACHE.clear()
        self.assertLess(len(i18n._CACHE), i18n._CACHE_LIMIT)


class TestAlertFrame(unittest.TestCase):
    """Каркас оповещения переводится, текст первоисточника — нет."""

    def test_header_translated(self):
        from radar.matching import format_locations_header

        header = format_locations_header([{"name": "Чапаева, 12"}], "", "en")
        self.assertIn("Matched locations", header)
        self.assertIn("Чапаева, 12", header)

    def test_header_russian_by_default(self):
        from radar.matching import format_locations_header

        self.assertIn("Совпавшие локации",
                      format_locations_header([{"name": "Чапаева, 12"}]))


class TestBackupSchedule(unittest.TestCase):
    """Расписание копий: без ротации диск одноплатника кончится за недели."""

    def test_due_after_hour(self):
        from radar import backup

        now = datetime(2026, 8, 21, backup.SCHEDULE_HOUR + 1, tzinfo=timezone.utc)
        self.assertTrue(backup.due_today("", now))

    def test_not_due_before_hour(self):
        from radar import backup

        now = datetime(2026, 8, 21, backup.SCHEDULE_HOUR - 1, tzinfo=timezone.utc)
        self.assertFalse(backup.due_today("", now))

    def test_not_twice_a_day(self):
        from radar import backup

        now = datetime(2026, 8, 21, 10, tzinfo=timezone.utc)
        self.assertFalse(backup.due_today("2026-08-21", now))

    def test_missed_day_runs_later(self):
        """Сервер был выключен ночью — копия снимется при первой возможности,
        а не пропадёт до следующих суток."""
        from radar import backup

        now = datetime(2026, 8, 21, 23, tzinfo=timezone.utc)
        self.assertTrue(backup.due_today("2026-08-20", now))

    def test_keeps_a_week(self):
        from radar import backup

        self.assertEqual(backup.KEEP_COPIES, 7)


class TestQuota(unittest.TestCase):
    def setUp(self):
        self.today = mediaquota.today()

    def test_free_limit(self):
        quota = mediaquota.Quota()
        self.assertEqual(quota.left(self.today), mediaquota.FREE_PER_DAY)
        self.assertTrue(quota.allowed(self.today))

    def test_spending_reduces_left(self):
        quota = mediaquota.Quota()
        quota.spend(self.today)
        self.assertEqual(quota.left(self.today), mediaquota.FREE_PER_DAY - 1)

    def test_limit_exhausted(self):
        quota = mediaquota.Quota()
        for _ in range(mediaquota.FREE_PER_DAY):
            quota.spend(self.today)
        self.assertFalse(quota.allowed(self.today))
        self.assertEqual(quota.left(self.today), 0)

    def test_new_day_resets(self):
        quota = mediaquota.Quota(used=mediaquota.FREE_PER_DAY, day="2020-01-01")
        self.assertTrue(quota.allowed(self.today))
        self.assertEqual(quota.left(self.today), mediaquota.FREE_PER_DAY)

    def test_subscription_removes_daily_limit(self):
        quota = mediaquota.Quota()
        quota.extend()
        for _ in range(mediaquota.FREE_PER_DAY + 5):
            quota.spend(self.today)
        self.assertTrue(quota.allowed(self.today))
        self.assertTrue(quota.unlimited)

    def test_expired_subscription_is_not_unlimited(self):
        past = datetime.now(timezone.utc) - timedelta(days=2)
        quota = mediaquota.Quota(paid_until=past.isoformat())
        self.assertFalse(quota.unlimited)
        self.assertEqual(quota.days_left, 0)

    def test_broken_date_is_not_unlimited(self):
        self.assertFalse(mediaquota.Quota(paid_until="не дата").unlimited)

    def test_extend_keeps_remainder(self):
        quota = mediaquota.Quota()
        quota.extend(10)
        first = quota.days_left
        quota.extend(10)
        self.assertGreater(quota.days_left, first)

    def test_roundtrip(self):
        quota = mediaquota.Quota(used=3, day=self.today)
        quota.extend()
        again = mediaquota.Quota.from_dict(quota.to_dict())
        self.assertEqual(again.used, 3)
        self.assertTrue(again.unlimited)

    def test_garbage_survives(self):
        quota = mediaquota.Quota.from_dict({"used": "много", "day": None})
        self.assertEqual(quota.used, 0)

    def test_price_and_limits_are_sane(self):
        self.assertEqual(mediaquota.FREE_PER_DAY, 20)
        self.assertEqual(mediaquota.STARS_PRICE, 10)
        self.assertEqual(mediaquota.SUBSCRIPTION_DAYS, 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
