#!/usr/bin/env python3
"""Мультиплатформенная идентификация, переключатели возможностей, абстракция транспорта."""

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

from radar import features, identity  # noqa: E402
from radar.platforms import Button, EventKind, InboundEvent, OutboundMessage  # noqa: E402


class TestIdentity(unittest.TestCase):
    def test_telegram_key_stays_bare(self):
        """Совместимость с 3.x: обработчики передают голый Telegram ID."""
        self.assertEqual(identity.make("telegram", 12345).key, "12345")

    def test_max_key_is_prefixed(self):
        self.assertEqual(identity.make("max", 999).key, "max:999")

    def test_parse_bare_is_telegram(self):
        parsed = identity.parse("12345")
        self.assertEqual(parsed.platform, "telegram")
        self.assertEqual(parsed.external_id, "12345")

    def test_parse_prefixed(self):
        parsed = identity.parse("max:777")
        self.assertEqual(parsed.platform, "max")
        self.assertEqual(parsed.external_id, "777")

    def test_roundtrip(self):
        for platform, external in (("telegram", "1"), ("max", "2")):
            key = identity.key_of(platform, external)
            parsed = identity.parse(key)
            self.assertEqual((parsed.platform, parsed.external_id), (platform, external))

    def test_same_number_different_platforms(self):
        """Один и тот же номер в разных мессенджерах — разные пользователи."""
        self.assertNotEqual(identity.key_of("telegram", 100), identity.key_of("max", 100))

    def test_unknown_platform_falls_back(self):
        self.assertEqual(identity.make("icq", 5).platform, "telegram")

    def test_colon_in_unknown_prefix_not_split(self):
        parsed = identity.parse("weird:123")
        self.assertEqual(parsed.platform, "telegram")
        self.assertEqual(parsed.external_id, "weird:123")

    def test_titles(self):
        self.assertEqual(identity.make("max", 1).title, "MAX")
        self.assertEqual(identity.make("telegram", 1).title, "Telegram")


class TestFeatures(unittest.TestCase):
    def setUp(self):
        features.apply({})

    def tearDown(self):
        features.apply({})

    def test_defaults_respected(self):
        self.assertTrue(features.enabled("alerts"))
        self.assertFalse(features.enabled("platform_max"))

    def test_override_applies(self):
        features.apply({"source_vk": True})
        self.assertTrue(features.enabled("source_vk"))

    def test_locked_cannot_be_disabled(self):
        features.apply({"alerts": False})
        self.assertTrue(features.enabled("alerts"))
        self.assertIsNone(features.set_local("alerts", False))

    def test_unknown_key_is_off(self):
        self.assertFalse(features.enabled("no_such_flag"))

    def test_alias_resolves(self):
        self.assertIsNotNone(features.resolve("promo"))
        self.assertEqual(features.resolve("promo").key, "partners")

    def test_set_local_changes_state(self):
        features.set_local("weather_image", True)
        self.assertTrue(features.enabled("weather_image"))
        features.set_local("weather_image", False)
        self.assertFalse(features.enabled("weather_image"))

    def test_snapshot_covers_all_flags(self):
        self.assertEqual(len(features.snapshot()), len(features.FLAGS))

    def test_groups_cover_all_flags(self):
        grouped = features.by_group()
        total = sum(len(items) for items in grouped.values())
        self.assertEqual(total, len(features.FLAGS))

    def test_keys_unique(self):
        keys = [flag.key for flag in features.FLAGS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_planned_flags_off_by_default(self):
        """Возможности будущих версий не должны включаться сами."""
        for key in ("source_vk", "weather_image", "quiet_hours",
                    "platform_max", "partners", "promo_codes",
                    "web_panel", "egress_proxy", "maintenance",
                    "digest", "digest_paid", "digest_suggestions"):
            self.assertFalse(features.enabled(key), key)


class TestPlatformAbstraction(unittest.TestCase):
    def test_inbound_event_key(self):
        event = InboundEvent(
            platform="max",
            identity=identity.make("max", 42),
            chat_id="42",
            kind=EventKind.COMMAND,
            command="start",
        )
        self.assertEqual(event.key, "max:42")

    def test_button_kinds(self):
        self.assertTrue(Button(text="Сайт", url="https://example.ru").is_link)
        self.assertFalse(Button(text="Меню", payload="menu:main").is_link)

    def test_outbound_defaults(self):
        message = OutboundMessage(text="привет")
        self.assertEqual(message.keyboard, [])
        self.assertTrue(message.disable_preview)
        self.assertFalse(message.silent)

    def test_event_kinds_present(self):
        for name in ("MESSAGE", "COMMAND", "CALLBACK", "LOCATION", "DOCUMENT"):
            self.assertTrue(hasattr(EventKind, name))

    def test_transport_protocol_methods(self):
        from radar.platforms.base import Transport

        for method in ("start", "stop", "send", "set_commands", "render"):
            self.assertTrue(hasattr(Transport, method), method)


class TestDatabaseErrors(unittest.TestCase):
    """Отличие «пароль не тот» от «база ещё не поднялась»."""

    def setUp(self):
        from radar.db import engine

        self.engine = engine

    def test_auth_errors_detected(self):
        samples = [
            'InvalidPasswordError: password authentication failed for user "radar"',
            "InvalidAuthorizationSpecificationError: role does not exist",
            "InvalidCatalogNameError: database \"radar\" does not exist",
        ]
        for text in samples:
            self.assertTrue(self.engine._is_auth_error(Exception(text)), text)

    def test_transient_errors_not_auth(self):
        samples = [
            "ConnectionRefusedError: [Errno 111] Connect call failed",
            "OSError: [Errno -2] Name or service not known",
            "TimeoutError: connection timed out",
        ]
        for text in samples:
            self.assertFalse(self.engine._is_auth_error(Exception(text)), text)

    def test_authentication_error_is_runtime_error(self):
        self.assertTrue(issubclass(self.engine.AuthenticationError, RuntimeError))


class TestLogStore(unittest.TestCase):
    """Перечисление, архивация и очистка журналов."""

    def setUp(self):
        import tempfile

        from radar import config, logs

        self.logs = logs
        self.config = config
        self.tmp = tempfile.mkdtemp()
        self.saved_dir = config.LOG_DIR
        config.LOG_DIR = self.tmp

        for name, content in (
            ("bot.log", "строка журнала бота\n" * 5),
            ("bot.log.1", "старый журнал\n"),
            ("installer_log_20260813-120000.txt", "установка\n"),
            ("installer_log_20260813-130000.txt", "ещё установка\n"),
            ("posторонний.txt", "не журнал\n"),
        ):
            with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as handle:
                handle.write(content)

    def tearDown(self):
        import shutil

        self.config.LOG_DIR = self.saved_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_known_files_collected(self):
        names = {item.name for item in self.logs.collect()}
        self.assertIn("bot.log", names)
        self.assertIn("installer_log_20260813-120000.txt", names)
        self.assertNotIn("posторонний.txt", names)

    def test_classified_by_kind(self):
        grouped = self.logs.by_kind()
        self.assertEqual(len(grouped["installer"]), 2)
        self.assertEqual(len(grouped["bot"]), 2)

    def test_find_rejects_traversal(self):
        self.assertIsNone(self.logs.find("../../etc/passwd"))
        self.assertIsNone(self.logs.find(".hidden"))
        self.assertIsNotNone(self.logs.find("bot.log"))

    def test_tail_returns_last_lines(self):
        item = self.logs.find("bot.log")
        self.assertIn("строка журнала бота", self.logs.tail(item, 2))

    def test_archive_contains_manifest(self):
        import io
        import tarfile

        payload, filename, count = self.logs.archive()
        self.assertTrue(filename.startswith("radar-logs-"))
        self.assertEqual(count, 4)
        with tarfile.open(fileobj=io.BytesIO(payload)) as bundle:
            names = bundle.getnames()
        self.assertIn("manifest.txt", names)
        self.assertTrue(any("installer/" in name for name in names))

    def test_archive_filtered_by_kind(self):
        _payload, _name, count = self.logs.archive({"installer"})
        self.assertEqual(count, 2)

    def test_purge_keeps_current_bot_log(self):
        removed, _freed = self.logs.purge()
        self.assertEqual(removed, 3)
        self.assertIsNotNone(self.logs.find("bot.log"))

    def test_purge_by_kind(self):
        removed, _freed = self.logs.purge({"installer"})
        self.assertEqual(removed, 2)
        self.assertEqual(self.logs.by_kind().get("installer"), None)

    def test_empty_directory_gives_no_archive(self):
        self.logs.purge(keep_current=False)
        self.assertIsNone(self.logs.archive())


class TestSourceCheck(unittest.TestCase):
    """Разбор ответов при проверке источников."""

    def setUp(self):
        from radar import sourcecheck

        self.sc = sourcecheck

    def test_title_formats(self):
        tg = self.sc.SourceStatus(kind="tg", ref="saratov_24")
        rss = self.sc.SourceStatus(kind="rss", ref="https://sarbc.ru/rss")
        self.assertEqual(tg.title, "@saratov_24")
        self.assertEqual(rss.title, "sarbc.ru")

    def test_stale_detection(self):
        from datetime import datetime, timedelta, timezone

        fresh = datetime.now(timezone.utc) - timedelta(days=1)
        old = datetime.now(timezone.utc) - timedelta(days=self.sc.STALE_DAYS + 5)
        self.assertFalse(self.sc._is_stale(fresh))
        self.assertTrue(self.sc._is_stale(old))
        self.assertFalse(self.sc._is_stale(None))

    def test_age_wording(self):
        from datetime import datetime, timedelta, timezone

        item = self.sc.SourceStatus(kind="tg", ref="x")
        self.assertEqual(item.age, "—")
        item.last_post = datetime.now(timezone.utc) - timedelta(days=1)
        self.assertEqual(item.age, "вчера")
        item.last_post = datetime.now(timezone.utc) - timedelta(days=5)
        self.assertIn("5 дн", item.age)

    def test_date_parsing(self):
        self.assertIsNotNone(self.sc._parse_date("Wed, 13 Aug 2026 10:00:00 +0300"))
        self.assertIsNotNone(self.sc._parse_date("2026-08-13T10:00:00Z"))
        self.assertIsNone(self.sc._parse_date("не дата"))
        self.assertIsNone(self.sc._parse_date(""))

    def test_report_buckets(self):
        report = self.sc.CheckReport(statuses=[
            self.sc.SourceStatus(kind="tg", ref="a", state=self.sc.ALIVE),
            self.sc.SourceStatus(kind="tg", ref="b", state=self.sc.STALE),
            self.sc.SourceStatus(kind="rss", ref="https://c.ru/x", state=self.sc.DEAD,
                                 note="HTTP 404"),
        ])
        self.assertEqual(len(report.alive), 1)
        self.assertEqual(len(report.stale), 1)
        self.assertEqual(len(report.dead), 1)
        self.assertEqual(report.total, 3)

    def test_render_lists_problems(self):
        report = self.sc.CheckReport(statuses=[
            self.sc.SourceStatus(kind="tg", ref="dead_one", state=self.sc.DEAD,
                                 note="канал не найден"),
        ])
        text = self.sc.render(report)
        self.assertIn("@dead_one", text)
        self.assertIn("канал не найден", text)

    def test_render_when_all_good(self):
        report = self.sc.CheckReport(statuses=[
            self.sc.SourceStatus(kind="tg", ref="ok", state=self.sc.ALIVE),
        ])
        self.assertIn("отвечают", self.sc.render(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
