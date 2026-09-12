#!/usr/bin/env python3
"""Панель с телефона (с 4.9.8.8).

Закреплено то, что ломается незаметно и проверяется только на живом
экране, до которого руки доходят последними:

* широкие таблицы обязаны прокручиваться вбок, а не схлопываться
  в нечитаемые колонки;
* прокрутка задана ТАБЛИЦЕ, а не карточке: у темы «Реактор» карточка
  носит уголки-скобки псевдоэлементами за своей границей, и overflow
  на .card срезал бы их вместе с углами;
* список пользователей на узком экране разворачивается в карточки,
  и подписи полей берутся из разметки, а не дублируются в CSS;
* элементы управления не мельче пальца.
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


class Breakpoints(unittest.TestCase):
    def test_both_widths_declared(self):
        self.assertIn("@media (max-width: 780px)", panel.PAGE_STYLE)
        self.assertIn("@media (max-width: 560px)", panel.PAGE_STYLE)

    def test_sections_get_their_own_row(self):
        # Иначе разделы зажаты между названием и кнопкой темы.
        self.assertIn("nav { order:3; flex:1 0 100%", panel.PAGE_STYLE)

    def test_viewport_is_declared(self):
        html = panel._layout("Обзор", "", "home", "Суперадминистратор", "superadmin")
        self.assertIn('name="viewport"', html)


class WideTables(unittest.TestCase):
    def test_table_scrolls_not_the_card(self):
        # Суть ограничения: overflow на .card срезал бы уголки «Реактора».
        self.assertIn("table:not(.stack) { display:block; overflow-x:auto",
                      panel.PAGE_STYLE)
        self.assertNotIn(".card { overflow-x:auto", panel.PAGE_STYLE)

    def test_columns_keep_their_widths(self):
        # display:block на самой таблице отключает расчёт колонок —
        # без возврата display:table у tbody они схлопываются.
        self.assertIn("table:not(.stack) > tbody { display:table", panel.PAGE_STYLE)

    def test_sticky_header_switched_off(self):
        self.assertIn("th { position:static; }", panel.PAGE_STYLE)


class StackedList(unittest.TestCase):
    def test_stack_rules_exist(self):
        self.assertIn("table.stack, table.stack > tbody", panel.PAGE_STYLE)
        self.assertIn("table.stack > thead { display:none; }", panel.PAGE_STYLE)

    def test_field_name_comes_from_markup(self):
        self.assertIn("content:attr(data-label)", panel.PAGE_STYLE)

    def test_users_body_emits_labels(self):
        source = open(os.path.join(ROOT, "radar", "web", "panel.py"),
                      encoding="utf-8").read()
        start = source.index("def _users_body")
        end = source.index("def _note", start)
        block = source[start:end]
        self.assertIn('<table class="stack">', block)
        for column in ("Ключ", "Роль", "Локаций", "Города", "Время"):
            with self.subTest(column=column):
                self.assertIn(f'data-label="{column}"', block)


class TouchTargets(unittest.TestCase):
    def test_controls_are_finger_sized(self):
        self.assertIn("nav a, .subnav a, button, #theme", panel.PAGE_STYLE)
        self.assertIn("min-height:40px", panel.PAGE_STYLE)
        self.assertIn("button.ghost { min-height:36px; }", panel.PAGE_STYLE)

    def test_install_log_does_not_eat_the_screen(self):
        self.assertIn("pre.log { max-height:260px; }", panel.PAGE_STYLE)


class ThemesStayIntact(unittest.TestCase):
    """Темы на телефоне не урезаются — решение автора. Проверяем, что
    мобильная вёрстка их не отключила походя."""

    def test_living_themes_not_disabled_on_narrow_screens(self):
        narrow = panel.PAGE_STYLE[panel.PAGE_STYLE.index("@media (max-width: 560px)"):]
        for needle in ("#rain { display:none", "backdrop-filter:none"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, narrow)

    def test_theme_styles_still_target_tables(self):
        self.assertIn('[data-theme="matrix"] th', panel.THEME_STYLE)
        self.assertIn('[data-theme="ark"] th', panel.THEME_STYLE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
