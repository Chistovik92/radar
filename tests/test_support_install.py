#!/usr/bin/env python3
"""Статические гарантии установки отдельного бота поддержки."""

from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


class SupportInstallTests(unittest.TestCase):
    def test_compose_service_is_separate_and_has_no_host_access(self) -> None:
        compose = read("docker-compose.yml")
        service = compose.split("  support:\n", 1)[1].split("\n  #", 1)[0]
        self.assertIn('profiles: ["support"]', service)
        self.assertIn("container_name: support_container", service)
        self.assertIn("image: support_image", service)
        self.assertIn("./data/support:/app/data", service)
        self.assertIn("SUPPORT_AI: ${SUPPORT_AI:-0}", service)
        self.assertNotIn("ports:", service)
        self.assertNotIn("docker.sock", service)

    def test_installer_keeps_main_bot_independent(self) -> None:
        source = read("tools/install.template.sh")
        self.assertIn("SUPPORT_INSTALL=false", source)
        self.assertIn("warn \"Образ поддержки не собран; основной бот будет установлен независимо\"", source)
        self.assertIn("$COMPOSE --profile support up -d support", source)
        self.assertNotIn('COMPOSE_ARGS="$COMPOSE_ARGS --profile support"', source)
        self.assertIn("Токен поддержки должен отличаться от BOT_TOKEN", source)

    def test_manifest_contains_every_support_source(self) -> None:
        from tools import build_installer

        expected = {
            os.path.relpath(os.path.join(directory, name), ROOT).replace("\\", "/")
            for directory, _, files in os.walk(os.path.join(ROOT, "support"))
            for name in files
            if name.endswith((".py", ".txt", ".md", ".example")) or name == "Dockerfile"
        }
        self.assertEqual(expected - set(build_installer.MANIFEST), set())

    def test_generated_installer_contains_support(self) -> None:
        installer = read("install.sh")
        for marker in ("SUPPORT_BOT_TOKEN", "support_container", "support_image",
                       "support/requirements-ai.txt", "support/README.md"):
            self.assertIn(marker, installer)


if __name__ == "__main__":
    unittest.main()
