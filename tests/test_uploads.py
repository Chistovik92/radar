#!/usr/bin/env python3
"""Приём файлов (5.9.0.1): cookies больше не попадают в список источников.

В 4.9.9.3 файл cookies, присланный после /cookies, разбирала загрузка
источников — она первой в цепочке ловила любой документ. Здесь закреплено:
документ идёт в тот раздел, который его просил, а без просьбы — по имени.
"""

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
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import cookies, uploads  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def setUp(self) -> None:
        uploads.reset()

    def test_cookies_by_name_for_superadmin(self) -> None:
        self.assertEqual(uploads.classify("1", "cookies.txt", superadmin=True), uploads.COOKIES)
        self.assertEqual(uploads.classify("1", "www.youtube.com_cookies.txt", superadmin=True),
                         uploads.COOKIES)

    def test_cookie_name_is_not_enough_for_others(self) -> None:
        self.assertEqual(uploads.classify("2", "cookies.txt", superadmin=False), uploads.SOURCES)

    def test_unknown_file_goes_to_sources(self) -> None:
        self.assertEqual(uploads.classify("1", "channels.txt", superadmin=True), uploads.SOURCES)
        self.assertEqual(uploads.classify("1", "db.json", superadmin=True), uploads.SOURCES)

    def test_expectation_beats_name(self) -> None:
        uploads.expect("1", uploads.COOKIES)
        self.assertEqual(uploads.classify("1", "export.txt", superadmin=True), uploads.COOKIES)
        uploads.expect("1", uploads.SOURCES)
        self.assertEqual(uploads.classify("1", "cookies.txt", superadmin=True), uploads.SOURCES)

    def test_expectation_is_per_user_and_expires(self) -> None:
        uploads.expect("1", uploads.COOKIES, now=1000)
        self.assertIsNone(uploads.expected("2", now=1001))
        self.assertEqual(uploads.expected("1", now=1001), uploads.COOKIES)
        self.assertIsNone(uploads.expected("1", now=1000 + uploads.EXPECT_TTL + 1))

    def test_done_clears_expectation(self) -> None:
        uploads.expect("1", uploads.COOKIES)
        uploads.done("1")
        self.assertIsNone(uploads.expected("1"))


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        uploads.reset()

    def test_route_sends_document_to_registered_handler(self) -> None:
        from radar.handlers import documents

        calls: list[str] = []

        async def fake(message, role, user):
            calls.append(message.document.file_name)

        saved = dict(uploads._handlers)
        uploads.register(uploads.COOKIES, fake)
        try:
            message = SimpleNamespace(
                document=SimpleNamespace(file_name="cookies.txt"),
                from_user=SimpleNamespace(id=1),
                answer=None,
            )
            asyncio.run(documents.route_document(message, "superadmin", {}))
        finally:
            uploads._handlers.clear()
            uploads._handlers.update(saved)
        self.assertEqual(calls, ["cookies.txt"])


class CookieLimitTests(unittest.TestCase):
    def test_export_from_screenshot_fits(self) -> None:
        # 749,5 КБ — размер файла из отчёта о 4.9.9.3.
        self.assertGreater(cookies.MAX_BYTES, 750 * 1024)


if __name__ == "__main__":
    unittest.main()
