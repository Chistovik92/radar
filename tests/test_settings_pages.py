#!/usr/bin/env python3
"""Раздел «Настройки» (5.9.2.2): всё, что раньше жило только в .env, правится в панели.

Главное, что здесь закреплено: у каждой возможности и каждого значения есть
страница, введённое проверяется по типу, а то, что нельзя менять из панели,
перечислено прямо — в том числе реклама внутри тревог, которой переключателя
быть не должно.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import config, features, secrets  # noqa: E402
from radar.web import panel, settingspages  # noqa: E402


class CoverageTests(unittest.TestCase):
    def test_every_group_of_values_has_a_page(self) -> None:
        self.assertEqual(settingspages.unplaced_groups(), [])

    def test_every_switchable_feature_has_a_page(self) -> None:
        self.assertEqual(settingspages.unplaced_flags(), [])

    def test_cards_name_only_existing_flags_and_groups(self) -> None:
        for section in settingspages.SECTIONS:
            for card in section.cards:
                for key in card.flags:
                    self.assertIsNotNone(features.resolve(key), (section.key, key))
                for group in card.groups:
                    self.assertIn(group, secrets.GROUPS, (section.key, group))

    def test_no_value_is_defined_twice(self) -> None:
        keys = [item.key for item in secrets.SETTINGS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_what_must_not_be_switchable_is_absent(self) -> None:
        for key in ("PROMO_IN_ALERTS", "SUPERADMIN_ID", "SECRET_KEY", "DATABASE_URL",
                    "DB_PASSWORD", "ENV_FILE", "AI_PROVIDER"):
            self.assertNotIn(key, secrets.BY_KEY, key)
        listed = " ".join(name for name, _ in settingspages.NOT_FROM_PANEL)
        self.assertIn("PROMO_IN_ALERTS", listed)
        self.assertIn("SUPERADMIN_ID", listed)

    def test_previously_env_only_values_are_now_settings(self) -> None:
        for key in ("MAX_BOT_TOKEN", "MAX_MODE", "BOT_TOKEN", "POLL_INTERVAL", "AI_RPM",
                    "FILEDROP_MAX_MB", "LINKCHECK_TIMEOUT", "LOG_LEVEL", "WEB_PORT",
                    "RUSTDESK_PUBLIC_HOST", "PROMO_URL", "MEDIA_MIN_ROLE"):
            self.assertIn(key, secrets.BY_KEY, key)

    def test_old_values_moved_to_their_platform(self) -> None:
        self.assertEqual(secrets.BY_KEY["VK_BOT_TOKEN"].group, "ВКонтакте")
        self.assertEqual(secrets.BY_KEY["VK_SERVICE_TOKEN"].group, "ВКонтакте")
        self.assertEqual(secrets.BY_KEY["OK_ACCESS_TOKEN"].group, "Одноклассники")
        self.assertEqual(secrets.BY_KEY["SAFE_BROWSING_API_KEY"].group, "Проверка ссылок")


class DefaultsMatchCodeTests(unittest.TestCase):
    def test_declared_defaults_equal_the_real_ones(self) -> None:
        """Подсказка «по умолчанию» не должна врать: сверяем с config.py."""
        if any(os.getenv(key) for key in ("POLL_INTERVAL", "AI_RPM", "WEB_PORT")):
            self.skipTest("в окружении заданы свои значения")
        checked = 0
        for item in secrets.SETTINGS:
            if item.kind != "int" or not item.default:
                continue
            real = getattr(config, item.key, None)
            if isinstance(real, bool) or not isinstance(real, int):
                continue
            self.assertEqual(real, int(item.default), item.key)
            checked += 1
        self.assertGreater(checked, 15)

    def test_int_limits_are_sane(self) -> None:
        for item in secrets.SETTINGS:
            if item.kind == "int" and item.default:
                number = int(item.default)
                if item.low is not None:
                    self.assertGreaterEqual(number, item.low, item.key)
                if item.high is not None:
                    self.assertLessEqual(number, item.high, item.key)


class ValueCheckTests(unittest.TestCase):
    def check(self, key: str, value: str) -> str:
        setting = secrets.BY_KEY[key]
        return secrets.check_value(setting, secrets.normalize_value(setting, value))

    def test_empty_is_always_allowed(self) -> None:
        for key in ("POLL_INTERVAL", "MAX_MODE", "WEB_HTTPS", "PROMO_URL", "DISCORD_SUMMARY_TIME"):
            self.assertEqual(self.check(key, ""), "", key)

    def test_int_bounds(self) -> None:
        self.assertEqual(self.check("POLL_INTERVAL", "300"), "")
        self.assertIn("60", self.check("POLL_INTERVAL", "10"))
        self.assertTrue(self.check("POLL_INTERVAL", "быстро"))
        self.assertTrue(self.check("POLL_INTERVAL", "-5"))
        self.assertIn("65535", self.check("WEB_PORT", "70000"))

    def test_bool_words_are_normalised(self) -> None:
        setting = secrets.BY_KEY["WEB_HTTPS"]
        for raw, want in (("да", "1"), ("Yes", "1"), ("true", "1"), ("off", "0"), ("нет", "0")):
            self.assertEqual(secrets.normalize_value(setting, raw), want, raw)
        self.assertTrue(self.check("WEB_HTTPS", "возможно"))

    def test_choice_is_canonical_and_closed(self) -> None:
        setting = secrets.BY_KEY["LOG_LEVEL"]
        self.assertEqual(secrets.normalize_value(setting, "debug"), "DEBUG")
        self.assertEqual(self.check("LOG_LEVEL", "debug"), "")
        self.assertIn("DEBUG", self.check("LOG_LEVEL", "шумно"))
        self.assertEqual(self.check("MAX_MODE", "Webhook"), "")
        self.assertTrue(self.check("MEDIA_MIN_ROLE", "owner"))

    def test_url_and_time(self) -> None:
        self.assertEqual(self.check("PROMO_URL", "https://t.me/x"), "")
        self.assertTrue(self.check("PROMO_URL", "t.me/x"))
        self.assertTrue(self.check("MAX_API_URL", "ftp://x"))
        self.assertEqual(self.check("DISCORD_SUMMARY_TIME", "8:05"), "")
        self.assertEqual(secrets.normalize_value(secrets.BY_KEY["DISCORD_SUMMARY_TIME"], "8:05"), "08:05")
        self.assertTrue(self.check("DISCORD_SUMMARY_TIME", "25:00"))


class PendingRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        secrets.PENDING_RESTART.clear()
        self.addCleanup(secrets.PENDING_RESTART.clear)

    def write(self, values: dict[str, str]) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            open(path, "w", encoding="utf-8").close()
            with mock.patch.object(secrets, "ENV_PATH", path), \
                    mock.patch("radar.backup.backup_env", lambda: None), \
                    mock.patch.dict(os.environ, {}, clear=False):
                ok = secrets.write_many(values)
                for key in values:
                    os.environ.pop(key, None)
            return ok

    def test_changed_startup_value_is_remembered(self) -> None:
        self.assertTrue(self.write({"POLL_INTERVAL": "300", "GEMINI_MODEL": "x"}))
        self.assertIn("POLL_INTERVAL", secrets.PENDING_RESTART)

    def test_hot_value_is_not(self) -> None:
        self.assertFalse(secrets.BY_KEY["MUSIC_DIR"].restart)
        self.write({"MUSIC_DIR": "/music"})
        self.assertNotIn("MUSIC_DIR", secrets.PENDING_RESTART)

    def test_unchanged_value_is_not(self) -> None:
        with mock.patch.dict(os.environ, {"POLL_INTERVAL": "300"}):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, ".env")
                open(path, "w", encoding="utf-8").close()
                with mock.patch.object(secrets, "ENV_PATH", path), \
                        mock.patch("radar.backup.backup_env", lambda: None):
                    secrets.write_many({"POLL_INTERVAL": "300"})
        self.assertNotIn("POLL_INTERVAL", secrets.PENDING_RESTART)


class PageTests(unittest.TestCase):
    def setUp(self) -> None:
        secrets.PENDING_RESTART.clear()
        self.addCleanup(secrets.PENDING_RESTART.clear)
        self.env = {"MAX_BOT_TOKEN": "SECRET-MAX-TOKEN-123", "MAX_MODE": "webhook"}
        for patch in (mock.patch.object(secrets, "get", lambda key: self.env.get(key, "")),):
            patch.start()
            self.addCleanup(patch.stop)

    def test_platform_page_groups_flags_and_values_by_topic(self) -> None:
        page = settingspages.section_body(settingspages.BY_PATH["/settings/platforms"], "CSRF")
        for needle in ("<h3>MAX</h3>", "<h3>Discord</h3>", "<h3>ВКонтакте</h3>",
                       'name="key" value="platform_max"', 'name="key" value="platform_discord"',
                       "MAX_MODE", "DISCORD_BOT_TOKEN", "VK_BOT_TOKEN"):
            self.assertIn(needle, page)
        self.assertIn('name="back" value="/settings/platforms"', page)
        self.assertNotIn("SECRET-MAX-TOKEN-123", page, "секрет на странице не показывается")

    def test_widgets_follow_the_kind(self) -> None:
        page = settingspages.section_body(settingspages.BY_PATH["/settings/platforms"], "CSRF")
        self.assertIn('<option value="webhook" selected>webhook</option>', page)
        alerts = settingspages.section_body(settingspages.BY_PATH["/settings/alerts"], "CSRF")
        self.assertIn('type="number" name="value"', alerts)
        self.assertIn("по умолчанию: 180", alerts)
        system = settingspages.section_body(settingspages.BY_PATH["/settings/system"], "CSRF")
        self.assertIn("включено</option>", system)        # WEB_HTTPS — переключатель

    def test_every_section_renders(self) -> None:
        for section in settingspages.SECTIONS:
            page = settingspages.section_body(section, "CSRF")
            self.assertIn("<h3>", page, section.key)
        overview = settingspages.overview_body("CSRF")
        for section in settingspages.SECTIONS:
            self.assertIn(section.path, overview)
        self.assertIn("PROMO_IN_ALERTS", overview)

    def test_restart_banner_only_when_needed(self) -> None:
        self.assertNotIn("ждёт перезапуска", settingspages.overview_body("CSRF"))
        secrets.PENDING_RESTART.add("POLL_INTERVAL")
        with_button = settingspages.overview_body("CSRF", can_restart=True)
        self.assertIn("ждёт перезапуска", with_button)
        self.assertIn('action="/settings/restart"', with_button)
        without = settingspages.overview_body("CSRF", can_restart=False)
        self.assertNotIn('action="/settings/restart"', without)
        self.assertIn("docker compose restart", without)

    def test_row_marks_pending_value(self) -> None:
        secrets.PENDING_RESTART.add("POLL_INTERVAL")
        row = panel._setting_row(secrets.BY_KEY["POLL_INTERVAL"], "CSRF", "/settings/alerts")
        self.assertIn("изменено — ждёт перезапуска", row)


class NavigationTests(unittest.TestCase):
    def test_owner_gets_settings_group(self) -> None:
        groups = {key: items for _, _, key, items in panel._nav_groups("superadmin")}
        paths = [item[0] for item in groups["settings"]]
        self.assertEqual(paths[0], "/settings")
        for section in settingspages.SECTIONS:
            self.assertIn(section.path, paths)

    def test_others_do_not(self) -> None:
        for role in ("admin", "moderator", "user"):
            flat = [item[0] for item in panel._links_for(role)]
            self.assertFalse(any(path.startswith("/settings") for path in flat), role)

    def test_handlers_are_guarded(self) -> None:
        with open(os.path.join(ROOT, "radar", "web", "panel.py"), encoding="utf-8") as handle:
            source = handle.read()
        index = source.index("async def settings_restart")
        self.assertIn('_guarded_form(request, "superadmin")', source[index:index + 300])
        index = source.index("async def settings_overview")
        self.assertIn("@owner_only", source[index - 40:index])
        self.assertIn("def _settings_page", source)
        self.assertIn("@owner_only", source[source.index("def _settings_page"):][:120])


if __name__ == "__main__":
    unittest.main()
