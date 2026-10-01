#!/usr/bin/env python3
"""Консоль: язык, пользователи, ключи, журналы, статистика (с 5.9.3.1).

Закреплено то, что ломается тихо: выбор языка, права по ролям (суперадмина
не тронуть), отказ без --yes, проверка значений ключей до записи и то,
что секрет не печатается.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import cli, clitext, config, secrets, storage  # noqa: E402


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(["--local", "--lang", "en"] + argv)
    return code, out.getvalue(), err.getvalue()


class Language(unittest.TestCase):
    def tearDown(self):
        clitext.set_lang("ru")

    def test_detect_order(self):
        self.assertEqual(clitext.detect(["--lang", "en"], {"RADAR_LANG": "ru"}), "en")
        self.assertEqual(clitext.detect(["--lang=ru"], {"LANG": "en_US.UTF-8"}), "ru")
        self.assertEqual(clitext.detect([], {"RADAR_LANG": "en"}), "en")
        self.assertEqual(clitext.detect([], {"LANG": "en_US.UTF-8"}), "en")
        self.assertEqual(clitext.detect([], {"LANG": "ru_RU.UTF-8"}), "ru")

    def test_default_is_russian(self):
        # В образе Python LANG=C.UTF-8: это «не задано», а не «английский».
        self.assertEqual(clitext.detect([], {}), "ru")
        self.assertEqual(clitext.detect([], {"LANG": "C.UTF-8"}), "ru")
        self.assertEqual(clitext.detect([], {"LANG": "POSIX"}), "ru")

    def test_unknown_language_ignored(self):
        self.assertEqual(clitext.detect(["--lang", "xx"], {}), "ru")

    def test_pair_follows_language(self):
        clitext.set_lang("en")
        self.assertEqual(clitext.L("да", "yes"), "yes")
        clitext.set_lang("ru")
        self.assertEqual(clitext.L("да", "yes"), "да")

    def test_help_is_in_chosen_language(self):
        clitext.set_lang("en")
        self.assertIn("Manage Radar", cli.build_parser().format_help())
        clitext.set_lang("ru")
        self.assertIn("Управление", cli.build_parser().format_help())

    def test_version_is_language_neutral(self):
        from radar import __version__

        code, out, _ = run(["version"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(out.strip(), __version__)


class FakeStore:
    """Подменяет хранилище: без базы, но с настоящими правилами ролей."""

    def __init__(self, people):
        self.people = people
        self.saved = 0
        self.dropped: list[str] = []
        self._orig = {}

    def __enter__(self):
        for name, func in {
            "users": lambda: self.people,
            "get_user": lambda uid: self.people.get(str(uid)),
            "save": self._save,
            "drop_user": self._drop,
        }.items():
            self._orig[name] = getattr(storage, name)
            setattr(storage, name, func)

        async def passthrough(action):
            result = action()
            return await result if asyncio.iscoroutine(result) else result

        self._wrap = cli._with_storage
        cli._with_storage = passthrough
        return self

    def __exit__(self, *exc):
        for name, func in self._orig.items():
            setattr(storage, name, func)
        cli._with_storage = self._wrap

    async def _save(self):
        self.saved += 1

    async def _drop(self, uid):
        self.dropped.append(str(uid))
        self.people.pop(str(uid), None)


def people():
    return {
        "1": {"role": "superadmin", "locs": []},
        "2": {"role": "user", "username": "bob", "tz": "", "weather_time": "08:00",
              "weather_mode": "interval", "sos_contacts": ["+79990000000"],
              "locs": [{"id": "a1", "name": "Дом", "city": "Саратов"}]},
        "3": {"role": "moderator", "locs": []},
    }


class Users(unittest.TestCase):
    def test_role_change_and_save(self):
        with FakeStore(people()) as store:
            code, out, _ = run(["users", "role", "2", "moderator"])
            self.assertEqual(code, cli.OK)
            self.assertEqual(store.people["2"]["role"], "moderator")
            self.assertEqual(store.saved, 1)
            self.assertIn("moderator", out)

    def test_superadmin_cannot_be_touched(self):
        with FakeStore(people()) as store:
            code, _o, _e = run(["users", "role", "1", "user"])
            self.assertEqual(code, cli.FAILED)
            self.assertEqual(store.people["1"]["role"], "superadmin")
            code, _o, _e = run(["users", "delete", "1", "--yes"])
            self.assertEqual(code, cli.FAILED)
            self.assertEqual(store.dropped, [])

    def test_superadmin_role_cannot_be_granted(self):
        with FakeStore(people()) as store:
            code, _o, _e = run(["users", "role", "2", "superadmin"])
            self.assertEqual(code, cli.FAILED)
            self.assertEqual(store.people["2"]["role"], "user")

    def test_delete_needs_yes(self):
        with FakeStore(people()) as store:
            code, _o, err = run(["users", "delete", "2"])
            self.assertEqual(code, cli.NEEDS_YES)
            self.assertIn("--yes", err)
            self.assertEqual(store.dropped, [])
            code, _o, _e = run(["users", "delete", "2", "--yes"])
            self.assertEqual(code, cli.OK)
            self.assertEqual(store.dropped, ["2"])

    def test_unknown_user(self):
        with FakeStore(people()):
            code, _o, err = run(["users", "show", "99"])
            self.assertEqual(code, cli.FAILED)
            self.assertIn("not found", err)

    def test_show_hides_private_fields(self):
        with FakeStore(people()):
            code, out, _ = run(["users", "show", "2", "--json"])
            self.assertEqual(code, cli.OK)
            text = out
            self.assertNotIn("+7999", text)
            self.assertNotIn("sos_contacts", text)
            card = json.loads(text)
            self.assertEqual(card["locations"][0]["city"], "Саратов")

    def test_time_validates(self):
        with FakeStore(people()) as store:
            code, _o, _e = run(["users", "time", "2", "--weather-time", "25:99"])
            self.assertEqual(code, cli.FAILED)
            code, _o, _e = run(["users", "time", "2", "--weather-time", "07:30"])
            self.assertEqual(code, cli.OK)
            self.assertEqual(store.people["2"]["weather_time"], "07:30")
            self.assertEqual(store.people["2"]["weather_mode"], "time")

    def test_list_filter(self):
        with FakeStore(people()):
            code, out, _ = run(["users", "list", "--role", "moderator", "--json"])
            self.assertEqual(code, cli.OK)
            self.assertEqual([r["key"] for r in json.loads(out)], ["3"])


class Keys(unittest.TestCase):
    def setUp(self):
        self.written: dict[str, str] = {}
        self._orig = (secrets.write, secrets.writable, secrets.get)
        secrets.write = lambda key, value: self.written.__setitem__(key, value) or True
        secrets.writable = lambda: True
        self.values = {}
        secrets.get = lambda key: self.values.get(key, "")

    def tearDown(self):
        secrets.write, secrets.writable, secrets.get = self._orig

    def int_key(self):
        return next(s for s in secrets.SETTINGS if s.kind == "int" and s.high is not None)

    def test_list_does_not_crash_and_masks(self):
        # До 5.9.3.1 команда обращалась к несуществующему полю name.
        code, out, _ = run(["keys", "list", "--json"])
        self.assertEqual(code, cli.OK)
        self.assertTrue(json.loads(out))

    def test_get_masks_secret(self):
        secret = next(s for s in secrets.SETTINGS if s.secret)
        self.values[secret.key] = "AIzaSyVERYSECRETVALUE1234567890"
        code, out, _ = run(["keys", "get", secret.key])
        self.assertEqual(code, cli.OK)
        self.assertNotIn("VERYSECRETVALUE", out)

    def test_set_rejects_bad_number(self):
        item = self.int_key()
        code, _o, err = run(["keys", "set", item.key, "abc"])
        self.assertEqual(code, cli.FAILED)
        self.assertTrue(err)
        self.assertEqual(self.written, {})

    def test_set_rejects_out_of_bounds(self):
        item = self.int_key()
        code, _o, _e = run(["keys", "set", item.key, str(item.high + 1)])
        self.assertEqual(code, cli.FAILED)
        self.assertEqual(self.written, {})

    def test_set_valid_and_unset(self):
        item = self.int_key()
        value = str(item.high if item.low is None else item.low)
        code, _o, _e = run(["keys", "set", item.key, value])
        self.assertEqual(code, cli.OK)
        self.assertEqual(self.written[item.key], value)
        code, _o, _e = run(["keys", "unset", item.key])
        self.assertEqual(code, cli.OK)
        self.assertEqual(self.written[item.key], "")

    def test_set_does_not_echo_secret(self):
        secret = next(s for s in secrets.SETTINGS if s.secret and s.kind == "text")
        code, out, err = run(["keys", "set", secret.key, "TOPSECRETVALUE0123456789"])
        self.assertEqual(code, cli.OK)
        self.assertNotIn("TOPSECRETVALUE0123456789", out + err)

    def test_unknown_key(self):
        code, _o, err = run(["keys", "get", "NO_SUCH_KEY"])
        self.assertEqual(code, cli.FAILED)
        self.assertIn("NO_SUCH_KEY", err)

    def test_extra_validation_shared_with_panel(self):
        # Тарифы проверяются теми же правилами, что в панели.
        self.assertTrue(secrets.validate_extra("DIGEST_PLANS", "nonsense"))
        self.assertEqual(secrets.validate_extra("DIGEST_PLANS", "30:150, 90:400"), "")
        from radar.web import panel

        self.assertEqual(panel._validate_setting("DIGEST_PLANS", "nonsense"),
                         secrets.validate_extra("DIGEST_PLANS", "nonsense"))


class LogsAndAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._dir = config.LOG_DIR
        config.LOG_DIR = self.tmp.name

    def tearDown(self):
        config.LOG_DIR = self._dir
        self.tmp.cleanup()

    def test_logs_clear_needs_yes(self):
        code, _o, err = run(["logs", "clear"])
        self.assertEqual(code, cli.NEEDS_YES)
        self.assertIn("--yes", err)

    def test_logs_tail_reads_file_and_rejects_path_escape(self):
        with open(os.path.join(self.tmp.name, "bot.log"), "w", encoding="utf-8") as h:
            h.write("one\ntwo\nthree\n")
        code, out, _ = run(["logs", "tail", "--lines", "2"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(out, "two\nthree\n")
        code, _o, _e = run(["logs", "tail", "../secret"])
        self.assertEqual(code, cli.FAILED)

    def test_audit_tail_reads_file_newest_first(self):
        with open(os.path.join(self.tmp.name, "audit.log"), "w", encoding="utf-8") as h:
            h.write("01.10 10:00:00\tа\tпервое\tx\n01.10 10:00:01\tб\tвторое\ty\n")
        code, out, _ = run(["audit", "tail", "--json"])
        self.assertEqual(code, cli.OK)
        rows = json.loads(out)
        self.assertEqual([r["action"] for r in rows], ["второе", "первое"])

    def test_audit_clear_needs_yes(self):
        code, _o, err = run(["audit", "clear"])
        self.assertEqual(code, cli.NEEDS_YES)
        self.assertIn("--yes", err)

    def test_console_actions_are_audited(self):
        from radar import cli_admin

        cli_admin.audit("проверка", "деталь")
        with open(os.path.join(self.tmp.name, "audit.log"), encoding="utf-8") as h:
            self.assertIn("консоль\tпроверка\tдеталь", h.read())


class Stats(unittest.TestCase):
    def test_stats_standalone_says_counters_are_bot_only(self):
        with FakeStore(people()):
            orig = (storage.channels, storage.rss_feeds, storage.pending)
            storage.channels, storage.rss_feeds, storage.pending = (
                lambda: [], lambda: [], lambda: [])
            try:
                code, out, _ = run(["stats", "--json"])
            finally:
                storage.channels, storage.rss_feeds, storage.pending = orig
            self.assertEqual(code, cli.OK)
            data = json.loads(out)
            self.assertEqual(data["users"], 3)
            self.assertFalse(data["live"])
            self.assertNotIn("monitor", data)


class Parity(unittest.TestCase):
    def test_parity_table_is_complete(self):
        """Новая команда бота или маршрут панели без решения про консоль —
        ошибка: иначе расхождение копится молча."""
        import lint_cli_parity

        out = io.StringIO()
        with redirect_stdout(out):
            code = lint_cli_parity.main()
        self.assertEqual(code, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
