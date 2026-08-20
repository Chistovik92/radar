#!/usr/bin/env python3
"""Партнёрские проекты: разбор, порядок, устойчивость к мусору."""

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

from radar import partners  # noqa: E402
from radar.handlers.partners import _make_slug  # noqa: E402


def raw(slug="test", title="Проект", url="https://example.ru", **extra):
    item = {"slug": slug, "title": title, "url": url}
    item.update(extra)
    return item


class TestProject(unittest.TestCase):
    def test_roundtrip(self):
        project = partners.Project.from_dict(raw(description="Опис", icon="🐙"))
        self.assertIsNotNone(project)
        again = partners.Project.from_dict(project.to_dict())
        self.assertEqual(project, again)

    def test_rejects_bad_url(self):
        """Ссылка ведёт наружу людям, которым бот сообщает об опасности."""
        for url in ("javascript:alert(1)", "file:///etc/passwd", "", "не ссылка"):
            with self.subTest(url=url):
                self.assertIsNone(partners.Project.from_dict(raw(url=url)))

    def test_accepts_telegram_link(self):
        self.assertIsNotNone(
            partners.Project.from_dict(raw(url="tg://resolve?domain=test"))
        )

    def test_rejects_bad_slug(self):
        for slug in ("", "a", "ЗАГЛАВНЫЕ", "с пробелом", "x" * 40):
            with self.subTest(slug=slug):
                self.assertIsNone(partners.Project.from_dict(raw(slug=slug)))

    def test_rejects_empty_title(self):
        self.assertIsNone(partners.Project.from_dict(raw(title="   ")))

    def test_long_fields_trimmed(self):
        project = partners.Project.from_dict(
            raw(title="Т" * 200, description="О" * 900)
        )
        self.assertLessEqual(len(project.title), partners.MAX_TITLE)
        self.assertLessEqual(len(project.description), partners.MAX_DESCRIPTION)

    def test_broken_numbers_get_defaults(self):
        project = partners.Project.from_dict(raw(order="не число", clicks=-5))
        self.assertEqual(project.order, 100)
        self.assertEqual(project.clicks, 0)


class TestParseAll(unittest.TestCase):
    def test_garbage_entries_dropped_not_whole_list(self):
        """Одна битая запись не должна ронять раздел целиком."""
        result = partners.parse_all([
            None, "строка", {"slug": "нет-названия"},
            raw(slug="good-one"), 42,
        ])
        self.assertEqual([item.slug for item in result], ["good-one"])

    def test_duplicates_removed(self):
        result = partners.parse_all([raw(slug="same"), raw(slug="same")])
        self.assertEqual(len(result), 1)

    def test_not_a_list(self):
        self.assertEqual(partners.parse_all({"slug": "x"}), [])
        self.assertEqual(partners.parse_all(None), [])

    def test_limit_enforced(self):
        many = [raw(slug=f"p-{index}") for index in range(partners.MAX_PROJECTS + 15)]
        self.assertEqual(len(partners.parse_all(many)), partners.MAX_PROJECTS)


class TestOrdering(unittest.TestCase):
    def build(self):
        return [
            partners.Project(slug="b", title="Бета", url="https://b.ru", order=50),
            partners.Project(slug="a", title="Альфа", url="https://a.ru", order=10),
            partners.Project(slug="c", title="Гамма", url="https://c.ru",
                             order=10, visible=False),
        ]

    def test_sorted_by_order_then_title(self):
        result = partners.order_projects(self.build())
        self.assertEqual([item.slug for item in result], ["a", "c", "b"])

    def test_hidden_excluded_from_visible(self):
        result = partners.visible_projects(self.build())
        self.assertNotIn("c", [item.slug for item in result])


class TestSlug(unittest.TestCase):
    def test_transliterates_russian(self):
        self.assertEqual(_make_slug("Мой Проект", set()), "moy-proekt")

    def test_valid_by_rules(self):
        for title in ("HydraSite", "Мой Проект", "Проект 2", "!!!"):
            with self.subTest(title=title):
                self.assertTrue(partners.valid_slug(_make_slug(title, set())))

    def test_collision_gets_number(self):
        self.assertEqual(_make_slug("Тест", {"test"}), "test-2")

    def test_second_collision(self):
        self.assertEqual(_make_slug("Тест", {"test", "test-2"}), "test-3")


class TestDefaults(unittest.TestCase):
    def project(self):
        projects = partners.default_projects()
        if not projects:
            self.skipTest("промо отключено в окружении")
        return projects[0]

    def test_icon_split_from_title(self):
        """Значок в PROMO_TITLE не должен задваиваться в списке."""
        project = self.project()
        self.assertNotIn(project.icon, project.title)

    def test_description_has_no_markup(self):
        """PROMO_TEXT писался с HTML, а в списке выводится с экранированием:
        теги должны быть сняты, иначе человек увидит «<b>HydraSite</b>»."""
        description = self.project().description
        for tag in ("<b>", "</b>", "<i>", "<a ", "&lt;"):
            self.assertNotIn(tag, description)

    def test_description_does_not_repeat_title(self):
        """Название уже стоит заголовком — повтор в описании выглядит сбоем."""
        project = self.project()
        first = project.description.split("\n")[0].strip()
        self.assertFalse(first.lower().startswith(project.title.lower()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
