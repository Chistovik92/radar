#!/usr/bin/env python3
"""Адрес панели и ошибки 404/405 (5.9.2.3).

С сервера пришёл отчёт: PasarGuard отвечала «HTTP 404: без пояснения» на
проверку и «405 Method Not Allowed» на выдачу. Причина типична — адрес
скопирован из браузера вместе с `/dashboard/`, и клиент слал API-запросы
в раздачу страниц веб-интерфейса.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import vpnpanels  # noqa: E402
from radar.vpnpanels import (MarzbanPanel, MarzneshinPanel, PanelError,  # noqa: E402
                             PasarGuardPanel, XuiPanel, api_root)


def run(coro):
    return asyncio.run(coro)


STOP = MarzbanPanel.url_stop


class ApiRootTests(unittest.TestCase):
    def test_dashboard_and_docs_are_cut(self) -> None:
        cases = {
            "https://h:8000/dashboard/": "https://h:8000",
            "https://h:8000/dashboard": "https://h:8000",
            "https://h:8000/dashboard/#/login": "https://h:8000",
            "https://h:8000/DASHBOARD/": "https://h:8000",
            "http://1.2.3.4:8000/docs": "http://1.2.3.4:8000",
            "https://h:8000/redoc": "https://h:8000",
            "https://h:8000/api": "https://h:8000",
            "https://h:8000/api/admin": "https://h:8000",
        }
        for given, want in cases.items():
            self.assertEqual(api_root(given, STOP), want, given)

    def test_clean_addresses_and_proxy_prefixes_survive(self) -> None:
        for same in ("https://h:8000", "https://h", "http://10.0.0.5:8000"):
            self.assertEqual(api_root(same + "/", STOP), same)
        self.assertEqual(api_root("https://h/panel/dashboard/", STOP), "https://h/panel")
        self.assertEqual(api_root("https://h/secret/", STOP), "https://h/secret")

    def test_garbage_is_not_made_worse(self) -> None:
        self.assertEqual(api_root("", STOP), "")
        self.assertEqual(api_root("not a url/", STOP), "not a url")


class PanelAddressTests(unittest.TestCase):
    def test_marzban_family_cuts_the_web_interface(self) -> None:
        for cls in (MarzbanPanel, PasarGuardPanel, MarzneshinPanel):
            self.assertEqual(cls("https://h:8000/dashboard/", token="t").url, "https://h:8000", cls)

    def test_other_panels_are_left_alone(self) -> None:
        """У 3x-ui секретный путь произволен — резать его нельзя."""
        self.assertEqual(XuiPanel("https://h:2053/abc/dashboard/", token="t").url,
                         "https://h:2053/abc/dashboard")


class FailureMessageTests(unittest.TestCase):
    def panel(self) -> PasarGuardPanel:
        panel = PasarGuardPanel("https://h:8000", token="static-api-key")
        panel._session = object()      # сессия «открыта»: _request подменён
        return panel

    def test_405_on_create_names_the_route_and_hints_at_the_address(self) -> None:
        panel = self.panel()

        async def fake(method, path, *, body=None, form=None, headers=None):
            return (404, "") if method == "GET" else (405, "")

        with mock.patch.object(panel, "_request", fake), self.assertRaises(PanelError) as ctx:
            run(panel.create_user("radar_42", 0, 0))
        text = str(ctx.exception)
        self.assertIn("405", text)
        self.assertIn("POST /api/user", text)
        self.assertIn("/dashboard", text)
        self.assertNotIn("static-api-key", text)

    def test_a_real_missing_user_is_still_just_missing(self) -> None:
        panel = self.panel()

        async def fake(method, path, *, body=None, form=None, headers=None):
            return 404, json.dumps({"detail": "User not found"})

        with mock.patch.object(panel, "_request", fake):
            self.assertIsNone(run(panel.get_user("radar_42")))

    def test_detailed_errors_are_passed_through(self) -> None:
        panel = self.panel()

        async def fake(method, path, *, body=None, form=None, headers=None):
            return 409, json.dumps({"detail": "User already exists"})

        with mock.patch.object(panel, "_request", fake), self.assertRaises(PanelError) as ctx:
            run(panel.create_user("x", 0, 0))
        self.assertIn("User already exists", str(ctx.exception))


class CheckProbeTests(unittest.TestCase):
    def test_check_points_at_the_real_root(self) -> None:
        # Адрес с префиксом, которого у панели нет: API живёт в корне сайта.
        panel = PasarGuardPanel("https://h:8000/panel", token="static-api-key")
        panel._session = object()
        seen: list[str] = []

        async def fake(method, path, *, body=None, form=None, headers=None):
            seen.append(path)
            if path.startswith("https://h:8000/api/admin"):
                return 401, json.dumps({"detail": "Not authenticated"})
            return 404, ""

        with mock.patch.object(panel, "_request", fake), self.assertRaises(PanelError) as ctx:
            run(panel.check())
        self.assertIn("API найден по адресу https://h:8000", str(ctx.exception))

    def test_check_without_a_better_root_keeps_the_plain_error(self) -> None:
        panel = PasarGuardPanel("https://h:8000/panel", token="k")
        panel._session = object()

        async def fake(method, path, *, body=None, form=None, headers=None):
            return 404, ""

        with mock.patch.object(panel, "_request", fake), self.assertRaises(PanelError) as ctx:
            run(panel.check())
        self.assertNotIn("API найден", str(ctx.exception))
        self.assertIn("404", str(ctx.exception))

    def test_a_page_stub_is_not_taken_for_the_api(self) -> None:
        panel = PasarGuardPanel("https://h:8000/panel", token="k")
        panel._session = object()

        async def fake(method, path, *, body=None, form=None, headers=None):
            if path.startswith("https://h:8000/api/admin"):
                return 200, "<html>dashboard</html>"
            return 404, ""

        with mock.patch.object(panel, "_request", fake), self.assertRaises(PanelError) as ctx:
            run(panel.check())
        self.assertNotIn("API найден", str(ctx.exception))

    def test_working_panel_is_reported_as_before(self) -> None:
        panel = PasarGuardPanel("https://h:8000", token="k")
        panel._session = object()

        async def fake(method, path, *, body=None, form=None, headers=None):
            return 200, json.dumps({"username": "admin"})

        with mock.patch.object(panel, "_request", fake):
            note = run(panel.check())
        self.assertIn("вход как admin", note)
        self.assertEqual(vpnpanels.KINDS["pasarguard"], PasarGuardPanel)


class SlotSaveNormalisationTests(unittest.TestCase):
    def test_form_stores_the_api_root(self) -> None:
        from radar import secrets, vpn, vpnslots

        env: dict[str, str] = {}

        def write_many(values):
            env.update(values)
            return True

        with mock.patch.object(vpn, "_setting", lambda key: env.get(key, "")),                 mock.patch.object(secrets, "write_many", write_many):
            form = {"KIND": "pasarguard", "URL": "https://h:8000/dashboard/", "TOKEN": "k"}
            self.assertEqual(vpnslots.save(1, form), "")
            self.assertEqual(env["VPN1_URL"], "https://h:8000")
            form = {"KIND": "3xui", "URL": "https://h:2053/secret/", "TOKEN": "k"}
            self.assertEqual(vpnslots.save(2, form), "")
            self.assertEqual(env["VPN2_URL"], "https://h:2053/secret/")


if __name__ == "__main__":
    unittest.main()
