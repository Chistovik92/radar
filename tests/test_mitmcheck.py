#!/usr/bin/env python3
"""Новые проверки сайтов (4.9.5.2): перехват TLS, безопасность HTTP.

Проверяется логика без сети: кому поставить сигнал перехвата, а кому
нет — здесь цена ошибки асимметрична. Ложное обвинение сайта хуже
пропущенного признака, поэтому пороги консервативны.
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

from multitool.linkcheck.netcheck import _cert_mitm_suspect  # noqa: E402


class TestMitmSuspect(unittest.TestCase):
    """Перехват TLS: сигнал ставится противоречием, не фактом CA."""

    def test_national_ca_on_known_site(self):
        """YouTube с национальной подписью — перехват."""
        suspect, why = _cert_mitm_suspect(
            "Russian Trusted Root CA", "www.youtube.com")
        self.assertTrue(suspect)
        self.assertIn("перехват", why.lower())

    def test_unknown_ca_on_known_site(self):
        """Известная площадка с незнакомым издателем — перехват."""
        suspect, _why = _cert_mitm_suspect(
            "Some Random Wiretapping Authority", "vk.com")
        self.assertTrue(suspect)

    def test_legit_ca_on_known_site(self):
        """Честный сертификат известного центра — чисто."""
        for issuer, host in (
            ("Google Trust Services", "www.youtube.com"),
            ("DigiCert Inc", "x.com"),
            ("GlobalSign", "vk.com"),
        ):
            with self.subTest(issuer=issuer, host=host):
                suspect, _why = _cert_mitm_suspect(issuer, host)
                self.assertFalse(suspect)

    def test_national_ca_on_own_site(self):
        """Национальная подпись на незнакомом сайте — сигнал-факт.

        Сама по себе она легальна, но проверяющему ссылку важно знать:
        внутри сессии возможен разбор трафика.
        """
        suspect, why = _cert_mitm_suspect(
            "Russian Trusted Root CA", "some-site.ru")
        self.assertTrue(suspect)
        self.assertIn("национальным", why)

    def test_legit_ca_on_unknown_site(self):
        """Незнакомый сайт с обычным Let's Encrypt — чисто."""
        suspect, _why = _cert_mitm_suspect(
            "Let's Encrypt", "some-site.ru")
        self.assertFalse(suspect)

    def test_empty_issuer(self):
        """Без издателя сигнала нет: нечего сравнивать."""
        suspect, _why = _cert_mitm_suspect("", "www.youtube.com")
        self.assertFalse(suspect)


class TestMitmSignalWeight(unittest.TestCase):
    """Сигнал попадает в вердикт и поднимает уровень."""

    def test_signal_registered(self):
        from multitool.linkcheck.analyze import SIGNALS

        codes = {code for code, _w, _t in SIGNALS}
        self.assertIn("mitm_cert", codes)
        weight = next(w for c, w, _t in SIGNALS if c == "mitm_cert")
        # 55 — «подозрительно» само по себе, до «опасно» — вместе
        # с другими признаками.
        self.assertGreaterEqual(weight, 50)

    def test_report_shows_mitm(self):
        from multitool.linkcheck.analyze import NetResult, Verdict
        from multitool.linkcheck.report import build_report

        v = Verdict(url="https://example.com")
        v.net = NetResult(success=True, mitm_suspect=True)
        text = build_report(v)
        self.assertIn("перехват TLS", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
