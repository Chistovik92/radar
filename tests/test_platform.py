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


if __name__ == "__main__":
    unittest.main(verbosity=2)
