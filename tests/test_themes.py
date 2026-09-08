#!/usr/bin/env python3
"""Темы оформления панели (с 4.9.7).

Тем четыре: две рабочие (светлая и тёмная) и две «живые» — «Матрица»
и «Реактор». Здесь закреплено то, что ломается незаметно:

* тема не должна тянуть ничего из сети: панель работает на сервере
  без выхода наружу, и подключённый шрифт с чужого домена превратил бы
  её в белый экран с бесконечной загрузкой;
* оформление не должно быть обязательным: если скрипт не выполнится,
  панель обязана остаться рабочей;
* анимации обязаны выключаться по системной настройке.
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

from radar.web import panel  # noqa: E402


class Themes(unittest.TestCase):
    def test_four_themes_declared(self) -> None:
        for key in ("light", "dark", "matrix", "ark"):
            with self.subTest(theme=key):
                self.assertIn(f"'{key}'", panel.THEME_TOGGLE)

    def test_living_themes_have_styles(self) -> None:
        self.assertIn('[data-theme="matrix"]', panel.THEME_STYLE)
        self.assertIn('[data-theme="ark"]', panel.THEME_STYLE)

    def test_unknown_theme_falls_back(self) -> None:
        # Значение из localStorage приходит от браузера, и мусор в нём
        # не должен оставлять страницу без темы вовсе.
        self.assertIn("known.indexOf(saved) < 0", panel.THEME_SCRIPT)

    def test_no_external_resources(self) -> None:
        # Ни шрифтов, ни библиотек со стороны: сервер может стоять
        # без доступа в интернет, и панель обязана открываться.
        blob = panel.PAGE_STYLE + panel.THEME_STYLE + panel.LIVE_SCRIPT
        for needle in ("http://", "https://", "@import", "cdn"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, blob)

    def test_motion_respects_system_setting(self) -> None:
        self.assertIn("prefers-reduced-motion", panel.PAGE_STYLE)
        self.assertIn("prefers-reduced-motion", panel.THEME_STYLE)
        self.assertIn("prefers-reduced-motion", panel.LIVE_SCRIPT)

    def test_animation_stops_when_tab_hidden(self) -> None:
        # Панель часто висит фоновой вкладкой: жечь батарею ради
        # невидимого дождя незачем.
        self.assertIn("visibilitychange", panel.LIVE_SCRIPT)
        self.assertIn("document.hidden", panel.LIVE_SCRIPT)

    def test_decoration_changes_nothing_on_the_server(self) -> None:
        # Оформление обязано быть необязательным: никаких запросов,
        # никакой отправки форм из скрипта оформления.
        for needle in ("fetch(", "XMLHttpRequest", ".submit(", "form."):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, panel.LIVE_SCRIPT)

    def test_counters_only_touch_numbers(self) -> None:
        # Иначе «4.9.7» в карточке превратилось бы в «497».
        self.assertIn("0-9", panel.LIVE_SCRIPT)
        self.assertIn(".metric b", panel.LIVE_SCRIPT)


class Markup(unittest.TestCase):
    def test_page_carries_theme_styles_and_script(self) -> None:
        html = panel._layout("Обзор", '<div class="card">тест</div>', "home",
                             "Суперадминистратор", "superadmin")
        self.assertIn('[data-theme="matrix"]', html)
        self.assertIn("startRain", html)
        self.assertIn('id="theme"', html)

    def test_login_page_has_themes_but_no_animation(self) -> None:
        # На странице входа переключателя нет, значит и оживлять нечего.
        html = panel._login_page("radar_bot")
        self.assertIn('[data-theme="ark"]', html)
        self.assertNotIn("startRain", html)

    def test_layout_keeps_single_root_theme_attribute(self) -> None:
        html = panel._layout("Обзор", "", "home", "Суперадминистратор", "superadmin")
        self.assertEqual(len(re.findall(r"<html[^>]*>", html)), 1)


if __name__ == "__main__":
    unittest.main()
