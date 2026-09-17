#!/usr/bin/env python3
"""Полное удаление и доставка скриптов обслуживания (с 4.9.8.10).

Главный тест здесь — инвариант, а не текст: каждый контейнер, который
поднимает docker-compose.yml, обязан попадать под удаление. Именно это
и разъехалось: список в uninstall.sh писался при четырёх контейнерах,
а RustDesk, сертификат и исполнитель обновления появились позже —
и переживали «полное удаление» вместе со своими данными.
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


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class Coverage(unittest.TestCase):
    def setUp(self) -> None:
        self.script = read("tools", "uninstall.sh")
        self.compose = read("docker-compose.yml")

    def test_every_compose_container_is_removed(self):
        names = re.findall(r"container_name:\s*(\S+)", self.compose)
        self.assertTrue(names, "в compose не нашлось ни одного container_name")
        for name in names:
            with self.subTest(container=name):
                self.assertIn(name, self.script)

    def test_updater_container_is_removed_too(self):
        # Он создаётся не через compose, а напрямую через Engine API,
        # поэтому предыдущий тест его не увидит.
        from radar import updater

        self.assertIn(updater.CONTAINER, self.script)

    def test_certificate_volume_is_removed(self):
        # В томе Caddy лежит выданный сертификат и ключ к нему.
        self.assertIn("caddy", self.script)

    def test_wiper_does_not_kill_itself(self):
        # Исполнитель удаления не должен попадать под собственную
        # команду: иначе он умрёт на середине и оставит машину
        # в состоянии хуже обоих исходов.
        from radar import wipe

        self.assertNotIn(wipe.CONTAINER, self.script)


class Delivery(unittest.TestCase):
    """Скрипты обслуживания едут на сервер вместе с кодом."""

    def setUp(self) -> None:
        self.builder = read("tools", "build_installer.py")

    def test_scripts_are_in_manifest(self):
        for name in ("tools/uninstall.sh", "tools/restore.sh",
                     "tools/radarctl.sh"):
            with self.subTest(name=name):
                self.assertIn(f'"{name}"', self.builder)

    def test_cli_modules_are_in_manifest(self):
        for name in ("radar/cli.py", "radar/__main__.py", "radar/wipe.py"):
            with self.subTest(name=name):
                self.assertIn(f'"{name}"', self.builder)

    def test_help_does_not_require_docker(self):
        # Справку читают и на своей машине, где Docker не стоит.
        script = read("tools", "radarctl.sh")
        help_at = script.index('""|-h|--help|help')
        docker_at = script.index("command -v docker")
        self.assertLess(help_at, docker_at)


if __name__ == "__main__":
    unittest.main(verbosity=2)
