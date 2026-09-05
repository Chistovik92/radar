"""Тесты модуля разбора ссылок на мошенничество (offline-часть).

Проверяется только analyse.py, так как он не требует сети и
подходит для быстрого unit-тестирования без стабов.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from multitool.linkcheck.analyze import (  # noqa: E402
    Signal,
    Verdict,
    analyze,
    levenshtein,
    _is_ip,
    _is_puny,
    _mixed_script,
    _extract_registrable,
    _deconfuse,
    _norm,
    BRANDS,
    ALL_LEGIT,
)


class TestLinkCheck(unittest.TestCase):
    def test_levenshtein(self):
        self.assertEqual(levenshtein("", ""), 0)
        self.assertEqual(levenshtein("a", "b"), 1)
        self.assertEqual(levenshtein("kitten", "sitting"), 3)
        self.assertEqual(levenshtein("sber", "sber"), 0)
        self.assertEqual(levenshtein("sber", "sberr"), 1)
        self.assertEqual(levenshtein("sber", "szer"), 1)

    def test_is_ip(self):
        self.assertTrue(_is_ip("192.168.1.1"))
        self.assertTrue(_is_ip("8.8.8.8"))
        self.assertTrue(_is_ip("2001:db8::1"))
        self.assertFalse(_is_ip("not.an.ip"))
        self.assertFalse(_is_ip("999.999.999.999"))

    def test_is_puny(self):
        self.assertTrue(_is_puny("xn--80akhbyknj4f.xn--p1ai"))
        self.assertFalse(_is_puny("example.com"))
        self.assertTrue(_is_puny("xn--node"))
        self.assertTrue(_is_puny("xn--vermgensberatung-pwb.de"))

    def test_mixed_script(self):
        self.assertTrue(_mixed_script("аbc"))
        self.assertTrue(_mixed_script("αbc"))
        self.assertFalse(_mixed_script("abc"))
        self.assertFalse(_mixed_script("абвг"))

    def test_extract_registrable(self):
        self.assertEqual(_extract_registrable("example.com"), ("example", "com"))
        self.assertEqual(_extract_registrable("a.b.c.uk"), ("a.b", "c.uk"))
        self.assertEqual(_extract_registrable("test.co.uk"), ("test", "co.uk"))
        self.assertEqual(_extract_registrable("site.com.br"), ("site", "com.br"))
        self.assertEqual(_extract_registrable("host.msu.ru"), ("host.msu", "ru"))
        self.assertEqual(_extract_registrable("something.pp.ru"), ("something", "pp.ru"))

    def test_deconfuse(self):
        self.assertEqual(_deconfuse("sberbank"), "sberbank")
        self.assertEqual(_deconfuse("g00gle"), "google")
        self.assertEqual(_deconfuse("а"), "a")

    def test_norm(self):
        self.assertEqual(_norm("abc123"), "abc12e")
        self.assertEqual(_norm("sЬberbаnk.ru"), "sberbankru")

    def test_basic_urls(self):
        v = analyze("http://example.com")
        self.assertTrue(any(s.code == "scheme_http" for s in v.signals))
        v = analyze("https://example.com")
        self.assertFalse(any(s.code == "scheme_http" for s in v.signals))
        v = analyze("javascript:alert(1)")
        self.assertTrue(any(s.code == "executable_scheme" for s in v.signals))
        v = analyze("http://192.168.1.1/login")
        self.assertTrue(any(s.code == "ip_literal" for s in v.signals))
        v = analyze("http://xn--80akhbyknj4f.xn--p1ai/")
        self.assertTrue(any(s.code == "punycode" for s in v.signals))
        v = analyze("http://ѕberbаnk.ru/")
        self.assertTrue(any(s.code == "mixed_script" for s in v.signals))
        self.assertTrue(any(s.code == "homograph_brand" for s in v.signals))
        v = analyze("http://user:pass@example.com/")
        self.assertTrue(any(s.code == "userinfo" for s in v.signals))
        self.assertTrue(any(s.title == "учётные данные: user:pass" for s in v.signals))
        v = analyze("https://sberbank.top/login")
        self.assertTrue(any(s.code == "brand_wrong_domain" for s in v.signals))
        v = analyze("https://sberbnak.ru/")
        self.assertTrue(any(s.code == "typosquat" for s in v.signals))
        v = analyze("https://example.tk/")
        self.assertTrue(any(s.code == "suspicious_tld" for s in v.signals))
        v = analyze("https://a.b.c.d.example.com/")
        self.assertTrue(any(s.code == "subdomain_depth" for s in v.signals))
        v = analyze("https://s-b-er-banking.ru/")
        self.assertTrue(any(s.code == "hyphen_label" for s in v.signals))
        v = analyze("https://bit.ly/3xyzABC")
        self.assertTrue(any(s.code == "shortener" for s in v.signals))
        v = analyze("https://secure-login.example.com/verify")
        self.assertTrue(any(s.code == "bait_word" for s in v.signals))
        v = analyze("http://example.com/file.exe")
        self.assertTrue(any(s.code == "executable_ext" for s in v.signals))
        v = analyze("http://example.com/document.pdf.exe")
        self.assertTrue(any(s.code == "double_ext" for s in v.signals))
        v = analyze("http://example.com/%31%32%33%34%35")
        self.assertTrue(any(s.code == "many_escapes" for s in v.signals))
        v = analyze("http://example.com.")
        self.assertTrue(any(s.code == "trailing_dot" for s in v.signals))
        v = analyze("http://example.com\u200b/")
        self.assertTrue(any(s.code == "zero_width" for s in v.signals))
        v = analyze("http://sberb2nk.ru/")
        self.assertTrue(any(s.code == "digits_in_brand" for s in v.signals))

    def test_verdict_scoring(self):
        v = analyze("https://www.google.com/search?q=test")
        self.assertLessEqual(v.score, 14)
        self.assertEqual(v.level, "ok")
        v = analyze("https://sberbank.top/login")
        self.assertGreaterEqual(v.score, 35)
        self.assertEqual(v.level, "suspect")
        v = analyze("javascript:alert(document.cookie)")
        self.assertGreaterEqual(v.score, 60)
        self.assertEqual(v.level, "danger")

    def test_extract_urls(self):
        text = "Проверь http://example.com и https://test.ru/path?q=1"
        urls = re.findall(r"https?://[^\s<>()]+", text, re.IGNORECASE)
        self.assertEqual(urls, ["http://example.com", "https://test.ru/path?q=1"])

    def test_report_building(self):
        from multitool.linkcheck.report import build_report, build_report_plain
        from multitool.linkcheck.analyze import Signal
        v = Verdict(url="https://example.com")
        v.signals.append(Signal("scheme_http", 20, "незащищённое HTTP"))
        report = build_report(v)
        self.assertIn("Результат проверки ссылки", report)
        self.assertIn("https://example.com", report)
        plain = build_report_plain(v)
        self.assertIn("Результат проверки ссылки", plain)
        self.assertIn("https://example.com", plain)

    def test_real_world_examples(self):
        v = analyze("http://ѕbегbаnk.ru.рф/login.php")
        self.assertGreater(v.score, 30)
        v = analyze("https://www.sberbank.ru/")
        self.assertLess(v.score, 20)
        v = analyze("http://gооgle.com")
        self.assertGreaterEqual(v.score, 35)


if __name__ == "__main__":
    unittest.main(verbosity=2)