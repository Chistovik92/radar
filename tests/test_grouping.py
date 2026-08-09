#!/usr/bin/env python3
"""Проверка правил группировки оповещений."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.matching import Analysis, plan_alerts  # noqa: E402

ALL_ON = {"jkh": True, "bpla": True, "mchs": True, "whitelist": True}


def loc(name, lat, lon, city="Саратов", street="", house=""):
    return {
        "id": name, "name": name, "lat": lat, "lon": lon,
        "city": city, "district": "", "region": "Саратовская область",
        "street": street, "house": house,
    }


def military(city="Саратов"):
    return Analysis(
        relevant=True, categories=["bpla"], severity="critical", scope="city",
        city=city, summary="Опасность атаки БПЛА", source="mchs_saratov",
    )


def utility(street, houses, city="Саратов"):
    return Analysis(
        relevant=True, categories=["jkh"], severity="warning", scope="street",
        city=city, streets=[{"street": street, "houses": houses}],
        summary="Отключение холодной воды", source="saratovvodokanal",
    )


class TestGrouping(unittest.TestCase):
    def test_military_one_message_per_city(self):
        """Локации в одном городе → одно военное сообщение со списком локаций."""
        locations = [
            loc("Чапаева, 12", 51.5330, 46.0340),
            loc("Рахова, 3", 51.5200, 46.0100),      # тот же город, >1 км
            loc("Энгельс, Ленина 1", 51.4800, 46.1200, city="Энгельс"),
        ]
        messages = plan_alerts(locations, ALL_ON, [military("Саратов")])
        city_messages = [text for kind, text in messages if kind == "city"]
        self.assertEqual(len(city_messages), 1)
        self.assertIn("Чапаева, 12", city_messages[0])
        self.assertIn("Рахова, 3", city_messages[0])
        self.assertNotIn("Энгельс, Ленина 1", city_messages[0])

    def test_military_two_cities_two_messages(self):
        locations = [
            loc("Чапаева, 12", 51.5330, 46.0340),
            loc("Ленина, 1", 51.4800, 46.1200, city="Энгельс"),
        ]
        messages = plan_alerts(
            locations, ALL_ON, [military("Саратов"), military("Энгельс")]
        )
        self.assertEqual(len([1 for kind, _ in messages if kind == "city"]), 2)

    def test_utility_separate_from_military(self):
        """ЖКХ и военные — разные сообщения."""
        locations = [loc("Чапаева, 12", 51.5330, 46.0340, street="улица Чапаева", house="12")]
        messages = plan_alerts(
            locations, ALL_ON, [military(), utility("улица Чапаева", ["12"])]
        )
        kinds = sorted(kind for kind, _ in messages)
        self.assertEqual(kinds, ["city", "utility"])

    def test_utility_addressed_only(self):
        """ЖКХ приходит только на совпавший адрес, соседняя улица не получает."""
        locations = [
            loc("Чапаева, 12", 51.5330, 46.0340, street="улица Чапаева", house="12"),
            loc("Рахова, 3", 51.5200, 46.0100, street="улица Рахова", house="3"),
        ]
        messages = plan_alerts(locations, ALL_ON, [utility("улица Чапаева", ["12"])])
        self.assertEqual(len(messages), 1)
        self.assertIn("Чапаева, 12", messages[0][1])
        self.assertNotIn("Рахова, 3", messages[0][1])

    def test_near_locations_share_one_message(self):
        """Локации в пределах 1 км → одно сообщение на группу."""
        locations = [
            loc("Чапаева, 12", 51.5330, 46.0340, street="улица Чапаева", house="12"),
            loc("Чапаева, 14", 51.5332, 46.0344, street="улица Чапаева", house="14"),
        ]
        messages = plan_alerts(locations, ALL_ON, [utility("улица Чапаева", ["12", "14"])])
        self.assertEqual(len(messages), 1)
        text = messages[0][1]
        self.assertIn("Чапаева, 12", text)
        self.assertIn("Чапаева, 14", text)
        self.assertIn("в пределах 1 км", text)

    def test_far_locations_get_separate_messages(self):
        """Локации дальше 1 км по одной улице → разные сообщения."""
        locations = [
            loc("Чапаева, 12", 51.5330, 46.0340, street="улица Чапаева", house="12"),
            loc("Чапаева, 120", 51.5600, 46.0700, street="улица Чапаева", house="120"),
        ]
        messages = plan_alerts(locations, ALL_ON, [utility("улица Чапаева", [])])
        self.assertEqual(len(messages), 2)
        for _kind, text in messages:
            self.assertNotIn("в пределах 1 км", text)

    def test_disabled_category_filtered(self):
        locations = [loc("Чапаева, 12", 51.5330, 46.0340, street="улица Чапаева", house="12")]
        settings = dict(ALL_ON, bpla=False)
        messages = plan_alerts(locations, settings, [military(), utility("улица Чапаева", ["12"])])
        self.assertEqual([kind for kind, _ in messages], ["utility"])

    def test_no_locations_no_messages(self):
        self.assertEqual(plan_alerts([], ALL_ON, [military()]), [])

    def test_irrelevant_analyses_ignored(self):
        locations = [loc("Чапаева, 12", 51.5330, 46.0340)]
        self.assertEqual(plan_alerts(locations, ALL_ON, [Analysis(relevant=False)]), [])

    def test_header_lists_matched_locations(self):
        locations = [
            loc("Чапаева, 12", 51.5330, 46.0340),
            loc("Рахова, 3", 51.5200, 46.0100),
        ]
        messages = plan_alerts(locations, ALL_ON, [military()])
        self.assertTrue(
            messages[0][1].splitlines()[2].startswith("📍 <b>Совпавшие локации:</b>")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
