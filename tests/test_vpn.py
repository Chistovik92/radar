#!/usr/bin/env python3
"""VPN-панели и выдача доступа (5.0): без сети.

Сеть не поднимается: у клиентов подменяется `_call`, а запросы
записываются. Так проверяется то, что решает модуль сам, — какие пути
и тела уходят в панель и как разбираются её ответы. Настоящие панели
этими тестами не проверены: ⚠️ до первой проверки на сервере.
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
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import features, vpn, vpnpanels  # noqa: E402
from radar.vpnpanels import (  # noqa: E402
    Account,
    PanelError,
    PasarGuardPanel,
    RemnawavePanel,
    XuiPanel,
)


def run(coro):
    return asyncio.run(coro)


class Recorder:
    """Подмена `_call`: пишет запросы, отвечает по таблице (метод, путь)."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def __call__(self, method, path, *, body=None, form=None, missing_ok=False):
        self.calls.append((method, path, body))
        answer = self.answers.get((method, path))
        if callable(answer):
            answer = answer(body)
        if answer is None and not missing_ok and (method, path) not in self.answers:
            raise AssertionError(f"неожиданный запрос {method} {path}")
        return answer


class TimeTests(unittest.TestCase):
    def test_seconds_millis_iso(self):
        self.assertEqual(vpnpanels.parse_time(1_800_000_000), 1_800_000_000)
        self.assertEqual(vpnpanels.parse_time(1_800_000_000_000), 1_800_000_000)
        self.assertEqual(vpnpanels.parse_time("2027-01-15T08:00:00.000Z"), 1_800_000_000)
        self.assertEqual(vpnpanels.parse_time("2027-01-15T11:00:00+03:00"), 1_800_000_000)
        self.assertEqual(vpnpanels.parse_time("2027-01-15T00:00:00"),
                         vpnpanels.parse_time("2027-01-15T00:00:00Z"))

    def test_empty_and_forever_are_zero(self):
        for value in (None, "", 0, -1, "2099-12-31T00:00:00.000Z", "мусор"):
            self.assertEqual(vpnpanels.parse_time(value), 0, value)

    def test_iso_roundtrip(self):
        ts = 1_800_000_000
        self.assertEqual(vpnpanels.parse_time(vpnpanels.to_iso(ts)), ts)
        self.assertTrue(vpnpanels.to_iso(0).startswith("2099-"))


class NameTests(unittest.TestCase):
    def test_account_name_is_stable_and_valid(self):
        self.assertEqual(vpnpanels.account_name("123456789"), "radar_123456789")
        self.assertEqual(vpnpanels.account_name("123"), vpnpanels.account_name(123))
        name = vpnpanels.account_name("max:42")
        self.assertTrue(vpnpanels.valid_name(name), name)

    def test_build_by_alias(self):
        self.assertIsInstance(vpnpanels.build("3x-ui", url="http://x"), XuiPanel)
        self.assertIsInstance(vpnpanels.build("PasarGuard", url="http://x"), PasarGuardPanel)
        self.assertIsInstance(vpnpanels.build("remna", url="http://x"), RemnawavePanel)
        self.assertIsNone(vpnpanels.build("marzban", url="http://x"))
        self.assertIsNone(vpnpanels.build("", url="http://x"))


def _xui_inbound(clients, protocol="vless"):
    return {"success": True, "obj": {
        "id": 3, "protocol": protocol,
        "settings": json.dumps({"clients": clients}),
    }}


class XuiTests(unittest.TestCase):
    def setUp(self):
        self.panel = XuiPanel("http://panel:2053/secret", token="t", inbound=3,
                              sub_url="https://sub.example:2096/sub/")

    def test_needs_inbound(self):
        panel = XuiPanel("http://panel", token="t")
        self.assertIn("VPN_XUI_INBOUND", panel.problems())
        self.assertEqual(self.panel.problems(), [])

    def test_create_sends_client_json_string(self):
        rec = Recorder({
            ("GET", "panel/api/inbounds/get/3"): _xui_inbound([]),
            ("POST", "panel/api/inbounds/addClient"): {"success": True, "obj": None},
        })
        with mock.patch.object(self.panel, "_call", rec):
            account = run(self.panel.create_user("radar_1", 1_800_000_000, 5 * vpnpanels.GB))
        method, path, body = rec.calls[-1]
        self.assertEqual(body["id"], 3)
        client = json.loads(body["settings"])["clients"][0]
        self.assertEqual(client["email"], "radar_1")
        self.assertEqual(client["expiryTime"], 1_800_000_000_000)
        self.assertEqual(client["totalGB"], 5 * vpnpanels.GB)
        self.assertTrue(client["id"])
        self.assertTrue(client["subId"])
        self.assertEqual(account.subscription_url,
                         f"https://sub.example:2096/sub/{client['subId']}")

    def test_trojan_uses_password(self):
        rec = Recorder({
            ("GET", "panel/api/inbounds/get/3"): _xui_inbound([], "trojan"),
            ("POST", "panel/api/inbounds/addClient"): {"success": True},
        })
        with mock.patch.object(self.panel, "_call", rec):
            run(self.panel.create_user("radar_1", 0, 0))
        client = json.loads(rec.calls[-1][2]["settings"])["clients"][0]
        self.assertIn("password", client)
        self.assertNotIn("id", client)
        self.assertEqual(client["expiryTime"], 0)

    def test_shadowsocks_refused(self):
        rec = Recorder({("GET", "panel/api/inbounds/get/3"):
                        _xui_inbound([], "shadowsocks")})
        with mock.patch.object(self.panel, "_call", rec):
            with self.assertRaises(PanelError):
                run(self.panel.create_user("radar_1", 0, 0))

    def test_expiry_keeps_the_same_client(self):
        """Продление — это updateClient прежнего клиента, а не новый."""
        old = {"id": "uuid-1", "email": "radar_1", "subId": "s1",
               "enable": False, "expiryTime": 1, "totalGB": 0}
        rec = Recorder({
            ("GET", "panel/api/inbounds/get/3"): _xui_inbound([old]),
            ("POST", "panel/api/inbounds/updateClient/uuid-1"): {"success": True},
        })
        with mock.patch.object(self.panel, "_call", rec):
            run(self.panel.set_expiry("radar_1", 1_800_000_000))
        client = json.loads(rec.calls[-1][2]["settings"])["clients"][0]
        self.assertEqual(client["id"], "uuid-1")
        self.assertEqual(client["subId"], "s1")
        self.assertEqual(client["expiryTime"], 1_800_000_000_000)

    def test_get_user_sums_traffic(self):
        client = {"id": "u", "email": "radar_1", "subId": "s1", "enable": True,
                  "expiryTime": 1_800_000_000_000, "totalGB": 10}
        rec = Recorder({
            ("GET", "panel/api/inbounds/get/3"): _xui_inbound([client]),
            ("GET", "panel/api/inbounds/getClientTraffics/radar_1"):
                {"success": True, "obj": {"up": 3, "down": 4}},
        })
        with mock.patch.object(self.panel, "_call", rec):
            account = run(self.panel.get_user("radar_1"))
        self.assertEqual(account.traffic_used, 7)
        self.assertEqual(account.expire, 1_800_000_000)
        self.assertTrue(account.enabled)

    def test_missing_client_is_none(self):
        rec = Recorder({("GET", "panel/api/inbounds/get/3"): _xui_inbound([])})
        with mock.patch.object(self.panel, "_call", rec):
            self.assertIsNone(run(self.panel.get_user("radar_1")))

    def test_refusal_carries_panel_message(self):
        rec = Recorder({("GET", "panel/api/inbounds/get/3"):
                        {"success": False, "msg": "inbound not found"}})
        with mock.patch.object(self.panel, "_call", rec):
            with self.assertRaises(PanelError) as caught:
                run(self.panel.check())
        self.assertIn("inbound not found", str(caught.exception))

    def test_subscription_needs_sub_url(self):
        panel = XuiPanel("http://panel", token="t", inbound=3)
        with self.assertRaises(PanelError):
            run(panel.subscription_url("radar_1"))


class PasarGuardTests(unittest.TestCase):
    def setUp(self):
        self.panel = PasarGuardPanel("https://pg.example", token="t", groups=("1", "x", "2"))

    def test_create_body(self):
        user = {"username": "radar_1", "status": "active",
                "expire": "2027-01-15T08:00:00Z", "data_limit": 0,
                "used_traffic": 12, "subscription_url": "/sub/abc"}
        rec = Recorder({("POST", "api/user"): user})
        with mock.patch.object(self.panel, "_call", rec):
            account = run(self.panel.create_user("radar_1", 1_800_000_000, 0))
        body = rec.calls[0][2]
        self.assertEqual(body["group_ids"], [1, 2])
        self.assertEqual(vpnpanels.parse_time(body["expire"]), 1_800_000_000)
        self.assertEqual(account.subscription_url, "https://pg.example/sub/abc")
        self.assertEqual(account.traffic_used, 12)
        self.assertTrue(account.enabled)

    def test_missing_user_is_none(self):
        rec = Recorder({("GET", "api/user/radar_1"): None})
        with mock.patch.object(self.panel, "_call", rec):
            self.assertIsNone(run(self.panel.get_user("radar_1")))

    def test_disable_is_status_change(self):
        rec = Recorder({("PUT", "api/user/radar_1"): {}})
        with mock.patch.object(self.panel, "_call", rec):
            run(self.panel.disable("radar_1"))
        self.assertEqual(rec.calls[0][2], {"status": "disabled"})


class RemnawaveTests(unittest.TestCase):
    def setUp(self):
        self.panel = RemnawavePanel("http://remnawave:3000", token="t",
                                    groups=("squad-uuid",))

    def test_token_required(self):
        panel = RemnawavePanel("http://r", user="a", password="b")
        self.assertIn("VPN_PANEL_TOKEN", panel.problems())

    def test_forwarded_headers(self):
        headers = self.panel._headers()
        self.assertEqual(headers["X-Forwarded-Proto"], "https")
        self.assertEqual(headers["Authorization"], "Bearer t")

    def test_create_and_parse(self):
        user = {"uuid": "u-1", "username": "radar_1", "status": "ACTIVE",
                "expireAt": "2099-12-31T00:00:00.000Z", "trafficLimitBytes": 0,
                "userTraffic": {"usedTrafficBytes": 99},
                "subscriptionUrl": "https://sub.example/abc"}
        rec = Recorder({("POST", "api/users"): {"response": user}})
        with mock.patch.object(self.panel, "_call", rec):
            account = run(self.panel.create_user("radar_1", 0, 0))
        body = rec.calls[0][2]
        self.assertEqual(body["activeInternalSquads"], ["squad-uuid"])
        self.assertTrue(body["expireAt"].startswith("2099-"))
        self.assertEqual(account.expire, 0)
        self.assertEqual(account.traffic_used, 99)
        self.assertEqual(account.subscription_url, "https://sub.example/abc")

    def test_old_traffic_field(self):
        account = vpnpanels.remnawave_account(
            {"username": "a", "status": "DISABLED", "usedTrafficBytes": 5})
        self.assertEqual(account.traffic_used, 5)
        self.assertFalse(account.enabled)

    def test_patch_by_uuid(self):
        rec = Recorder({
            ("GET", "api/users/by-username/radar_1"): {"response": {"uuid": "u-1"}},
            ("PATCH", "api/users"): {"response": {}},
        })
        with mock.patch.object(self.panel, "_call", rec):
            run(self.panel.set_expiry("radar_1", 1_800_000_000))
        body = rec.calls[-1][2]
        self.assertEqual(body["uuid"], "u-1")
        self.assertEqual(vpnpanels.parse_time(body["expireAt"]), 1_800_000_000)


class FakePanel(vpnpanels.Panel):
    """Панель в памяти: проверяет логику выдачи, а не разметку запросов."""

    kind = "fake"

    def __init__(self):
        super().__init__("http://fake", token="t")
        self.users = {}
        self.created = 0

    async def create_user(self, name, expire, traffic):
        self.created += 1
        self.users[name] = Account(name, True, expire, traffic, 0, f"https://s/{name}")
        return self.users[name]

    async def get_user(self, name):
        return self.users.get(name)

    async def set_expiry(self, name, expire):
        old = self.users[name]
        self.users[name] = Account(name, old.enabled, expire, old.traffic_limit,
                                   0, old.subscription_url)

    async def set_traffic(self, name, traffic):
        pass

    async def disable(self, name):
        old = self.users[name]
        self.users[name] = Account(name, False, old.expire, 0, 0, old.subscription_url)

    async def enable(self, name):
        old = self.users[name]
        self.users[name] = Account(name, True, old.expire, 0, 0, old.subscription_url)

    async def check(self):
        return "ok"


class AccessTests(unittest.TestCase):
    """Заявка → выдача → продление; ключ при повторной выдаче тот же."""

    def setUp(self):
        self.meta = {}
        self.fake = FakePanel()

        async def meta_get(key, default=None):
            return json.loads(json.dumps(self.meta.get(key, default)))

        async def meta_set(key, value):
            self.meta[key] = json.loads(json.dumps(value))

        from radar import storage

        features.set_local("vpn", True)
        self.patches = [
            mock.patch.object(storage, "meta_get", meta_get),
            mock.patch.object(storage, "meta_set", meta_set),
            mock.patch.object(vpn, "panel", lambda: self.fake),
            mock.patch.object(vpn, "_setting", lambda key: ""),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        features.apply({})

    def test_flag_off_blocks(self):
        features.set_local("vpn", False)
        ok, reason = vpn.ready()
        self.assertFalse(ok)
        with self.assertRaises(PanelError):
            run(vpn.issue("1", "9"))

    def test_request_is_idempotent(self):
        self.assertEqual(run(vpn.request("1")), vpn.PENDING)
        self.assertEqual(run(vpn.request("1")), vpn.PENDING)
        self.assertEqual(run(vpn.pending()), ["1"])

    def test_issue_then_reissue_keeps_key(self):
        run(vpn.request("1"))
        first = run(vpn.issue("1", "9"))
        self.assertEqual(run(vpn.pending()), [])
        self.assertEqual(run(vpn.issued()), ["1"])
        run(vpn.set_enabled("1", False))
        second = run(vpn.issue("1", "9"))
        self.assertEqual(self.fake.created, 1)
        self.assertEqual(first.subscription_url, second.subscription_url)
        self.assertTrue(second.enabled)

    def test_expired_reissue_gets_new_term(self):
        run(vpn.issue("1", "9"))
        name = vpnpanels.account_name("1")
        run(self.fake.set_expiry(name, int(time.time()) - 10))
        account = run(vpn.issue("1", "9"))
        self.assertGreater(account.expire, time.time() + 29 * vpn.DAY)

    def test_extend_from_later_of_now_and_expiry(self):
        run(vpn.issue("1", "9"))
        before = run(vpn.status("1")).expire
        after = run(vpn.extend("1", 10)).expire
        self.assertEqual(after - before, 10 * vpn.DAY)

    def test_forever_is_not_shortened(self):
        name = vpnpanels.account_name("1")
        run(self.fake.create_user(name, 0, 0))
        self.assertEqual(run(vpn.extend("1", 10)).expire, 0)

    def test_deny(self):
        run(vpn.request("1"))
        run(vpn.deny("1", "9"))
        self.assertEqual(run(vpn.record("1"))["state"], vpn.DENIED)
        self.assertEqual(run(vpn.request("1")), vpn.PENDING)

    def test_forget_allows_new_request(self):
        run(vpn.issue("1", "9"))
        run(vpn.forget("1"))
        self.assertEqual(run(vpn.request("1")), vpn.PENDING)

    def test_link_not_stored_in_db(self):
        run(vpn.issue("1", "9"))
        self.assertNotIn("https://s/", json.dumps(self.meta))


class RoleTests(unittest.TestCase):
    def test_default_auto_role_is_admin(self):
        with mock.patch.object(vpn, "_setting", lambda key: ""):
            self.assertTrue(vpn.issues_without_request("admin"))
            self.assertTrue(vpn.issues_without_request("superadmin"))
            self.assertFalse(vpn.issues_without_request("user"))

    def test_none_means_requests_only(self):
        with mock.patch.object(vpn, "_setting", lambda key: "none"):
            self.assertFalse(vpn.issues_without_request("superadmin"))

    def test_defaults(self):
        values = {"VPN_DAYS": "7", "VPN_TRAFFIC_GB": "50"}
        with mock.patch.object(vpn, "_setting", lambda key: values.get(key, "")):
            self.assertEqual(vpn.default_days(), 7)
            self.assertEqual(vpn.default_traffic(), 50 * vpnpanels.GB)


class BoundaryTests(unittest.TestCase):
    """Границы из дорожной карты, закреплённые строкой."""

    def test_flag_off_by_default(self):
        self.assertFalse(features.BY_KEY["vpn"].default)

    def test_no_sdk_dependencies(self):
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as handle:
            text = handle.read().lower()
        for package in ("remnawave", "httpx", "orjson"):
            self.assertNotIn(package, text)

    def test_monitor_does_not_touch_vpn(self):
        with open(os.path.join(ROOT, "radar", "monitor.py"), encoding="utf-8") as handle:
            self.assertNotIn("vpn", handle.read().lower())


if __name__ == "__main__":
    unittest.main()
