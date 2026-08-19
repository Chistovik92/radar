#!/usr/bin/env python3
"""Сокращение ссылок: коды, проверка адресов, отказ по умолчанию."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import shortener  # noqa: E402

BASE = "https://example.ru"


def with_base(base=BASE, salt="соль"):
    """Подменяет настройки: тесты не должны зависеть от .env машины."""
    def fake_get(key, default=""):
        return {"SHORT_BASE_URL": base, "SHORT_SALT": salt}.get(key, default)

    return mock.patch("radar.secrets.get", side_effect=fake_get)


class TestEnabled(unittest.TestCase):
    def test_disabled_without_base(self):
        """Без адреса сокращение выключено: ссылка в никуда хуже длинной."""
        with with_base(base=""):
            self.assertFalse(shortener.enabled())

    def test_enabled_with_base(self):
        with with_base():
            self.assertTrue(shortener.enabled())

    def test_trailing_slash_stripped(self):
        with with_base(base="https://example.ru/"):
            self.assertEqual(shortener.base_url(), "https://example.ru")


class TestValidation(unittest.TestCase):
    def test_accepts_http_and_https(self):
        self.assertTrue(shortener.valid("http://example.ru/a"))
        self.assertTrue(shortener.valid("https://example.ru/a"))

    def test_rejects_dangerous_schemes(self):
        """javascript: и file: превратили бы короткую ссылку в оружие."""
        for url in ("javascript:alert(1)", "file:///etc/passwd",
                    "data:text/html,<script>", "ftp://example.ru"):
            with self.subTest(url=url):
                self.assertFalse(shortener.valid(url))

    def test_rejects_garbage(self):
        for url in ("", "   ", "просто текст", "example.ru", "https://"):
            with self.subTest(url=url):
                self.assertFalse(shortener.valid(url))

    def test_rejects_overlong(self):
        self.assertFalse(shortener.valid("https://example.ru/" + "a" * 3000))


class TestCodes(unittest.TestCase):
    def test_deterministic(self):
        """Одна ссылка — один код: повтор не должен плодить записи."""
        with with_base():
            first = shortener.code_for("https://example.ru/новость")
            second = shortener.code_for("https://example.ru/новость")
        self.assertEqual(first, second)

    def test_different_urls_differ(self):
        with with_base():
            self.assertNotEqual(
                shortener.code_for("https://example.ru/a"),
                shortener.code_for("https://example.ru/b"),
            )

    def test_salt_separates_installs(self):
        """Разные экземпляры «Радара» не должны выдавать одинаковые коды."""
        with with_base(salt="первая"):
            first = shortener.code_for("https://example.ru/a")
        with with_base(salt="вторая"):
            second = shortener.code_for("https://example.ru/a")
        self.assertNotEqual(first, second)

    def test_length_and_alphabet(self):
        with with_base():
            code = shortener.code_for("https://example.ru/страница")
        self.assertEqual(len(code), shortener.CODE_LENGTH)
        for char in code:
            self.assertIn(char, shortener.ALPHABET)

    def test_alphabet_without_lookalikes(self):
        """Короткие ссылки диктуют голосом: ноль и «O» неразличимы."""
        for char in "01lIoO":
            self.assertNotIn(char, shortener.ALPHABET)

    def test_whitespace_ignored(self):
        with with_base():
            self.assertEqual(
                shortener.code_for(" https://example.ru/a "),
                shortener.code_for("https://example.ru/a"),
            )

    def test_short_url_format(self):
        with with_base():
            self.assertEqual(shortener.short_url("abc123"),
                             "https://example.ru/s/abc123")


class TestCodeValidation(unittest.TestCase):
    def test_accepts_own_codes(self):
        with with_base():
            code = shortener.code_for("https://example.ru/a")
        self.assertTrue(shortener.valid_code(code))

    def test_rejects_injection(self):
        """Код приходит из адресной строки — в базу должен идти чистым."""
        for code in ("../../etc", "abc'; DROP TABLE", "a" * 40, "", "AB0"):
            with self.subTest(code=code):
                self.assertFalse(shortener.valid_code(code))


if __name__ == "__main__":
    unittest.main(verbosity=2)
