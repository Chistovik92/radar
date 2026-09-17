#!/usr/bin/env python3
"""Страница ссылок: людские отдельно от системных (с 4.9.8.13).

Ссылки подборок заводит рассылка (`radar/monitor.py`) — без автора,
`created_by = 0`. Их становится во много раз больше, чем сокращённых
людьми, и вперемешку они прячут ровно то, ради чего на страницу заходят.
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar.web import panel  # noqa: E402


class Split(unittest.TestCase):
    def test_zero_author_is_system(self):
        people, system = panel._split_links([
            {"code": "a", "created_by": 0},
            {"code": "b", "created_by": 12345},
        ])
        self.assertEqual([item["code"] for item in people], ["b"])
        self.assertEqual([item["code"] for item in system], ["a"])

    def test_missing_field_counts_as_system(self):
        # Старые записи могли лечь без поля вовсе.
        people, system = panel._split_links([{"code": "a"}])
        self.assertEqual(people, [])
        self.assertEqual(len(system), 1)

    def test_string_identifier_is_a_person(self):
        people, _ = panel._split_links([{"code": "a", "created_by": "77"}])
        self.assertEqual(len(people), 1)

    def test_nothing_is_lost(self):
        items = [{"code": str(i), "created_by": i % 2} for i in range(10)]
        people, system = panel._split_links(items)
        self.assertEqual(len(people) + len(system), len(items))


class Markup(unittest.TestCase):
    def setUp(self) -> None:
        with open(os.path.join(ROOT, "radar", "web", "panel.py"),
                  encoding="utf-8") as handle:
            self.source = handle.read()

    def test_system_links_are_behind_a_spoiler(self):
        self.assertIn("Системные ссылки подборок", self.source)
        self.assertIn('<details class="card">', self.source)

    def test_people_go_first(self):
        start = self.source.index("async def _links_body")
        block = self.source[start:start + 4000]
        self.assertLess(block.index("people, system = _split_links"),
                        block.index("Системные ссылки подборок"))

    def test_spoiler_is_styled(self):
        # Иначе в «Матрице» и «Реакторе» он выглядит как случайный текст.
        self.assertIn("details.card > summary", panel.PAGE_STYLE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
