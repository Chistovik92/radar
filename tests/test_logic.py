#!/usr/bin/env python3
"""Тесты логики, не требующие сети и внешних пакетов.

Запуск:  python3 -m unittest discover -s tests -v
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import roles  # noqa: E402
from radar.matching import (  # noqa: E402
    Analysis,
    build_city_alert,
    build_utility_alert,
    heuristic_analysis,
    match_locations,
    matches_location,
)
from radar.textutils import (  # noqa: E402
    cluster_locations,
    haversine_m,
    house_in_range,
    md_to_html,
    normalize_house,
    normalize_street,
    same_city,
    split_text,
    street_matches,
)

def loc(name, lat=51.533, lon=46.034, **kw):
    base = {
        "id": name[:6], "name": name, "lat": lat, "lon": lon,
        "city": "Саратов", "district": "", "region": "Саратовская область",
        "street": "", "house": "",
    }
    base.update(kw)
    return base


class TestAddressNormalization(unittest.TestCase):
    def test_street_types_stripped(self):
        self.assertEqual(normalize_street("ул. Чапаева"), "чапаева")
        self.assertEqual(normalize_street("улица имени Чапаева В."), "чапаева")
        self.assertEqual(normalize_street("проспект 50 лет Октября"), "50 лет октября")

    def test_street_matching(self):
        self.assertTrue(street_matches("улица Чапаева", "ул. Чапаева"))
        self.assertTrue(street_matches("ул. Чапаева", "улица имени Чапаева В.И."))
        self.assertFalse(street_matches("улица Чапаева", "улица Рахова"))
        self.assertFalse(street_matches("", "улица Рахова"))

    def test_houses(self):
        self.assertEqual(normalize_house("д. 12/1"), "12/1")
        self.assertEqual(normalize_house("14А"), "14а")
        self.assertTrue(house_in_range("12", []))            # вся улица
        self.assertTrue(house_in_range("14", ["12", "14"]))
        self.assertTrue(house_in_range("16", ["12-20"]))
        self.assertFalse(house_in_range("22", ["12-20"]))
        self.assertFalse(house_in_range("13", ["12", "14"]))

    def test_city(self):
        self.assertTrue(same_city("Саратов", "г. Саратов"))
        self.assertFalse(same_city("Саратов", "Энгельс"))
        self.assertTrue(same_city("", "Энгельс"))  # нет данных — не отсекаем


class TestGeometry(unittest.TestCase):
    def test_haversine(self):
        distance = haversine_m(51.5330, 46.0340, 51.5330, 46.0484)
        self.assertTrue(900 < distance < 1100, distance)

    def test_cluster_within_1km(self):
        a = loc("A", 51.5330, 46.0340)
        b = loc("B", 51.5340, 46.0350)   # ~130 м
        c = loc("C", 51.6000, 46.2000)   # далеко
        clusters = cluster_locations([a, b, c], 1000)
        self.assertEqual(len(clusters), 2)
        self.assertEqual({x["name"] for x in clusters[0]}, {"A", "B"})

    def test_cluster_transitive(self):
        points = [loc(f"P{i}", 51.5330 + i * 0.005, 46.0340) for i in range(3)]
        # шаг ~555 м: цепочка склеивается транзитивно
        self.assertEqual(len(cluster_locations(points, 1000)), 1)

    def test_no_coords_separate(self):
        clusters = cluster_locations([loc("A"), loc("B", 0.0, 0.0)], 1000)
        self.assertEqual(len(clusters), 2)


class TestMatching(unittest.TestCase):
    def test_military_is_city_wide(self):
        analysis = Analysis(
            relevant=True, categories=["bpla"], scope="city", city="Саратов",
            summary="Опасность атаки БПЛА", source="mchs_saratov",
        )
        self.assertTrue(analysis.is_city_wide)
        here = loc("Чапаева, 12", street="улица Чапаева", house="12")
        far = loc("Ленина, 3", street="улица Ленина", house="3", city="Энгельс")
        self.assertTrue(matches_location(analysis, here))
        self.assertFalse(matches_location(analysis, far))

    def test_utility_is_address_level(self):
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="street", city="Саратов",
            streets=[{"street": "улица Чапаева", "houses": ["12", "14"]}],
            summary="Отключение холодной воды", source="saratovvodokanal",
        )
        self.assertFalse(analysis.is_city_wide)
        hit = loc("Чапаева, 12", street="улица Чапаева", house="12")
        miss_house = loc("Чапаева, 30", street="улица Чапаева", house="30")
        miss_street = loc("Рахова, 12", street="улица Рахова", house="12")
        self.assertTrue(matches_location(analysis, hit))
        self.assertFalse(matches_location(analysis, miss_house))
        self.assertFalse(matches_location(analysis, miss_street))

    def test_utility_citywide_when_no_streets(self):
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="city", city="Саратов",
            summary="Город останется без горячей воды", source="tplus_saratov",
        )
        self.assertTrue(matches_location(analysis, loc("Рахова, 12", street="улица Рахова")))

    def test_utility_district(self):
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="district", city="Саратов",
            districts=["Кировский район"], summary="Отключение света", source="s",
        )
        inside = loc("Рахова, 12", district="Кировский район")
        outside = loc("Ленина, 3", district="Заводской район")
        self.assertTrue(matches_location(analysis, inside))
        self.assertFalse(matches_location(analysis, outside))

    def test_whitelist_city_wide(self):
        analysis = Analysis(
            relevant=True, categories=["whitelist"], scope="region", city="Саратов",
            summary="Ограничения мобильного интернета", source="s",
        )
        self.assertTrue(analysis.is_city_wide)

    def test_irrelevant_never_matches(self):
        self.assertFalse(matches_location(Analysis(relevant=False), loc("A")))

    def test_legacy_location_without_street(self):
        """Локация из базы 2.x: адрес только в name."""
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="street", city="",
            streets=[{"street": "Чапаева", "houses": []}],
            raw="Авария на улице Чапаева", source="s",
        )
        legacy = loc("Чапаева, 12", street="", city="")
        self.assertTrue(matches_location(analysis, legacy))

    def test_match_locations_returns_subset(self):
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="street", city="Саратов",
            streets=[{"street": "улица Рахова", "houses": []}], source="s",
        )
        items = [
            loc("Рахова, 1", street="улица Рахова"),
            loc("Чапаева, 2", street="улица Чапаева"),
        ]
        self.assertEqual([x["name"] for x in match_locations(analysis, items)], ["Рахова, 1"])


class TestHeuristics(unittest.TestCase):
    def test_utility_detected_without_ai(self):
        text = "Внимание! Отключение холодной воды по ул. Чапаева, д. 12 и д. 14 до 18:00."
        analysis = heuristic_analysis(text, source="saratovvodokanal")
        self.assertTrue(analysis.relevant)
        self.assertIn("jkh", analysis.categories)
        self.assertTrue(any("Чапаева" in s["street"] for s in analysis.streets))
        self.assertEqual(analysis.engine, "heuristic")

    def test_military_detected(self):
        analysis = heuristic_analysis("Объявлена опасность атаки БПЛА", source="mchs")
        self.assertIn("bpla", analysis.categories)
        self.assertTrue(analysis.is_city_wide)

    def test_noise_ignored(self):
        analysis = heuristic_analysis("Розыгрыш призов среди подписчиков!", source="x")
        self.assertFalse(analysis.relevant)


class TestMessages(unittest.TestCase):
    def test_city_alert_lists_locations(self):
        events = [Analysis(relevant=True, categories=["bpla"], summary="Работа ПВО", source="mchs")]
        text = build_city_alert("Саратов", [loc("Чапаева, 12"), loc("Рахова, 3")], events)
        self.assertIn("Саратов", text)
        self.assertIn("Чапаева, 12", text)
        self.assertIn("Рахова, 3", text)
        self.assertIn("Совпавшие локации", text)

    def test_utility_alert_marks_group(self):
        events = [Analysis(relevant=True, categories=["jkh"], summary="Нет воды", source="vk")]
        text = build_utility_alert([loc("A"), loc("B")], events, grouped=True)
        self.assertIn("в пределах 1 км", text)

    def test_html_escaped(self):
        events = [Analysis(relevant=True, categories=["jkh"], summary="<script>", source="s")]
        text = build_utility_alert([loc("A & B")], events, grouped=False)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)


class TestRoles(unittest.TestCase):
    def test_superadmin_assigns_admin(self):
        self.assertTrue(roles.can_assign("superadmin", "user", "admin"))

    def test_admin_cannot_assign_admin(self):
        self.assertFalse(roles.can_assign("admin", "user", "admin"))
        self.assertTrue(roles.can_assign("admin", "user", "moderator"))

    def test_admin_cannot_touch_admin(self):
        self.assertFalse(roles.can_assign("admin", "admin", "moderator"))
        self.assertFalse(roles.can_delete_user("admin", "admin"))

    def test_moderator_assigns_nobody(self):
        self.assertEqual(roles.assignable_roles("moderator"), [])
        self.assertFalse(roles.can_assign("moderator", "user", "user"))

    def test_delete_requires_admin(self):
        self.assertFalse(roles.can_delete_user("moderator", "user"))
        self.assertTrue(roles.can_delete_user("admin", "user"))
        self.assertTrue(roles.can_delete_user("superadmin", "admin"))
        self.assertFalse(roles.can_delete_user("superadmin", "superadmin"))

    def test_edit_from_moderator(self):
        self.assertTrue(roles.can_edit_user("moderator", "user"))
        self.assertFalse(roles.can_edit_user("moderator", "moderator"))
        self.assertFalse(roles.can_edit_user("user", "user"))

    def test_assistant_from_moderator(self):
        self.assertFalse(roles.can_use_assistant("user"))
        self.assertTrue(roles.can_use_assistant("moderator"))
        self.assertTrue(roles.can_use_assistant("superadmin"))


class TestFormatting(unittest.TestCase):
    def test_split_respects_limit(self):
        chunks = split_text("строка\n" * 2000, limit=1000)
        self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))
        self.assertEqual("".join(chunks), "строка\n" * 2000)

    def test_markdown_to_html(self):
        html = md_to_html("**жирный** и `код` и <tag>")
        self.assertIn("<b>жирный</b>", html)
        self.assertIn("<code>код</code>", html)
        self.assertIn("&lt;tag&gt;", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
