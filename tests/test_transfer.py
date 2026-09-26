#!/usr/bin/env python3
"""Перенос SQLite ⇄ PostgreSQL (5.9): адреса баз и защита CLI, без сети.

Сам перенос на настоящих базах проверяет tools/db_transfer_check.py
(шаг CI с сервисом PostgreSQL).
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import cli  # noqa: E402
from radar.db import transfer  # noqa: E402


class UrlTests(unittest.TestCase):
    def test_postgres_from_parts(self):
        env = {"DB_USER": "radar", "DB_PASSWORD": "p@ss/w", "DB_HOST": "postgres",
               "DB_PORT": "5432", "DB_NAME": "radar", "DATABASE_URL": ""}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(transfer.url_for("postgres"),
                             "postgresql+asyncpg://radar:p%40ss%2Fw@postgres:5432/radar")

    def test_postgres_from_database_url(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://u:p@h:1/d"}):
            self.assertEqual(transfer.url_for("postgresql"), "postgresql+asyncpg://u:p@h:1/d")

    def test_sqlite_path(self):
        with mock.patch.dict(os.environ, {"DB_FILE": os.path.join(ROOT, "data", "x.db")}):
            self.assertTrue(transfer.url_for("sqlite").startswith("sqlite+aiosqlite:///"))

    def test_unknown_backend(self):
        with self.assertRaises(transfer.TransferError):
            transfer.url_for("mysql")

    def test_password_hidden_in_messages(self):
        self.assertNotIn("secret", transfer._describe("postgresql+asyncpg://u:secret@h:5432/d"))


class CliTests(unittest.TestCase):
    def test_needs_both_ends(self):
        self.assertEqual(cli.main(["db", "copy", "--to", "postgres"]), cli.FAILED)

    def test_replace_requires_yes(self):
        self.assertEqual(cli.main(["db", "copy", "--from", "sqlite", "--to", "postgres",
                                   "--replace"]), cli.NEEDS_YES)


if __name__ == "__main__":
    unittest.main()
