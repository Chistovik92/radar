#!/usr/bin/env python3
"""Консоль: подписки, VPN-панели и доступы, партнёры, перезапуск (с 5.9.8).

Проверяется то, что консоль зовёт те же функции, что панель (а не повторяет
их), не печатает секреты и не делает разрушающего без --yes.
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import (cli, cli_ops, config, filedrop, ops, partners, promo, redeem,  # noqa: E402
                   storage, subscription, vpn, vpnslots)


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(["--local", "--lang", "en"] + argv)
    return code, out.getvalue(), err.getvalue()


class Store:
    """Подмена хранилища и базы: настоящие правила, без файлов."""

    def __init__(self, people=None):
        self.people = people if people is not None else {}
        self.saved = 0

    def __enter__(self):
        self._orig = {n: getattr(storage, n) for n in ("users", "get_user", "save")}
        storage.users = lambda: self.people
        storage.get_user = lambda uid: self.people.get(str(uid))

        async def save(uid=None):
            self.saved += 1

        storage.save = save

        async def passthrough(action):
            result = action()
            return await result if asyncio.iscoroutine(result) else result

        self._wrap = cli._with_storage
        cli._with_storage = passthrough
        self._tmp = tempfile.TemporaryDirectory()
        self._log = config.LOG_DIR
        config.LOG_DIR = self._tmp.name           # журнал действий — во временный каталог
        return self

    def __exit__(self, *exc):
        for name, func in self._orig.items():
            setattr(storage, name, func)
        cli._with_storage = self._wrap
        config.LOG_DIR = self._log
        self._tmp.cleanup()

    def audit_text(self) -> str:
        path = os.path.join(self._tmp.name, "audit.log")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as handle:
            return handle.read()


class Subs(unittest.TestCase):
    def test_grant_and_list_and_revoke(self):
        with Store({"7": {"role": "user", "username": "bob"}}) as store:
            code, out, _ = run(["subs", "grant", "7", "30"])
            self.assertEqual(code, cli.OK)
            self.assertTrue(subscription.paid(store.people["7"]))
            code, out, _ = run(["subs", "list", "--json"])
            rows = json.loads(out)
            self.assertEqual([r["uid"] for r in rows], ["7"])
            self.assertTrue(rows[0]["paid"])
            self.assertIn("подписка выдана", store.audit_text())
            code, _o, err = run(["subs", "revoke", "7"])
            self.assertEqual(code, cli.NEEDS_YES)
            self.assertTrue(subscription.paid(store.people["7"]))
            code, _o, _e = run(["subs", "revoke", "7", "--yes"])
            self.assertEqual(code, cli.OK)
            self.assertFalse(subscription.paid(store.people["7"]))

    def test_grant_validates_days_and_person(self):
        with Store({"7": {"role": "user"}}):
            self.assertEqual(run(["subs", "grant", "7", "abc"])[0], cli.FAILED)
            self.assertEqual(run(["subs", "grant", "7", "99999"])[0], cli.FAILED)
            self.assertEqual(run(["subs", "grant", "404", "5"])[0], cli.FAILED)
            self.assertEqual(run(["subs", "grant", "7"])[0], cli.FAILED)

    def test_codes(self):
        codes: list[dict] = []

        async def load():
            return list(codes)

        async def add(text, days=30):
            fresh = [c for c in text.split() if len(c) >= 5]
            codes.extend({"code": c, "days": days} for c in fresh)
            return fresh, []

        async def drop(code):
            found = [c for c in codes if c["code"] == code]
            for item in found:
                codes.remove(item)
            return bool(found)

        with Store(), mock.patch.object(redeem, "load", load), \
                mock.patch.object(redeem, "add", add), mock.patch.object(redeem, "drop", drop):
            code, out, _ = run(["subs", "code-add", "ABCDE-1", "ABCDE-2", "--days", "7"])
            self.assertEqual(code, cli.OK)
            self.assertEqual([c["days"] for c in codes], [7, 7])
            code, out, _ = run(["subs", "codes", "--json"])
            self.assertEqual([r["code"] for r in json.loads(out)], ["ABCDE-1", "ABCDE-2"])
            self.assertEqual(run(["subs", "code-drop", "ABCDE-1"])[0], cli.OK)
            self.assertEqual(run(["subs", "code-drop", "NOPE"])[0], cli.FAILED)
            self.assertEqual(run(["subs", "code-add"])[0], cli.FAILED)


class Vpn(unittest.TestCase):
    def slots(self):
        data = {1: {"KIND": "3xui", "TITLE": "Main", "URL": "https://p:1", "TOKEN": "SECRETTOKEN",
                    "PASS": ""}}
        saved: dict = {}

        async def issued_on(number):
            return 3

        patches = [
            mock.patch.object(vpnslots, "numbers", lambda: range(1, 4)),
            mock.patch.object(vpnslots, "configured", lambda n: n in data),
            mock.patch.object(vpnslots, "read", lambda n: dict(data[n])),
            mock.patch.object(vpnslots, "issued_on", issued_on),
            mock.patch.object(vpnslots, "save",
                              lambda n, form: saved.update({n: dict(form)}) or ""),
        ]
        return data, saved, patches

    def test_panels_list_never_prints_secrets(self):
        data, saved, patches = self.slots()
        for p in patches:
            p.start()
        try:
            with Store():
                code, out, _ = run(["vpn", "panels", "--json"])
                plain = run(["vpn", "panels"])[1]
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(code, cli.OK)
        self.assertNotIn("SECRETTOKEN", out + plain)
        row = json.loads(out)[0]
        self.assertEqual((row["slot"], row["kind"], row["issued"]), (1, "3xui", 3))
        self.assertTrue(row["secret_set"])

    def test_panel_save_validates_fields(self):
        data, saved, patches = self.slots()
        for p in patches:
            p.start()
        try:
            with Store() as store:
                self.assertEqual(run(["vpn", "panel-save", "2", "--set", "NOPE=1"])[0], cli.FAILED)
                self.assertEqual(run(["vpn", "panel-save", "2", "--set", "broken"])[0], cli.FAILED)
                self.assertEqual(run(["vpn", "panel-save", "x", "--set", "KIND=3xui"])[0], cli.FAILED)
                code, _o, _e = run(["vpn", "panel-save", "2", "--set", "KIND=marzban",
                                    "--set", "URL=https://m:8000"])
                self.assertEqual(code, cli.OK)
                self.assertEqual(saved[2]["KIND"], "marzban")
                self.assertIn("VPN-панель сохранена", store.audit_text())
                self.assertNotIn("https://m:8000", store.audit_text())   # адрес в журнал не идёт
        finally:
            for p in patches:
                p.stop()

    def test_panel_remove_needs_yes_and_warns_about_issued(self):
        data, saved, patches = self.slots()
        removed = []
        patches.append(mock.patch.object(vpnslots, "remove", lambda n: removed.append(n) or True))
        for p in patches:
            p.start()
        try:
            with Store():
                code, _o, err = run(["vpn", "panel-remove", "1"])
                self.assertEqual(code, cli.NEEDS_YES)
                self.assertIn("3", err)                      # сколько выдано на панели
                self.assertEqual(removed, [])
                self.assertEqual(run(["vpn", "panel-remove", "1", "--yes"])[0], cli.OK)
                self.assertEqual(removed, [1])
        finally:
            for p in patches:
                p.stop()

    def test_access_actions_call_the_panels_function(self):
        calls = []

        def record(name):
            async def fake(*args, **kwargs):
                calls.append((name, args))
                return {} if name == "issue" else None
            return fake

        patches = [mock.patch.object(vpn, name, record(name))
                   for name in ("issue", "deny", "extend", "set_enabled", "revoke")]
        for p in patches:
            p.start()
        try:
            with Store() as store:
                self.assertEqual(run(["vpn", "issue", "7", "--slot", "1", "--slot", "2"])[0], cli.OK)
                self.assertEqual(run(["vpn", "issue", "7"])[0], cli.FAILED)       # ни одной панели
                self.assertEqual(run(["vpn", "deny", "7"])[0], cli.OK)
                self.assertEqual(run(["vpn", "extend", "7", "1", "30"])[0], cli.OK)
                self.assertEqual(run(["vpn", "extend", "7", "1", "99999"])[0], cli.FAILED)
                self.assertEqual(run(["vpn", "off", "7", "1"])[0], cli.OK)
                self.assertEqual(run(["vpn", "on", "7", "1"])[0], cli.OK)
                self.assertEqual(run(["vpn", "revoke", "7", "1"])[0], cli.NEEDS_YES)
                self.assertEqual(run(["vpn", "revoke", "7", "1", "--yes"])[0], cli.OK)
        finally:
            for p in patches:
                p.stop()
        names = [name for name, _ in calls]
        self.assertEqual(names, ["issue", "deny", "extend", "set_enabled", "set_enabled",
                                 "revoke"])
        self.assertEqual(calls[0][1][1], ["1", "2"])              # выбранные панели
        self.assertEqual(calls[0][1][3], "superadmin")             # консоль — роль владельца
        self.assertFalse(calls[4][1][2] is False)                  # on → True

    def test_app_revoke(self):
        from radar import appapi

        seen = []

        async def revoke(uid, device=None):
            seen.append((uid, device))
            return 2

        with Store(), mock.patch.object(appapi, "revoke", revoke):
            code, out, _ = run(["vpn", "app-revoke", "7", "--device", "d1", "--json"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(seen, [("7", "d1")])
        self.assertEqual(json.loads(out)["revoked"], 2)

    def test_old_vpn_commands_still_parse(self):
        parser = cli.build_parser()
        for argv in (["vpn", "check"], ["vpn", "selftest", "--yes"]):
            self.assertTrue(callable(parser.parse_args(argv).func))


def project(slug="shop", **extra):
    base = {"slug": slug, "title": "Shop", "url": "https://shop.example", "description": "Магазин",
            "icon": "🛒", "order": 5, "visible": True, "clicks": 9}
    base.update(extra)
    return partners.Project.from_dict(base)


class Partners(unittest.TestCase):
    def run_with(self, projects, argv):
        saved = []

        async def load():
            return list(projects)

        async def save(items):
            saved.append(list(items))

        with Store() as store, mock.patch.object(partners, "load", load), \
                mock.patch.object(partners, "save", save):
            result = run(argv)
            return result, saved, store.audit_text()

    def test_list_and_show(self):
        (code, out, _), saved, _a = self.run_with([project()], ["partners", "list", "--json"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(json.loads(out)[0]["slug"], "shop")
        (code, out, _), _s, _a = self.run_with([project()], ["partners", "show", "shop", "--json"])
        self.assertEqual(json.loads(out)["clicks"], 9)
        (code, _o, _e), _s, _a = self.run_with([project()], ["partners", "show", "nope"])
        self.assertEqual(code, cli.FAILED)

    def test_save_new_project(self):
        (code, _o, _e), saved, audit = self.run_with(
            [], ["partners", "save", "fresh", "--set", "title=Fresh",
                 "--set", "url=https://fresh.example", "--set", "visible=1"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(saved[0][0].slug, "fresh")
        self.assertTrue(saved[0][0].visible)
        self.assertIn("партнёр добавлен", audit)

    def test_partial_update_keeps_other_fields(self):
        """Правка названия не стирает описание, переходы и порядок."""
        (code, _o, _e), saved, audit = self.run_with(
            [project()], ["partners", "save", "shop", "--set", "title=New title"])
        self.assertEqual(code, cli.OK)
        updated = saved[0][0]
        self.assertEqual(updated.title, "New title")
        self.assertEqual(updated.description, "Магазин")
        self.assertEqual((updated.clicks, updated.order, updated.visible), (9, 5, True))
        self.assertIn("партнёр изменён", audit)

    def test_visible_can_be_switched_off(self):
        (code, _o, _e), saved, _a = self.run_with(
            [project()], ["partners", "save", "shop", "--set", "visible=0"])
        self.assertFalse(saved[0][0].visible)

    def test_bad_input_is_refused(self):
        for argv in (["partners", "save", "x y", "--set", "title=T", "--set", "url=https://a.b"],
                     ["partners", "save", "ok", "--set", "title=T", "--set", "url=notaurl"],
                     ["partners", "save", "ok", "--set", "nonsense"]):
            with self.subTest(argv=argv):
                (code, _o, _e), saved, _a = self.run_with([], argv)
                self.assertEqual(code, cli.FAILED)
                self.assertEqual(saved, [])

    def test_remove_needs_yes(self):
        (code, _o, err), saved, _a = self.run_with([project()], ["partners", "remove", "shop"])
        self.assertEqual(code, cli.NEEDS_YES)
        self.assertEqual(saved, [])
        (code, _o, _e), saved, audit = self.run_with([project()], ["partners", "remove", "shop", "--yes"])
        self.assertEqual((code, saved), (cli.OK, [[]]))
        self.assertIn("партнёр удалён", audit)
        (code, _o, _e), _s, _a = self.run_with([], ["partners", "remove", "ghost", "--yes"])
        self.assertEqual(code, cli.FAILED)

    def test_export_prints_the_panels_csv(self):
        async def export(slug):
            return [{"code": "ABC", "issued": "2026-10-01"}]

        with Store(), mock.patch.object(partners, "load", lambda: _done([])), \
                mock.patch.object(promo, "export_for_partner", export), \
                mock.patch.object(promo, "render_csv", lambda rows: "code;date\nABC;x\n"):
            code, out, _ = run(["partners", "export", "shop"])
        self.assertEqual((code, out), (cli.OK, "code;date\nABC;x\n"))

    def test_project_limit_is_the_shared_rule(self):
        async def load():
            return [project(f"p{n}") for n in range(partners.MAX_PROJECTS)]

        result = asyncio.run(self._save_with(load, {"slug": "extra", "title": "T",
                                                    "url": "https://e.example"}))
        self.assertFalse(result.ok)
        self.assertIn(str(partners.MAX_PROJECTS), result.message)

    async def _save_with(self, load, data):
        with mock.patch.object(partners, "load", load):
            return await ops.partner_save(data)


async def _done(value):
    return value


class Restart(unittest.TestCase):
    def test_needs_yes_and_reports_missing_docker(self):
        with Store():
            self.assertEqual(run(["restart"])[0], cli.NEEDS_YES)
            with mock.patch.object(ops, "restart_bot",
                                   lambda: _done(ops.Result(False, "Нет доступа к docker"))):
                code, _o, err = run(["restart", "--yes"])
            self.assertEqual(code, cli.FAILED)
            self.assertIn("docker", err)
            with mock.patch.object(ops, "restart_bot",
                                   lambda: _done(ops.Result(True, "Перезапуск начат"))):
                self.assertEqual(run(["restart", "--yes"])[0], cli.OK)

    def test_ops_refuses_without_docker_socket(self):
        from radar import dockerapi

        with mock.patch.object(dockerapi, "available", lambda: False):
            result = asyncio.run(ops.restart_bot())
        self.assertFalse(result.ok)

    def test_host_script_has_restart(self):
        with open(os.path.join(ROOT, "tools", "radarctl.sh"), encoding="utf-8") as handle:
            script = handle.read()
        self.assertIn("restart)", script)
        self.assertIn('docker restart "$CONTAINER"', script)


class Files(unittest.TestCase):
    def test_remove_needs_yes_and_token(self):
        removed = []
        with Store(), mock.patch.object(filedrop, "remove",
                                        lambda token: removed.append(token) or token == "good"):
            self.assertEqual(run(["files", "remove"])[0], cli.FAILED)
            self.assertEqual(run(["files", "remove", "good"])[0], cli.NEEDS_YES)
            self.assertEqual(removed, [])
            self.assertEqual(run(["files", "remove", "good", "--yes"])[0], cli.OK)
            self.assertEqual(run(["files", "remove", "gone", "--yes"])[0], cli.FAILED)


class Parsing(unittest.TestCase):
    def test_new_subcommands_parse(self):
        parser = cli.build_parser()
        for argv in (["subs", "list"], ["subs", "grant", "1", "5"], ["partners", "list"],
                     ["restart"], ["files", "remove", "t"], ["vpn", "panels"],
                     ["vpn", "extend", "1", "2", "30"]):
            with self.subTest(argv=argv):
                self.assertTrue(callable(parser.parse_args(argv).func))

    def test_pairs_helper(self):
        self.assertEqual(cli_ops.pairs(["a=1", "b=x=y"]), ({"a": "1", "b": "x=y"}, ""))
        self.assertTrue(cli_ops.pairs(["broken"])[1])
        self.assertTrue(cli_ops.pairs(["=1"])[1])

    def test_form_matches_panel_form_api(self):
        form = cli_ops.Form(slot=["1", "2"], one="x")
        self.assertEqual(form.getall("slot"), ["1", "2"])
        self.assertEqual(form.getall("one"), ["x"])
        self.assertEqual(form.getall("none", ["d"]), ["d"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
