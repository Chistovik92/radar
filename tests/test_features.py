#!/usr/bin/env python3
"""Обмен источниками, оформление погоды и предупреждение о «белых списках»."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import exporting, weather  # noqa: E402
from radar.matching import (  # noqa: E402
    WHITELIST_NOTICE,
    Analysis,
    build_city_alert,
    cluster_title,
    plan_alerts,
)

ALL_ON = {"jkh": True, "bpla": True, "mchs": True, "whitelist": True}

def loc(name, lat=51.533, lon=46.034, city="Саратов"):
    return {"id": name, "name": name, "lat": lat, "lon": lon, "city": city,
            "district": "", "region": "", "street": "", "house": ""}


def military():
    return Analysis(relevant=True, categories=["bpla"], severity="critical",
                    scope="city", city="Саратов", summary="Опасность атаки БПЛА",
                    source="mchs_saratov")


# ==========================================================================
#  Экспорт и импорт источников
# ==========================================================================

class TestExport(unittest.TestCase):
    def test_roundtrip(self):
        payload = exporting.export_bundle(
            ["saratov_24", "mchs_saratov"], ["https://example.ru/rss"], ["newone"], "3.3.0"
        )
        bundle = exporting.parse_bundle(payload)
        self.assertEqual(bundle.channels, ["mchs_saratov", "saratov_24"])
        self.assertEqual(bundle.rss, ["https://example.ru/rss"])
        self.assertEqual(bundle.pending, ["newone"])

    def test_file_is_valid_json_with_metadata(self):
        data = json.loads(exporting.export_bundle(["a_channel"], [], [], "3.3.0"))
        self.assertEqual(data["format"], "radar-sources")
        self.assertEqual(data["schema"], exporting.SCHEMA)
        self.assertIn("exported_at", data)
        self.assertEqual(data["generator"], "radar/3.3.0")

    def test_filename_has_version(self):
        self.assertTrue(exporting.export_filename("3.3.0").startswith("radar-sources-3.3.0-"))
        self.assertTrue(exporting.export_filename("3.3.0").endswith(".json"))

    def test_future_schema_rejected(self):
        payload = json.dumps({"format": "radar-sources", "schema": 99, "channels": ["x_chan"]})
        with self.assertRaises(exporting.ImportError_) as ctx:
            exporting.parse_bundle(payload)
        self.assertIn("обновите бота", str(ctx.exception))

    def test_unknown_fields_ignored(self):
        """Файл из будущей версии с той же схемой должен читаться."""
        payload = json.dumps({
            "format": "radar-sources", "schema": 1,
            "channels": ["saratov_24"], "rss": [],
            "telegram_groups": ["что-то новое"], "weights": {"saratov_24": 5},
        })
        bundle = exporting.parse_bundle(payload)
        self.assertEqual(bundle.channels, ["saratov_24"])

    def test_legacy_db_json_accepted(self):
        """db.json из версий 2.x — тоже валидный источник."""
        legacy = json.dumps({
            "users": {"1": {"role": "superadmin", "locs": []}},
            "channels": ["saratov_24", "tplus_saratov"],
            "pending": ["someone"],
        })
        bundle = exporting.parse_bundle(legacy)
        self.assertEqual(bundle.channels, ["saratov_24", "tplus_saratov"])

    def test_plain_text_list(self):
        bundle = exporting.parse_bundle(
            "saratov_24, @mchs_saratov\nhttps://t.me/saratovzhkh\nhttps://sm.ru/rss"
        )
        self.assertIn("saratov_24", bundle.channels)
        self.assertIn("mchs_saratov", bundle.channels)
        self.assertIn("saratovzhkh", bundle.channels)
        self.assertIn("https://sm.ru/rss", bundle.rss)

    def test_bad_entries_reported(self):
        payload = json.dumps({"channels": ["ok_channel", "!!!", "a"], "rss": ["не ссылка"]})
        bundle = exporting.parse_bundle(payload)
        self.assertEqual(bundle.channels, ["ok_channel"])
        self.assertTrue(bundle.warnings)

    def test_empty_file_rejected(self):
        with self.assertRaises(exporting.ImportError_):
            exporting.parse_bundle("")

    def test_no_sources_rejected(self):
        with self.assertRaises(exporting.ImportError_):
            exporting.parse_bundle(json.dumps({"format": "radar-sources", "schema": 1}))

    def test_merge_adds_without_duplicates(self):
        channels = ["saratov_24"]
        feeds: list[str] = []
        bundle = exporting.Bundle(channels=["saratov_24", "new_channel"],
                                  rss=["https://a.ru/rss"])
        added_channels, added_rss = exporting.merge(bundle, channels, feeds)
        self.assertEqual((added_channels, added_rss), (1, 1))
        self.assertEqual(channels, ["saratov_24", "new_channel"])

    def test_merge_replace_mode(self):
        channels = ["old_channel"]
        feeds: list[str] = []
        bundle = exporting.Bundle(channels=["new_channel"])
        exporting.merge(bundle, channels, feeds, replace=True)
        self.assertEqual(channels, ["new_channel"])


# ==========================================================================
#  Белые списки
# ==========================================================================

class TestWhitelistNotice(unittest.TestCase):
    def test_notice_added_to_military_alert(self):
        messages = plan_alerts([loc("Чапаева, 12")], ALL_ON, [military()])
        self.assertIn("белые списки", messages[0][1].lower())

    def test_notice_hidden_when_disabled(self):
        settings = dict(ALL_ON, whitelist=False)
        messages = plan_alerts([loc("Чапаева, 12")], settings, [military()])
        self.assertNotIn("белые списки", messages[0][1].lower())

    def test_notice_absent_for_utility(self):
        utility = Analysis(relevant=True, categories=["jkh"], scope="city",
                           city="Саратов", summary="Нет воды", source="vk")
        messages = plan_alerts([loc("Чапаева, 12")], ALL_ON, [utility])
        self.assertNotIn("белые списки", messages[0][1].lower())

    def test_notice_mentions_alternatives(self):
        self.assertIn("Wi-Fi", WHITELIST_NOTICE)
        self.assertIn("SMS", WHITELIST_NOTICE)

    def test_build_city_alert_flag(self):
        without = build_city_alert("Саратов", [loc("A")], [military()], whitelist_notice=False)
        with_notice = build_city_alert("Саратов", [loc("A")], [military()], whitelist_notice=True)
        self.assertLess(len(without), len(with_notice))


# ==========================================================================
#  Погода
# ==========================================================================

SAMPLE = {
    "current": {
        "time": "2026-08-10T14:00",
        "temperature_2m": 24.3, "apparent_temperature": 26.1,
        "relative_humidity_2m": 45, "wind_speed_10m": 3.2, "wind_gusts_10m": 8.4,
        "surface_pressure": 1006.0, "weather_code": 1, "is_day": 1,
    },
    "hourly": {
        "time": [f"2026-08-10T{hour:02d}:00" for hour in range(12, 24)],
        "temperature_2m": [22, 23, 24, 25, 26, 25, 24, 22, 20, 19, 18, 17],
        "precipitation_probability": [0, 0, 5, 10, 30, 60, 40, 10, 0, 0, 0, 0],
        "weather_code": [1, 1, 2, 2, 61, 63, 61, 2, 1, 0, 0, 0],
        "is_day": [1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0],
    },
    "daily": {
        "time": ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"],
        "temperature_2m_min": [17, 16, 15, 14],
        "temperature_2m_max": [28, 26, 24, 23],
        "precipitation_probability_max": [60, 20, 10, 0],
        "weather_code": [61, 2, 1, 0],
        "sunrise": ["2026-08-10T05:12", "2026-08-11T05:14",
                    "2026-08-12T05:15", "2026-08-13T05:17"],
        "sunset": ["2026-08-10T20:34", "2026-08-11T20:32",
                   "2026-08-12T20:30", "2026-08-13T20:28"],
    },
}


class TestWeatherParse(unittest.TestCase):
    def setUp(self):
        self.data = weather.parse(SAMPLE, hours=8)

    def test_current_values(self):
        self.assertTrue(self.data.ok)
        self.assertEqual(self.data.temp, 24.3)
        self.assertEqual(self.data.humidity, 45)
        self.assertTrue(self.data.is_day)

    def test_hourly_starts_from_now(self):
        """Прошедшие часы отбрасываются: сейчас 14:00."""
        self.assertEqual(self.data.hourly[0].label, "14ч")
        self.assertEqual(len(self.data.hourly), 8)

    def test_daily_labels(self):
        labels = [day.label for day in self.data.daily]
        self.assertEqual(labels[0], "сегодня")
        self.assertEqual(labels[1], "завтра")
        self.assertRegex(labels[2], r"^[а-я]{2} \d+$")

    def test_sun_times(self):
        self.assertEqual(self.data.sunrise, "05:12")
        self.assertEqual(self.data.sunset, "20:34")

    def test_missing_blocks_tolerated(self):
        light = weather.parse({"current": {"temperature_2m": 10}}, hours=8)
        self.assertTrue(light.ok)
        self.assertEqual(light.hourly, [])
        self.assertEqual(light.daily, [])


class TestWeatherRender(unittest.TestCase):
    def setUp(self):
        self.text = weather.render(weather.parse(SAMPLE, hours=8), "📍 <b>Чапаева, 12</b>")

    def test_has_title_and_temperature(self):
        self.assertIn("Чапаева, 12", self.text)
        self.assertIn("24°", self.text)

    def test_description_present(self):
        self.assertIn("малооблачно", self.text)

    def test_hourly_table_is_monospace(self):
        self.assertIn("<pre>", self.text)
        self.assertIn("14ч", self.text)

    def test_precipitation_shown(self):
        self.assertIn("60%", self.text)

    def test_daily_forecast_present(self):
        self.assertIn("сегодня", self.text)
        self.assertIn("завтра", self.text)

    def test_sun_line(self):
        self.assertIn("05:12", self.text)
        self.assertIn("20:34", self.text)

    def test_negative_temperature_formatting(self):
        frosty = weather.parse({"current": {"temperature_2m": -12.4, "weather_code": 75}})
        self.assertIn("-12°", weather.render(frosty))

    def test_error_rendered_plainly(self):
        broken = weather.Weather(ok=False, error="сбой получения погоды")
        self.assertTrue(weather.render(broken).startswith("⚠️"))

    def test_sparkline_length_matches_hours(self):
        bars = weather._sparkline([1.0, 5.0, 9.0])
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[0], "▁")
        self.assertEqual(bars[-1], "█")

    def test_sparkline_flat_series(self):
        self.assertEqual(weather._sparkline([7.0, 7.1, 7.0]), ["▄", "▄", "▄"])


class TestClusterTitle(unittest.TestCase):
    def test_single_location(self):
        self.assertNotIn("1 км", cluster_title([loc("Чапаева, 12")]))

    def test_group_marked(self):
        title = cluster_title([loc("Чапаева, 12"), loc("Чапаева, 14")])
        self.assertIn("1 км", title)
        self.assertIn("Чапаева, 14", title)


if __name__ == "__main__":
    unittest.main(verbosity=2)
