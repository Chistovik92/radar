#!/usr/bin/env python3
"""Обновление системы из панели (4.9.6).

Кнопка запускает не произвольную команду, а один заранее заданный
сценарий, и только при трёх выполненных условиях: возможность включена,
сокет Docker проброшен, путь установки на хосте передан. Здесь закреплены
именно они — потому что каждое несоблюдённое условие выглядит на живом
сервере одинаково («кнопка не работает»), а причины разные.
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

from radar import features, updater  # noqa: E402


class Readiness(unittest.TestCase):
    def tearDown(self) -> None:
        features.set_local("panel_update", False)

    def test_disabled_by_default(self) -> None:
        # Сокет Docker в контейнере равносилен root на хосте: возможность
        # обязана быть выключенной, пока её не включили руками.
        flag = features.resolve("panel_update")
        self.assertIsNotNone(flag)
        self.assertFalse(flag.default)

    def test_refuses_while_flag_off(self) -> None:
        features.set_local("panel_update", False)
        allowed, reason = updater.ready()
        self.assertFalse(allowed)
        self.assertIn("выключена", reason)

    def test_refuses_without_socket(self) -> None:
        features.set_local("panel_update", True)
        with mock.patch("os.path.exists", return_value=False):
            allowed, reason = updater.ready()
        self.assertFalse(allowed)
        self.assertIn("Сокет Docker", reason)

    def test_refuses_without_host_dir(self) -> None:
        features.set_local("panel_update", True)
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch.dict(os.environ, {"RADAR_HOST_DIR": ""}, clear=False):
            allowed, reason = updater.ready()
        self.assertFalse(allowed)
        self.assertIn("RADAR_HOST_DIR", reason)

    def test_ready_when_all_three_hold(self) -> None:
        features.set_local("panel_update", True)
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch.dict(os.environ, {"RADAR_HOST_DIR": "/root/radar_bot"}):
            allowed, reason = updater.ready()
        self.assertTrue(allowed, reason)

    def test_start_refused_when_not_ready(self) -> None:
        features.set_local("panel_update", False)
        started, reason = asyncio.run(updater.start("тест"))
        self.assertFalse(started)
        self.assertIn("выключена", reason)


class RunnerRecipe(unittest.TestCase):
    """Сценарий исполнителя: важны детали, которые ломают обновление молча."""

    def test_installer_gets_no_questions(self) -> None:
        # Без RADAR_ASKED установщик ждал бы ответа у терминала, которого
        # у исполнителя нет, и обновление зависло бы на первом вопросе.
        source = open(os.path.join(ROOT, "radar", "updater.py"),
                      encoding="utf-8").read()
        self.assertIn('"RADAR_ASKED=1"', source)
        self.assertIn('"NO_ANIMATION=1"', source)

    def test_host_path_is_mounted_as_itself(self) -> None:
        # Каталог обязан попасть в исполнитель по своему же пути: иначе
        # docker compose передаст демону пути, которых на хосте нет,
        # и тома бота отвалятся при первом же обновлении.
        source = open(os.path.join(ROOT, "radar", "updater.py"),
                      encoding="utf-8").read()
        self.assertIn('f"{directory}:{directory}"', source)

    def test_script_runs_installer_with_bash(self) -> None:
        # install.sh написан на bash, а в образе docker:cli его нет.
        self.assertIn("apk add --no-cache bash", updater.SCRIPT)
        self.assertIn("bash install.sh", updater.SCRIPT)

    def test_script_keeps_system_packages_alone(self) -> None:
        # Обновлять пакеты системы изнутри контейнера бессмысленно.
        self.assertIn("--skip-updates", updater.SCRIPT)

    def test_compose_is_ensured(self) -> None:
        self.assertIn("docker compose version", updater.SCRIPT)


class PanelRoutes(unittest.TestCase):
    """Маршруты обновления закрыты правами суперадминистратора."""

    def setUp(self) -> None:
        self.source = open(os.path.join(ROOT, "radar", "web", "panel.py"),
                           encoding="utf-8").read()

    def test_page_is_owner_only(self) -> None:
        index = self.source.index("async def update_page")
        self.assertIn("@owner_only", self.source[index - 40:index])

    def test_start_is_post_with_form_guard(self) -> None:
        # Запуск обновления обязан идти POST-ом с токеном формы: по GET
        # его можно было бы вызвать чужой страницей через редирект.
        self.assertIn('web.post("/update/start", update_start)', self.source)
        self.assertNotIn('web.get("/update/start"', self.source)
        index = self.source.index("async def update_start")
        body = self.source[index:index + 400]
        self.assertIn('_guarded_form(request, "superadmin")', body)

    def test_menu_item_follows_the_flag(self) -> None:
        self.assertIn('if features.enabled("panel_update")', self.source)


if __name__ == "__main__":
    unittest.main()
