#!/usr/bin/env python3
"""Удаление установки из панели (с 4.9.8.10).

Единственное действие панели, которое нельзя отменить. Поэтому здесь
закреплены не только права, но и то, что отличает его от остальных
кнопок: подтверждение словом и проверка скачанного скрипта до запуска.
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import features, wipe  # noqa: E402


class Confirmation(unittest.TestCase):
    def test_exact_word_required(self):
        self.assertTrue(wipe.confirmed("УДАЛИТЬ"))
        self.assertTrue(wipe.confirmed("  удалить  "))
        for wrong in ("", "да", "удалит", "delete", "УДАЛИТЬ!"):
            with self.subTest(word=wrong):
                self.assertFalse(wipe.confirmed(wrong))


class Readiness(unittest.TestCase):
    def tearDown(self) -> None:
        features.set_local("panel_wipe", False)

    def test_disabled_by_default(self):
        flag = features.resolve("panel_wipe")
        self.assertIsNotNone(flag)
        self.assertFalse(flag.default)

    def test_refuses_while_flag_off(self):
        features.set_local("panel_wipe", False)
        allowed, reason = wipe.ready()
        self.assertFalse(allowed)
        self.assertIn("выключена", reason)

    def test_refuses_without_socket(self):
        features.set_local("panel_wipe", True)
        with mock.patch("os.path.exists", return_value=False):
            allowed, reason = wipe.ready()
        self.assertFalse(allowed)
        self.assertIn("Сокет Docker", reason)

    def test_start_refused_when_not_ready(self):
        features.set_local("panel_wipe", False)
        started, reason = asyncio.run(wipe.start("тест"))
        self.assertFalse(started)
        self.assertIn("выключена", reason)


class Runner(unittest.TestCase):
    def test_script_checks_download_before_running(self):
        script = wipe.SCRIPT
        check = script.index("bash -n /tmp/uninstall.sh")
        run = script.index("bash /tmp/uninstall.sh --yes")
        self.assertLess(check, run)

    def test_script_takes_uninstall_from_release(self):
        self.assertIn("$RADAR_RAW_BASE/$tag/tools/uninstall.sh", wipe.SCRIPT)

    def test_installation_directory_is_explicit(self):
        # Без RADAR_HOME скрипт возьмёт $HOME/radar_bot внутри
        # одноразового контейнера и «удалит» пустоту.
        self.assertIn('RADAR_HOME="$RADAR_HOST_DIR"', wipe.SCRIPT)


class PanelRoutes(unittest.TestCase):
    def setUp(self) -> None:
        with open(os.path.join(ROOT, "radar", "web", "panel.py"),
                  encoding="utf-8") as handle:
            self.source = handle.read()

    def test_page_is_owner_only(self):
        index = self.source.index("async def wipe_page")
        self.assertIn("@owner_only", self.source[index - 40:index])

    def test_start_is_post_with_form_guard(self):
        self.assertIn('web.post("/wipe/start", wipe_start)', self.source)
        self.assertNotIn('web.get("/wipe/start"', self.source)
        index = self.source.index("async def wipe_start")
        body = self.source[index:index + 500]
        self.assertIn('_guarded_form(request, "superadmin")', body)

    def test_word_is_checked_before_starting(self):
        index = self.source.index("async def wipe_start")
        body = self.source[index:index + 800]
        self.assertLess(body.index("wipe.confirmed"), body.index("wipe.start"))

    def test_page_has_a_way_back(self):
        from radar.web import panel

        self.assertIn("wipe", panel._PARENT_PAGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
