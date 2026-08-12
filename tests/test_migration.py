#!/usr/bin/env python3
"""Совместимость с базой продакшен-версии 2.6.0.

Внешние зависимости подменяются заглушками из tools/stubcheck.py,
поэтому тест работает без установленных aiogram/aiohttp/google-genai.
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import storage  # noqa: E402

# Точный формат db.json из install.sh версии 2.6.0
LEGACY = {
    "users": {
        "111": {
            "role": "superadmin",
            "locs": [{"name": "Чапаева, 12", "lat": 51.533, "lon": 46.034}],
            "settings": {"jkh": True, "bpla": True, "mchs": True, "whitelist": True},
            "weather_mode": "interval",
            "weather_interval": 60,
            "weather_time": "08:00",
            "last_weather": 1730000000,
            "last_fixed_date": "",
        },
        "222": {
            "role": "user",
            "locs": ["Рахова, 3"],  # формат ещё до 2.0 — строка
            "settings": {"jkh": True},
        },
    },
    "channels": ["saratov_24", "mchs_saratov"],
    "pending": ["someChannel"],
}


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.data = storage.migrate({k: v.copy() if isinstance(v, dict) else list(v)
                                     for k, v in LEGACY.items()})

    def test_users_preserved(self):
        self.assertIn("111", self.data["users"])
        self.assertIn("222", self.data["users"])

    def test_locations_converted(self):
        location = self.data["users"]["111"]["locs"][0]
        self.assertEqual(location["name"], "Чапаева, 12")
        self.assertEqual(location["lat"], 51.533)
        self.assertIn("id", location)
        for key in ("city", "district", "region", "street", "house"):
            self.assertIn(key, location)

    def test_string_location_converted(self):
        location = self.data["users"]["222"]["locs"][0]
        self.assertEqual(location["name"], "Рахова, 3")
        self.assertEqual(location["lat"], 0.0)

    def test_missing_settings_filled(self):
        settings = self.data["users"]["222"]["settings"]
        for key in ("jkh", "bpla", "mchs", "whitelist"):
            self.assertIn(key, settings)

    def test_weather_fields_kept(self):
        user = self.data["users"]["111"]
        self.assertEqual(user["weather_interval"], 60)
        self.assertEqual(user["last_weather"], 1730000000)

    def test_defaults_added(self):
        self.assertIn("rss", self.data)
        self.assertIn("meta", self.data)
        self.assertEqual(self.data["meta"]["schema"], 3)
        # Существующие каналы сохраняются, федеральные добавляются всегда.
        self.assertIn("saratov_24", self.data["channels"])
        self.assertIn("mchs_official", self.data["channels"])
        self.assertEqual(self.data["pending"], ["someChannel"])

    def test_city_preset_applied(self):
        """Набор источников города подключается по SOURCE_CITIES."""
        from radar import config

        saved = config.SOURCE_CITIES
        config.SOURCE_CITIES = ["kazan"]
        try:
            data = storage.migrate({})
        finally:
            config.SOURCE_CITIES = saved
        self.assertIn("vodokanalkzn", data["channels"])
        self.assertIn("mchs_official", data["channels"])

    def test_migration_is_idempotent(self):
        once = storage.migrate(self.data)
        twice = storage.migrate(once)
        self.assertEqual(len(twice["users"]["111"]["locs"]), 1)
        self.assertEqual(twice["channels"], once["channels"])

    def test_empty_database(self):
        fresh = storage.migrate({})
        self.assertIn("users", fresh)
        self.assertIn("channels", fresh)
        self.assertTrue(fresh["channels"])

    def test_broken_types_repaired(self):
        broken = storage.migrate({"users": [], "channels": "x", "pending": None})
        self.assertIsInstance(broken["users"], dict)
        self.assertIsInstance(broken["channels"], list)
        self.assertIsInstance(broken["pending"], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
