#!/usr/bin/env python3
"""Командная строка (с 4.9.8.10).

Закреплено то, что ломается тихо: разрушающее действие без --yes,
машиночитаемый вывод и коды возврата. Последнее важнее, чем кажется:
командную строку ставят в cron, а там об ошибке узнают только по коду.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import cli  # noqa: E402


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class Parser(unittest.TestCase):
    def test_every_subcommand_parses(self):
        parser = cli.build_parser()
        for argv in (
            ["sources", "list"], ["users", "list"], ["features", "list"],
            ["keys", "list"], ["backup", "list"], ["db", "size"],
            ["links", "list"], ["files", "list"],
            ["rustdesk", "info"], ["doctor"], ["version"],
        ):
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertTrue(callable(args.func))

    def test_json_works_on_both_sides(self):
        # «radar --json version» помнит не каждый, «radar version --json»
        # набирается само — работать обязаны обе формы.
        parser = cli.build_parser()
        self.assertTrue(parser.parse_args(["--json", "version"]).json)
        self.assertTrue(parser.parse_args(["version", "--json"]).json)
        self.assertFalse(parser.parse_args(["version"]).json)

    def test_unknown_subcommand_is_rejected(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["nonsense"])


class Output(unittest.TestCase):
    def test_version_plain_and_json(self):
        from radar import __version__

        code, out, _ = run(["version"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(out.strip(), __version__)

        code, out, _ = run(["version", "--json"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(json.loads(out)["version"], __version__)


class Destructive(unittest.TestCase):
    """Разрушающее без --yes не делает ничего и говорит об этом кодом."""

    def test_db_vacuum_needs_yes(self):
        code, _out, err = run(["db", "vacuum"])
        self.assertEqual(code, cli.NEEDS_YES)
        self.assertIn("--yes", err)

    def test_links_clear_needs_yes(self):
        code, _out, err = run(["links", "clear"])
        self.assertEqual(code, cli.NEEDS_YES)
        self.assertIn("--yes", err)

    def test_rustdesk_stop_needs_yes(self):
        # Отказ по --yes обязан идти РАНЬШЕ обращения к Docker: иначе
        # проверка зависит от окружения, а не от намерения.
        from radar import rustdesk

        was = rustdesk.ready
        rustdesk.ready = lambda: (True, "")
        try:
            code, _out, err = run(["rustdesk", "stop"])
        finally:
            rustdesk.ready = was
        self.assertEqual(code, cli.NEEDS_YES)
        self.assertIn("--yes", err)

    def test_codes_are_distinct(self):
        # cron отличает «не сделано, потому что не подтвердили»
        # от «сломалось» только по коду.
        self.assertEqual(cli.OK, 0)
        self.assertNotEqual(cli.FAILED, cli.NEEDS_YES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
