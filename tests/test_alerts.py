#!/usr/bin/env python3
"""Отбой опасности, ссылки на новости и наборы источников по городам."""

from __future__ import annotations

import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import presets  # noqa: E402
from radar.matching import (  # noqa: E402
    ALL_CLEAR_NOTICE,
    ALL_CLEAR_RE,
    Analysis,
    build_all_clear,
    heuristic_analysis,
    plan_alerts,
)

ALL_ON = {"jkh": True, "bpla": True, "mchs": True, "whitelist": True}


def loc(name, lat=51.533, lon=46.034, city="Саратов"):
    return {"id": name, "name": name, "lat": lat, "lon": lon, "city": city,
            "district": "", "region": "", "street": "", "house": ""}


def alert(all_clear=False, summary="Опасность атаки БПЛА"):
    return Analysis(relevant=True, categories=["bpla"],
                    severity="info" if all_clear else "critical",
                    scope="city", city="Саратов", summary=summary,
                    source="mchs_saratov", all_clear=all_clear)


# ==========================================================================
#  Распознавание отбоя
# ==========================================================================

class TestAllClearDetection(unittest.TestCase):
    def test_typical_phrasings(self):
        samples = [
            "Отбой беспилотной опасности на территории области.",
            "✅ ОТБОЙ беспилотной и ракетной опасности на территории Самарской области.",
            "Опасность атаки БПЛА снята. Обстановка спокойная.",
            "Режим беспилотной опасности отменён.",
            "Воздушная тревога отменена, угроза миновала.",
        ]
        for text in samples:
            self.assertTrue(ALL_CLEAR_RE.search(text), text)

    def test_active_alert_not_matched(self):
        samples = [
            "Объявлена опасность атаки БПЛА. Просим сохранять спокойствие.",
            "В городе объявлена воздушная тревога, пройдите в укрытия.",
            "Работают силы противовоздушной обороны.",
        ]
        for text in samples:
            self.assertIsNone(ALL_CLEAR_RE.search(text), text)

    def test_heuristic_sets_flag(self):
        analysis = heuristic_analysis("Отбой беспилотной опасности", source="mchs")
        self.assertTrue(analysis.relevant)
        self.assertTrue(analysis.all_clear)
        self.assertIn("bpla", analysis.categories)
        self.assertEqual(analysis.severity, "info")

    def test_heuristic_active_alert_is_critical(self):
        analysis = heuristic_analysis("Объявлена опасность атаки БПЛА", source="mchs")
        self.assertFalse(analysis.all_clear)
        self.assertEqual(analysis.severity, "critical")

    def test_payload_flag(self):
        analysis = Analysis.from_payload(
            {"relevant": True, "categories": ["bpla"], "all_clear": True},
            source="s", raw="отбой",
        )
        self.assertTrue(analysis.all_clear)


# ==========================================================================
#  Сообщение отбоя
# ==========================================================================

class TestAllClearMessage(unittest.TestCase):
    def test_separate_message_kind(self):
        messages = plan_alerts([loc("Чапаева, 12")], ALL_ON, [alert(all_clear=True)])
        self.assertEqual([kind for kind, _ in messages], ["clear"])

    def test_text_differs_from_alarm(self):
        text = plan_alerts([loc("A")], ALL_ON, [alert(all_clear=True)])[0][1]
        self.assertIn("ОТБОЙ", text)
        self.assertNotIn("🚨", text)
        self.assertIn("✅", text)

    def test_alarm_and_clear_never_merge(self):
        """Действующая тревога и отбой не должны попасть в одно сообщение."""
        messages = plan_alerts(
            [loc("A")], ALL_ON, [alert(), alert(all_clear=True, summary="Отбой")]
        )
        kinds = sorted(kind for kind, _ in messages)
        self.assertEqual(kinds, ["city", "clear"])

    def test_whitelist_notice_says_soon_disabled(self):
        text = build_all_clear("Саратов", [loc("A")], [alert(all_clear=True)], True)
        self.assertIn("отключены", text)
        self.assertIn("ближайшее время", text)

    def test_whitelist_notice_respects_setting(self):
        settings = dict(ALL_ON, whitelist=False)
        text = plan_alerts([loc("A")], settings, [alert(all_clear=True)])[0][1]
        self.assertNotIn("Белые списки", text)
        self.assertNotIn("белые списки", text.lower())

    def test_notice_texts_differ(self):
        from radar.matching import WHITELIST_NOTICE

        self.assertNotEqual(ALL_CLEAR_NOTICE, WHITELIST_NOTICE)


# ==========================================================================
#  Ссылки на новости
# ==========================================================================

class TestNewsLinks(unittest.TestCase):
    def test_link_rendered(self):
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="city", city="Саратов",
            summary="Отключение воды", source="sarbc.ru",
            link="https://sarbc.ru/news/123",
        )
        text = plan_alerts([loc("A")], ALL_ON, [analysis])[0][1]
        self.assertIn("https://sarbc.ru/news/123", text)
        self.assertIn("Читать источник", text)

    def test_no_link_no_footer(self):
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="city", city="Саратов",
            summary="Отключение воды", source="saratovzhkh",
        )
        text = plan_alerts([loc("A")], ALL_ON, [analysis])[0][1]
        self.assertNotIn("Читать источник", text)

    def test_link_escaped(self):
        analysis = Analysis(
            relevant=True, categories=["jkh"], scope="city", city="Саратов",
            summary="х", source="site.ru", link='https://site.ru/a?b="x"&c=1',
        )
        text = plan_alerts([loc("A")], ALL_ON, [analysis])[0][1]
        self.assertNotIn('?b="x"', text)
        self.assertIn("&amp;", text)

    def test_rss_entry_link_extracted(self):
        from radar.sources import _entry_link

        rss = ET.fromstring(
            "<item><title>Т</title><link>https://a.ru/1</link></item>"
        )
        self.assertEqual(_entry_link(rss), "https://a.ru/1")

    def test_atom_entry_link_extracted(self):
        from radar.sources import _entry_link

        atom = ET.fromstring(
            '<entry xmlns="http://www.w3.org/2005/Atom">'
            '<title>Т</title><link rel="alternate" href="https://a.ru/2"/></entry>'
        )
        self.assertEqual(_entry_link(atom), "https://a.ru/2")

    def test_guid_fallback(self):
        from radar.sources import _entry_link

        item = ET.fromstring("<item><guid>https://a.ru/3</guid></item>")
        self.assertEqual(_entry_link(item), "https://a.ru/3")

    def test_missing_link_is_empty(self):
        from radar.sources import _entry_link

        self.assertEqual(_entry_link(ET.fromstring("<item><title>Т</title></item>")), "")


# ==========================================================================
#  Пресеты городов
# ==========================================================================

class TestPresets(unittest.TestCase):
    def test_all_cities_present(self):
        keys = set(presets.BY_KEY)
        for expected in ("saratov", "moscow", "spb", "kazan", "samara", "federal"):
            self.assertIn(expected, keys)

    def test_lookup_by_russian_name(self):
        self.assertEqual(presets.for_city("Казань").key, "kazan")
        self.assertEqual(presets.for_city("Санкт-Петербург").key, "spb")
        self.assertIsNone(presets.for_city(""))
        self.assertIsNone(presets.for_city("Урюпинск"))

    def test_federal_always_included(self):
        channels = presets.channels_for(["kazan"])
        self.assertIn("mchs_official", channels)
        self.assertIn("vodokanalkzn", channels)

    def test_no_duplicates_across_cities(self):
        channels = presets.channels_for(["saratov", "moscow", "spb", "kazan", "samara"])
        self.assertEqual(len(channels), len(set(channels)))

    def test_dead_feed_removed(self):
        """Лента закрывшегося издания не должна остаться в пресете."""
        self.assertNotIn(
            "https://fn-volga.ru/rss", presets.SARATOV.rss
        )

    def test_every_channel_username_valid(self):
        import re

        pattern = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
        for preset in presets.ALL:
            for name in preset.channels:
                self.assertRegex(name, pattern, f"{preset.key}: {name}")

    def test_every_feed_is_url(self):
        for preset in presets.ALL:
            for url in preset.rss:
                self.assertTrue(url.startswith("https://"), f"{preset.key}: {url}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
