#!/usr/bin/env python3
"""Промокоды: один код на человека, режимы выдачи, выгрузка без личных данных."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import partners, promo  # noqa: E402


class FakeRepo:
    """Хранилище в памяти вместо базы: правило «один код на человека»
    проверяется логикой, а не наличием PostgreSQL."""

    def __init__(self):
        self.rows: list[dict] = []

    async def promo_for_user(self, project, user_key):
        for row in self.rows:
            if row["project"] == project and row["user_key"] == str(user_key):
                return row
        return None

    async def promo_code_taken(self, code):
        return any(row["code"] == code for row in self.rows)

    async def save_promo(self, project, user_key, code, issued_at, shared=False):
        self.rows.append({
            "project": project, "user_key": str(user_key), "code": code,
            "issued_at": issued_at, "shared": shared,
        })

    async def promo_list(self, project):
        return [row for row in self.rows if row["project"] == project]


def run(coro):
    return asyncio.run(coro)


def project(kind=partners.UNIQUE, **extra):
    fields = {
        "slug": "hydrasite", "title": "HydraSite", "url": "https://example.ru",
        "promo_kind": kind,
    }
    fields.update(extra)
    return partners.Project(**fields)


class PromoCase(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepo()
        # Подменяем и атрибут пакета, и запись в sys.modules: `from .db
        # import repo` берёт готовый атрибут, если пакет уже импортирован,
        # и запись из sys.modules, если ещё нет. Какой путь сработает,
        # зависит от порядка запуска тестов, поэтому закрываем оба —
        # иначе файл проходит в общем прогоне и падает в одиночку.
        import radar.db

        self.patch = mock.patch.object(
            radar.db, "repo", self.repo, create=True
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)

        self.modules = mock.patch.dict(
            sys.modules, {"radar.db.repo": self.repo}
        )
        self.modules.start()
        self.addCleanup(self.modules.stop)


class TestIssue(PromoCase):
    def test_unique_code_issued(self):
        issued = run(promo.issue(project(), "111"))
        self.assertIsNotNone(issued)
        self.assertTrue(issued.code)
        self.assertFalse(issued.shared)

    def test_same_user_gets_same_code(self):
        """Повтор обязан вернуть прежний код, а не выдать новый."""
        first = run(promo.issue(project(), "111"))
        second = run(promo.issue(project(), "111"))
        self.assertEqual(first.code, second.code)
        self.assertEqual(len(self.repo.rows), 1)

    def test_different_users_get_different_codes(self):
        first = run(promo.issue(project(), "111"))
        second = run(promo.issue(project(), "222"))
        self.assertNotEqual(first.code, second.code)

    def test_prefix_applied(self):
        issued = run(promo.issue(project(promo_prefix="HYDRA"), "111"))
        self.assertTrue(issued.code.startswith("HYDRA-"))

    def test_shared_code_same_for_all(self):
        item = project(kind=partners.SHARED, promo_value="RADAR2026")
        first = run(promo.issue(item, "111"))
        second = run(promo.issue(item, "222"))
        self.assertEqual(first.code, "RADAR2026")
        self.assertEqual(second.code, "RADAR2026")
        self.assertTrue(first.shared)

    def test_shared_keeps_personal_date(self):
        """У общего кода дата получения личная — от неё считается срок."""
        item = project(kind=partners.SHARED, promo_value="RADAR2026")
        run(promo.issue(item, "111"))
        self.assertEqual(len(self.repo.rows), 1)
        self.assertIsInstance(self.repo.rows[0]["issued_at"], datetime)

    def test_no_promo_returns_none(self):
        self.assertIsNone(run(promo.issue(project(kind=partners.NONE), "111")))

    def test_shared_without_value_is_not_promo(self):
        item = project(kind=partners.SHARED, promo_value="")
        self.assertFalse(item.has_promo)
        self.assertIsNone(run(promo.issue(item, "111")))

    def test_collision_retried(self):
        """Занятый код не должен достаться второму человеку."""
        taken = {"count": 0}
        original = self.repo.promo_code_taken

        async def once_taken(code):
            taken["count"] += 1
            return taken["count"] == 1

        self.repo.promo_code_taken = once_taken
        issued = run(promo.issue(project(), "111"))
        self.repo.promo_code_taken = original
        self.assertIsNotNone(issued)
        self.assertGreaterEqual(taken["count"], 2)


class TestGenerate(unittest.TestCase):
    def test_length_and_alphabet(self):
        code = promo.generate()
        self.assertEqual(len(code), promo.CODE_LENGTH)
        for char in code:
            self.assertIn(char, promo.ALPHABET)

    def test_alphabet_without_lookalikes(self):
        """Код переписывают руками и диктуют голосом."""
        for char in "OI01l":
            self.assertNotIn(char, promo.ALPHABET)

    def test_codes_differ(self):
        codes = {promo.generate() for _ in range(200)}
        self.assertGreater(len(codes), 190)

    def test_prefix_sanitised(self):
        self.assertTrue(promo.generate("hy dra!").startswith("HYDRA-"))


class TestExport(PromoCase):
    def test_export_has_no_user_ids(self):
        """Обещание партнёру: коды без привязки к нашим людям."""
        run(promo.issue(project(), "123456789"))
        rows = run(promo.export_for_partner("hydrasite"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"code", "issued"})
        serialised = str(rows)
        self.assertNotIn("123456789", serialised)
        self.assertNotIn("user_key", serialised)

    def test_code_not_derived_from_user(self):
        """Код случайный: иначе партнёр восстановил бы, кто есть кто."""
        first = run(promo.issue(project(), "111"))
        self.repo.rows.clear()
        second = run(promo.issue(project(), "111"))
        self.assertNotEqual(first.code, second.code)

    def test_csv_has_header(self):
        rows = [{"code": "AAA-111", "issued": "2026-08-20"}]
        text = promo.render_csv(rows)
        self.assertTrue(text.startswith("code,issued"))
        self.assertIn("AAA-111,2026-08-20", text)

    def test_empty_export(self):
        self.assertEqual(run(promo.export_for_partner("hydrasite")), [])


class TestKinds(unittest.TestCase):
    def test_unknown_kind_falls_back_to_none(self):
        parsed = partners.Project.from_dict({
            "slug": "test", "title": "Т", "url": "https://a.ru",
            "promo_kind": "выдумка",
        })
        self.assertEqual(parsed.promo_kind, partners.NONE)

    def test_all_kinds_have_titles(self):
        for kind in partners.KINDS:
            self.assertIn(kind, partners.KIND_TITLES)

    def test_promo_fields_survive_roundtrip(self):
        item = project(kind=partners.SHARED, promo_value="X1",
                       promo_terms="Скидка 10%")
        again = partners.Project.from_dict(item.to_dict())
        self.assertEqual(again.promo_value, "X1")
        self.assertEqual(again.promo_terms, "Скидка 10%")


if __name__ == "__main__":
    unittest.main(verbosity=2)
