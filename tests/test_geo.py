#!/usr/bin/env python3
"""География оповещений, события в прошлом и сводки.

Главный сценарий: пользователь в Саратове не должен получать тревогу
о Подмосковье, а сообщение о вчерашних событиях не должно приходить
как сигнал опасности.
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
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.matching import (  # noqa: E402
    HISTORICAL_RE,
    Analysis,
    build_recap,
    geo_matches,
    heuristic_analysis,
    plan_alerts,
)

ALL_ON = {"jkh": True, "bpla": True, "mchs": True, "whitelist": True}


def saratov(street: str = "", house: str = "") -> dict:
    return {
        "id": "a", "name": "Чапаева, 12", "lat": 51.533, "lon": 46.034,
        "city": "Саратов", "district": "", "region": "Саратовская область",
        "street": street, "house": house,
    }


def alert(city: str = "", region: str = "", raw: str = "", **extra) -> Analysis:
    payload = {
        "relevant": True, "categories": ["bpla"], "severity": "critical",
        "scope": "city", "city": city, "region": region,
        "summary": "Опасность атаки БПЛА", "source": "mchs_official", "raw": raw,
    }
    payload.update(extra)
    return Analysis(**payload)


class TestGeography(unittest.TestCase):
    """Без подтверждённого совпадения тревога не уходит."""

    def test_own_city_matches(self):
        self.assertTrue(geo_matches(alert(city="Саратов"), saratov()))

    def test_other_city_blocked(self):
        self.assertFalse(geo_matches(alert(city="Москва"), saratov()))

    def test_other_region_blocked(self):
        self.assertFalse(
            geo_matches(alert(region="Московская область"), saratov())
        )

    def test_own_region_matches(self):
        self.assertTrue(geo_matches(alert(region="Саратовская область"), saratov()))

    def test_unknown_geography_blocked_for_citywide(self):
        """Главный баг: событие без географии рассылалось всем подряд."""
        self.assertFalse(geo_matches(alert(raw="Объявлена опасность БПЛА"), saratov()))

    def test_unknown_geography_matched_by_text(self):
        self.assertTrue(
            geo_matches(alert(raw="В Саратове объявлена опасность"), saratov())
        )

    def test_address_event_without_geography_passes(self):
        """Адресное событие судим по улице: она достаточно специфична."""
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="street",
            streets=[{"street": "улица Чапаева", "houses": []}], source="s",
        )
        self.assertTrue(geo_matches(analysis, saratov(street="улица Чапаева")))

    def test_moscow_alert_not_delivered_to_saratov(self):
        """Сквозная проверка через планировщик."""
        moscow = alert(city="Москва", region="Москва")
        self.assertEqual(plan_alerts([saratov()], ALL_ON, [moscow]), [])

    def test_federal_alert_without_city_not_delivered(self):
        federal = alert(raw="Силы ПВО отражают атаку беспилотников")
        self.assertEqual(plan_alerts([saratov()], ALL_ON, [federal]), [])

    def test_own_city_alert_delivered(self):
        messages = plan_alerts([saratov()], ALL_ON, [alert(city="Саратов")])
        self.assertEqual(len(messages), 1)


class TestHistorical(unittest.TestCase):
    """Прошедшие события не поднимают тревогу."""

    def test_markers_detected(self):
        samples = [
            "Вчера силы ПВО сбили беспилотник",
            "В ночь на среду отражена атака",
            "По итогам суток уничтожено 12 БПЛА",
            "Напомним, ранее сообщалось о падении обломков",
            "Как сообщалось, 12 августа была атака",
        ]
        for text in samples:
            self.assertIsNotNone(HISTORICAL_RE.search(text), text)

    def test_current_alert_not_historical(self):
        samples = [
            "Внимание! Объявлена опасность атаки БПЛА",
            "В городе воздушная тревога, пройдите в укрытия",
        ]
        for text in samples:
            self.assertIsNone(HISTORICAL_RE.search(text), text)

    def test_heuristic_sets_flag_and_severity(self):
        analysis = heuristic_analysis(
            "Вчера силы ПВО сбили беспилотник над областью", source="mchs"
        )
        self.assertTrue(analysis.historical)
        self.assertEqual(analysis.severity, "info")

    def test_historical_not_sent_as_alert(self):
        past = alert(city="Саратов", historical=True)
        self.assertEqual(plan_alerts([saratov()], ALL_ON, [past]), [])

    def test_payload_flag(self):
        analysis = Analysis.from_payload(
            {"relevant": True, "categories": ["bpla"], "historical": True},
            source="s", raw="вчера",
        )
        self.assertTrue(analysis.historical)


class TestRecap(unittest.TestCase):
    """Сводка по завершившимся событиям."""

    def test_empty_gives_nothing(self):
        self.assertEqual(build_recap([]), "")

    def test_groups_by_category(self):
        events = [
            alert(city="Саратов", historical=True, summary="Сбиты БПЛА"),
            Analysis(relevant=True, categories=["jkh"], historical=True,
                     summary="Вчера чинили водовод", source="vk"),
        ]
        text = build_recap(events, "за сутки", "Саратов")
        self.assertIn("Сводка за сутки", text)
        self.assertIn("Саратов", text)
        self.assertIn("Сбиты БПЛА", text)
        self.assertIn("Вчера чинили водовод", text)

    def test_marked_as_recap_not_alarm(self):
        text = build_recap([alert(city="Саратов", historical=True)])
        self.assertIn("уже завершилось", text)
        self.assertNotIn("ОПАСНОСТЬ", text)

    def test_long_list_trimmed(self):
        events = [
            alert(city="Саратов", historical=True, summary=f"Событие {i}")
            for i in range(12)
        ]
        text = build_recap(events)
        self.assertIn("и ещё", text)

    def test_link_rendered(self):
        events = [
            Analysis(relevant=True, categories=["bpla"], historical=True,
                     summary="Итоги ночи", source="sarbc.ru",
                     link="https://sarbc.ru/1")
        ]
        self.assertIn("https://sarbc.ru/1", build_recap(events))


class TestRecapSchedule(unittest.TestCase):
    def setUp(self):
        import sys as system

        system.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"
        ))
        import stubcheck

        stubcheck.install()
        from radar import monitor

        self.monitor = monitor
        monitor._recap_pool.clear()
        monitor._recap_sent.clear()

    def tearDown(self):
        self.monitor._recap_pool.clear()
        self.monitor._recap_sent.clear()

    def test_no_recap_without_events(self):
        self.assertIsNone(self.monitor.recap_due(datetime(2026, 8, 14, 9, 0)))

    def test_recap_at_scheduled_hour(self):
        self.monitor._recap_pool.append(alert(city="Саратов", historical=True))
        self.assertIsNotNone(self.monitor.recap_due(datetime(2026, 8, 14, 9, 5)))

    def test_no_recap_at_other_hour(self):
        self.monitor._recap_pool.append(alert(city="Саратов", historical=True))
        self.assertIsNone(self.monitor.recap_due(datetime(2026, 8, 14, 13, 0)))

    def test_not_sent_twice(self):
        self.monitor._recap_pool.append(alert(city="Саратов", historical=True))
        moment = datetime(2026, 8, 14, 20, 0)
        marker = self.monitor.recap_due(moment)
        self.assertIsNotNone(marker)
        self.monitor._recap_sent["last"] = marker
        self.assertIsNone(self.monitor.recap_due(moment))

    def test_only_historical_collected(self):
        self.monitor.collect_recap([
            alert(city="Саратов", historical=True),
            alert(city="Саратов"),
        ])
        self.assertEqual(len(self.monitor._recap_pool), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
