#!/usr/bin/env python3
"""VPN-панели и выдача доступа (5.0, несколько панелей — 5.0.1): без сети.

Сеть не поднимается: у клиентов подменяется `_call` (а для входа —
`_request`), запросы записываются. Проверяется то, что решает модуль
сам, — какие пути и тела уходят в панель и как разбираются её ответы.
Форматы сверены с исходным кодом панелей (сентябрь 2026), но настоящие
панели этими тестами не проверены: ⚠️ до первой проверки на сервере
(`python3 -m radar vpn selftest --yes`).
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
    HiddifyPanel,
    MarzbanPanel,
    MarzneshinPanel,
    OutlinePanel,
    PanelError,
    PasarGuardPanel,
    RemnawavePanel,
    SuiPanel,
    WgEasyPanel,
    XuiLegacyPanel,
    XuiPanel,
)

CERT = "AB" * 32


def run(coro):
    return asyncio.run(coro)


class Recorder:
    """Подмена `_call`: пишет запросы, отвечает по таблице (метод, путь).

    Ответ может быть функцией от тела запроса. Запрос, которого нет
    в таблице, — ошибка теста: так видно, что клиент пошёл не туда.
    """

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def __call__(self, method, path, *, body=None, form=None,
                      missing_ok=False, text=False):
        self.calls.append((method, path, body if body is not None else form))
        if (method, path) not in self.answers:
            raise AssertionError(f"неожиданный запрос {method} {path}")
        answer = self.answers[(method, path)]
        if callable(answer):
            answer = answer(body if body is not None else form)
        if isinstance(answer, PanelError):
            raise answer
        return answer

    def last(self, method, path):
        for call in reversed(self.calls):
            if call[:2] == (method, path):
                return call[2]
        raise AssertionError(f"запроса {method} {path} не было")


def patched(panel, answers):
    rec = Recorder(answers)
    return rec, mock.patch.object(panel, "_call", rec)


# --------------------------------------------------------------------------
#  Общее
# --------------------------------------------------------------------------

class TimeTests(unittest.TestCase):
    def test_seconds_millis_iso(self):
        self.assertEqual(vpnpanels.parse_time(1_800_000_000), 1_800_000_000)
        self.assertEqual(vpnpanels.parse_time(1_800_000_000_000), 1_800_000_000)
        self.assertEqual(vpnpanels.parse_time("2027-01-15T08:00:00.000Z"), 1_800_000_000)
        self.assertEqual(vpnpanels.parse_time("2027-01-15T11:00:00+03:00"), 1_800_000_000)
        self.assertEqual(vpnpanels.parse_time("2027-01-15T08:00:00"), 1_800_000_000)

    def test_empty_and_forever_are_zero(self):
        for value in (None, "", 0, -1, "2099-12-31T00:00:00.000Z", "мусор"):
            self.assertEqual(vpnpanels.parse_time(value), 0, value)

    def test_iso_roundtrip(self):
        self.assertEqual(vpnpanels.parse_time(vpnpanels.to_iso(1_800_000_000)), 1_800_000_000)
        self.assertTrue(vpnpanels.to_iso(0).startswith("2099-"))


class NameTests(unittest.TestCase):
    def test_account_name_fits_strictest_panel(self):
        """Marzban и PasarGuard: строчные, цифры, подчёркивание, до 32."""
        for uid in ("123456789", 123, "max:42", "MAX:9" * 10):
            name = vpnpanels.account_name(uid)
            self.assertTrue(vpnpanels.valid_name(name), name)
        self.assertEqual(vpnpanels.account_name("123"), vpnpanels.account_name(123))

    def test_all_ten_kinds_and_aliases(self):
        self.assertEqual(len(vpnpanels.KINDS), 10)
        cases = {"3x-ui": XuiPanel, "x-ui": XuiLegacyPanel, "s-ui": SuiPanel,
                 "marzban": MarzbanPanel, "PasarGuard": PasarGuardPanel,
                 "marzneshin": MarzneshinPanel, "remna": RemnawavePanel,
                 "hiddify": HiddifyPanel, "outline": OutlinePanel,
                 "wg-easy": WgEasyPanel}
        for alias, cls in cases.items():
            self.assertIsInstance(vpnpanels.build(alias, url="http://x"), cls, alias)
        self.assertIsNone(vpnpanels.build("amnezia", url="http://x"))
        self.assertIn("amnezia", vpnpanels.UNSUPPORTED)

    def test_fingerprint_parsing(self):
        self.assertEqual(len(vpnpanels._fingerprint(":".join(["ab"] * 32))), 32)
        self.assertIsNone(vpnpanels._fingerprint("short"))
        panel = MarzbanPanel("https://p", token="t", cert="bad")
        self.assertTrue(any("отпечаток" in item for item in panel.problems()))


# --------------------------------------------------------------------------
#  3x-ui и x-ui
# --------------------------------------------------------------------------

def _inbound(clients, protocol="vless"):
    return {"success": True, "obj": {"id": 3, "protocol": protocol,
                                     "settings": json.dumps({"clients": clients})}}


PROBE = ("GET", "panel/api/clients/get/radar_probe")


class Xui2Tests(unittest.TestCase):
    """Ветка 2.x: клиенты внутри подключения."""

    def setUp(self):
        self.panel = XuiPanel("http://panel:2053/secret", token="t", inbound=3,
                              sub_url="https://sub.example:2096/sub/")

    def test_needs_inbound(self):
        self.assertTrue(any("inbound" in item for item in
                            XuiPanel("http://p", token="t").problems()))
        self.assertEqual(self.panel.problems(), [])

    def test_generation_detected_by_404(self):
        rec, patch = patched(self.panel, {PROBE: None})
        with patch:
            self.assertEqual(run(self.panel._gen()), 2)

    def test_create_sends_client_json_string_without_tgid(self):
        rec, patch = patched(self.panel, {
            PROBE: None,
            ("GET", "panel/api/inbounds/get/3"): _inbound([]),
            ("POST", "panel/api/inbounds/addClient"): {"success": True},
        })
        with patch:
            account = run(self.panel.create_user("radar_1", 1_800_000_000, 5 * vpnpanels.GB))
        body = rec.last("POST", "panel/api/inbounds/addClient")
        self.assertEqual(body["id"], 3)
        client = json.loads(body["settings"])["clients"][0]
        self.assertEqual(client["expiryTime"], 1_800_000_000_000)
        self.assertEqual(client["totalGB"], 5 * vpnpanels.GB)
        self.assertNotIn("tgId", client)
        self.assertEqual(account.subscription_url,
                         f"https://sub.example:2096/sub/{client['subId']}")

    def test_trojan_uses_password_shadowsocks_refused(self):
        rec, patch = patched(self.panel, {
            PROBE: None,
            ("GET", "panel/api/inbounds/get/3"): _inbound([], "trojan"),
            ("POST", "panel/api/inbounds/addClient"): {"success": True},
        })
        with patch:
            run(self.panel.create_user("radar_1", 0, 0))
        client = json.loads(rec.last("POST", "panel/api/inbounds/addClient")["settings"])["clients"][0]
        self.assertIn("password", client)
        self.assertNotIn("id", client)

        panel = XuiPanel("http://p", token="t", inbound=3)
        _, patch = patched(panel, {PROBE: None, ("GET", "panel/api/inbounds/get/3"):
                                   _inbound([], "shadowsocks")})
        with patch, self.assertRaises(PanelError):
            run(panel.create_user("radar_1", 0, 0))

    def test_expiry_keeps_the_same_client(self):
        old = {"id": "uuid-1", "email": "radar_1", "subId": "s1", "enable": False,
               "expiryTime": 1, "totalGB": 0}
        rec, patch = patched(self.panel, {
            PROBE: None,
            ("GET", "panel/api/inbounds/get/3"): _inbound([old]),
            ("POST", "panel/api/inbounds/updateClient/uuid-1"): {"success": True},
        })
        with patch:
            run(self.panel.set_expiry("radar_1", 1_800_000_000))
        client = json.loads(rec.last("POST", "panel/api/inbounds/updateClient/uuid-1")
                            ["settings"])["clients"][0]
        self.assertEqual((client["id"], client["subId"]), ("uuid-1", "s1"))
        self.assertEqual(client["expiryTime"], 1_800_000_000_000)

    def test_get_user_sums_traffic(self):
        client = {"id": "u", "email": "radar_1", "subId": "s1", "enable": True,
                  "expiryTime": 1_800_000_000_000, "totalGB": 10}
        _, patch = patched(self.panel, {
            PROBE: None,
            ("GET", "panel/api/inbounds/get/3"): _inbound([client]),
            ("GET", "panel/api/inbounds/getClientTraffics/radar_1"):
                {"success": True, "obj": {"up": 3, "down": 4}},
        })
        with patch:
            account = run(self.panel.get_user("radar_1"))
        self.assertEqual((account.traffic_used, account.expire), (7, 1_800_000_000))


class Xui3Tests(unittest.TestCase):
    """Ветка 3.x: клиент — отдельная сущность (3x-ui 3.8)."""

    def setUp(self):
        self.panel = XuiPanel("http://panel", token="t", inbound=3,
                              sub_url="https://sub.example/sub")
        self.missing = {"success": False, "msg": "Ошибка: record not found"}

    def test_create_uses_clients_add_with_inbound_ids(self):
        rec, patch = patched(self.panel, {
            PROBE: self.missing,
            ("GET", "panel/api/clients/get/radar_1"): self.missing,
            ("POST", "panel/api/clients/add"): {"success": True},
        })
        with patch:
            account = run(self.panel.create_user("radar_1", 1_800_000_000, 0))
        body = rec.last("POST", "panel/api/clients/add")
        self.assertEqual(body["inboundIds"], [3])
        self.assertEqual(body["client"]["email"], "radar_1")
        self.assertTrue(body["client"]["id"] and body["client"]["password"])
        self.assertEqual(account.expire, 1_800_000_000)

    def test_update_sends_whole_client_with_uuid_as_id(self):
        record = {"client": {"uuid": "u-1", "email": "radar_1", "subId": "s1",
                             "enable": True, "expiryTime": 0, "totalGB": 5,
                             "limitIp": 2, "password": "p"},
                  "usedTraffic": 9}
        rec, patch = patched(self.panel, {
            PROBE: self.missing,
            ("GET", "panel/api/clients/get/radar_1"): {"success": True, "obj": record},
            ("POST", "panel/api/clients/update/radar_1"): {"success": True},
        })
        with patch:
            run(self.panel.disable("radar_1"))
            account = run(self.panel.get_user("radar_1"))
        body = rec.last("POST", "panel/api/clients/update/radar_1")
        self.assertEqual(body["id"], "u-1")
        self.assertNotIn("uuid", body)
        self.assertEqual((body["enable"], body["subId"], body["limitIp"]), (False, "s1", 2))
        self.assertEqual(account.traffic_used, 9)
        self.assertEqual(account.subscription_url, "https://sub.example/sub/s1")

    def test_missing_is_none_other_refusal_is_error(self):
        _, patch = patched(self.panel, {
            PROBE: self.missing,
            ("GET", "panel/api/clients/get/radar_1"): self.missing,
            ("GET", "panel/api/clients/get/radar_2"): {"success": False, "msg": "db locked"},
        })
        with patch:
            self.assertIsNone(run(self.panel.get_user("radar_1")))
            with self.assertRaises(PanelError):
                run(self.panel.get_user("radar_2"))


class XuiLoginTests(unittest.TestCase):
    """Вход по паролю: в 3.x — с CSRF-токеном, в старых — без."""

    def _panel(self, cls=XuiPanel):
        panel = cls("http://panel", user="admin", password="pw", inbound=1)
        panel._headers = {}
        return panel

    def test_csrf_flow(self):
        panel = self._panel()
        seen = []

        async def fake(method, path, *, body=None, form=None, headers=None):
            seen.append((method, path, dict(headers or {})))
            if path == "csrf-token":
                return 200, json.dumps({"success": True, "obj": f"tok{len(seen)}"})
            return 200, json.dumps({"success": True})

        with mock.patch.object(panel, "_request", fake):
            run(panel._login())
        self.assertEqual(seen[1][:2], ("POST", "login"))
        self.assertEqual(seen[1][2]["X-CSRF-Token"], "tok1")
        self.assertEqual(panel._headers["X-CSRF-Token"], "tok3")

    def test_old_panel_without_csrf(self):
        panel = self._panel()

        async def fake(method, path, *, body=None, form=None, headers=None):
            if path == "csrf-token":
                return 404, "404 page not found"
            return 200, json.dumps({"success": True})

        with mock.patch.object(panel, "_request", fake):
            run(panel._login())
        self.assertNotIn("X-CSRF-Token", panel._headers)

    def test_wrong_password(self):
        panel = self._panel()

        async def fake(method, path, *, body=None, form=None, headers=None):
            return (404, "") if path == "csrf-token" else (200, '{"success": false}')

        with mock.patch.object(panel, "_request", fake), self.assertRaises(PanelError):
            run(panel._login())

    def test_legacy_xui_path_and_no_tokens(self):
        panel = XuiLegacyPanel("http://p", token="t", inbound=1)
        self.assertTrue(any("токенов у этой панели нет" in item for item in panel.problems()))
        panel = XuiLegacyPanel("http://p", user="a", password="b", inbound=1)
        _, patch = patched(panel, {("GET", "xui/API/inbounds/get/1"): _inbound([])})
        with patch:
            self.assertIsNone(run(panel.get_user("radar_1")))


# --------------------------------------------------------------------------
#  s-ui
# --------------------------------------------------------------------------

class SuiTests(unittest.TestCase):
    def setUp(self):
        self.panel = SuiPanel("https://sui.example/app", token="tok", groups=("1", "2"),
                              sub_url="https://sui.example/sub")

    def test_token_header(self):
        self.assertEqual(self.panel._base_headers()["Token"], "tok")
        self.assertTrue(SuiPanel("https://x").problems())

    def test_create_generates_configs_like_frontend(self):
        rec, patch = patched(self.panel, {
            ("GET", "apiv2/clients"): {"success": True, "obj": {"clients": []}},
            ("POST", "apiv2/save"): {"success": True},
        })
        with patch:
            account = run(self.panel.create_user("radar_1", 1_800_000_000, 0))
        form = rec.last("POST", "apiv2/save")
        self.assertEqual((form["object"], form["action"]), ("clients", "new"))
        data = json.loads(form["data"])
        self.assertEqual(data["inbounds"], [1, 2])
        self.assertEqual(data["expiry"], 1_800_000_000)
        for protocol in ("vless", "vmess", "trojan", "hysteria2", "tuic", "shadowsocks"):
            self.assertIn(protocol, data["config"])
        self.assertEqual(data["config"]["vless"]["uuid"], data["config"]["vmess"]["uuid"])
        self.assertEqual(account.subscription_url, "https://sui.example/sub/radar_1")

    def test_edit_sends_full_client(self):
        short = {"id": 7, "name": "radar_1", "enable": True}
        full = {"id": 7, "name": "radar_1", "enable": True, "config": {"vless": {}},
                "inbounds": [1], "volume": 0, "expiry": 0, "up": 1, "down": 2}
        rec, patch = patched(self.panel, {
            ("GET", "apiv2/clients"): {"success": True, "obj": {"clients": [short]}},
            ("GET", "apiv2/clients?id=7"): {"success": True, "obj": {"clients": [full]}},
            ("POST", "apiv2/save"): {"success": True},
        })
        with patch:
            run(self.panel.disable("radar_1"))
        data = json.loads(rec.last("POST", "apiv2/save")["data"])
        self.assertEqual(rec.last("POST", "apiv2/save")["action"], "edit")
        self.assertEqual((data["id"], data["enable"], data["config"]), (7, False, {"vless": {}}))


# --------------------------------------------------------------------------
#  Marzban, PasarGuard, Marzneshin
# --------------------------------------------------------------------------

class MarzbanTests(unittest.TestCase):
    def test_create_needs_proxies_and_int_expiry(self):
        panel = MarzbanPanel("https://m.example", token="jwt", groups=("VLESS", "trojan", "junk"))
        user = {"username": "radar_1", "status": "active", "expire": 1_800_000_000,
                "data_limit": 0, "used_traffic": 5, "subscription_url": "/sub/abc"}
        rec, patch = patched(panel, {("POST", "api/user"): user})
        with patch:
            account = run(panel.create_user("radar_1", 1_800_000_000, 0))
        body = rec.last("POST", "api/user")
        self.assertEqual(body["proxies"], {"vless": {}, "trojan": {}})
        self.assertEqual(body["expire"], 1_800_000_000)
        self.assertEqual(account.subscription_url, "https://m.example/sub/abc")

    def test_unlimited_is_zero(self):
        panel = MarzbanPanel("https://m", token="t")
        rec, patch = patched(panel, {("PUT", "api/user/radar_1"): {}})
        with patch:
            run(panel.set_expiry("radar_1", 0))
        self.assertEqual(rec.last("PUT", "api/user/radar_1"), {"expire": 0})


class PasarGuardTests(unittest.TestCase):
    def test_api_key_goes_to_x_api_key(self):
        panel = PasarGuardPanel("https://pg", token="pg_key_123")
        panel._headers = {}
        run(panel._login())
        self.assertEqual(panel._headers, {"X-Api-Key": "pg_key_123"})

    def test_jwt_goes_to_bearer(self):
        panel = PasarGuardPanel("https://pg", token="eyJhbGc.eyJzdWI.sig")
        panel._headers = {}
        run(panel._login())
        self.assertEqual(panel._headers["Authorization"], "Bearer eyJhbGc.eyJzdWI.sig")

    def test_unlimited_on_modify_is_zero_not_null(self):
        """null у PasarGuard значит «не менять» — бессрочно только 0."""
        panel = PasarGuardPanel("https://pg", token="k")
        rec, patch = patched(panel, {("PUT", "api/user/radar_1"): {}})
        with patch:
            run(panel.set_expiry("radar_1", 0))
            run(panel.set_expiry("radar_1", 1_800_000_000))
        bodies = [call[2] for call in rec.calls]
        self.assertEqual(bodies[0], {"expire": 0})
        self.assertEqual(vpnpanels.parse_time(bodies[1]["expire"]), 1_800_000_000)

    def test_create_groups(self):
        panel = PasarGuardPanel("https://pg", token="k", groups=("1", "x", "2"))
        rec, patch = patched(panel, {("POST", "api/user"): {"username": "radar_1",
                                                            "status": "active"}})
        with patch:
            run(panel.create_user("radar_1", 0, 0))
        body = rec.last("POST", "api/user")
        self.assertEqual((body["group_ids"], body["expire"]), ([1, 2], 0))


class MarzneshinTests(unittest.TestCase):
    def setUp(self):
        self.panel = MarzneshinPanel("https://mz", token="t", groups=("4",))

    def test_create_strategy_and_services(self):
        rec, patch = patched(self.panel, {("POST", "api/users"): {
            "username": "radar_1", "enabled": True, "expire_strategy": "never",
            "used_traffic": 1, "subscription_url": "/sub/radar_1/k"}})
        with patch:
            account = run(self.panel.create_user("radar_1", 0, 0))
        body = rec.last("POST", "api/users")
        self.assertEqual((body["expire_strategy"], body["service_ids"]), ("never", [4]))
        self.assertEqual(account.expire, 0)
        self.assertEqual(account.subscription_url, "https://mz/sub/radar_1/k")

    def test_modify_carries_username_and_toggles_are_actions(self):
        rec, patch = patched(self.panel, {
            ("PUT", "api/users/radar_1"): {},
            ("POST", "api/users/radar_1/disable"): {},
        })
        with patch:
            run(self.panel.set_expiry("radar_1", 1_800_000_000))
            run(self.panel.disable("radar_1"))
        body = rec.last("PUT", "api/users/radar_1")
        self.assertEqual((body["username"], body["expire_strategy"]), ("radar_1", "fixed_date"))
        self.assertEqual(self.panel.admin_path, "api/admins/current")


# --------------------------------------------------------------------------
#  Remnawave, Hiddify, Outline, wg-easy
# --------------------------------------------------------------------------

class RemnawaveTests(unittest.TestCase):
    def setUp(self):
        self.panel = RemnawavePanel("http://remnawave:3000", token="t", groups=("sq-1",))

    def test_token_required_and_headers(self):
        self.assertTrue(RemnawavePanel("http://r", user="a", password="b").problems())
        headers = self.panel._base_headers()
        self.assertEqual((headers["Authorization"], headers["X-Forwarded-Proto"]),
                         ("Bearer t", "https"))

    def test_patch_by_username_new_version(self):
        """Текущая версия: username или числовой id, uuid нет."""
        rec, patch = patched(self.panel, {
            ("GET", "api/users/by-username/radar_1"): {"response": {"id": 42, "username": "radar_1"}},
            ("PATCH", "api/users"): {"response": {}},
            ("POST", "api/users/42/actions/disable"): {"response": {}},
        })
        with patch:
            run(self.panel.set_expiry("radar_1", 1_800_000_000))
            run(self.panel.disable("radar_1"))
        body = rec.last("PATCH", "api/users")
        self.assertEqual(body["username"], "radar_1")
        self.assertNotIn("uuid", body)

    def test_patch_old_version_keeps_uuid(self):
        rec, patch = patched(self.panel, {
            ("GET", "api/users/by-username/radar_1"): {"response": {"uuid": "u-1"}},
            ("PATCH", "api/users"): {"response": {}},
            ("POST", "api/users/u-1/actions/enable"): {"response": {}},
        })
        with patch:
            run(self.panel.set_traffic("radar_1", 7))
            run(self.panel.enable("radar_1"))
        self.assertEqual(rec.last("PATCH", "api/users")["uuid"], "u-1")

    def test_parse_both_traffic_fields(self):
        new = vpnpanels.remnawave_account({"username": "a", "status": "ACTIVE",
                                           "userTraffic": {"usedTrafficBytes": 99}})
        old = vpnpanels.remnawave_account({"username": "a", "status": "DISABLED",
                                           "usedTrafficBytes": 5})
        self.assertEqual((new.traffic_used, new.enabled), (99, True))
        self.assertEqual((old.traffic_used, old.enabled), (5, False))


class HiddifyTests(unittest.TestCase):
    def setUp(self):
        self.panel = HiddifyPanel("https://h.example/adminpath", token="admin-uuid",
                                  sub_url="https://h.example/clientpath")

    def test_uuid_is_stable(self):
        self.assertEqual(HiddifyPanel.user_uuid("radar_1"), HiddifyPanel.user_uuid("radar_1"))
        self.assertNotEqual(HiddifyPanel.user_uuid("radar_1"), HiddifyPanel.user_uuid("radar_2"))
        self.assertEqual(self.panel._base_headers()["Hiddify-API-Key"], "admin-uuid")

    def test_create_body_period_and_parse(self):
        expire = int(time.time()) + 10 * vpnpanels.DAY
        rec, patch = patched(self.panel, {
            ("POST", "api/v2/admin/user/"): lambda body: {**body, "current_usage_GB": 1.5},
        })
        with patch:
            account = run(self.panel.create_user("radar_1", expire, 0))
        body = rec.last("POST", "api/v2/admin/user/")
        self.assertIn(body["package_days"], (10, 11))
        self.assertEqual(body["usage_limit_GB"], float(vpnpanels.UNLIMITED_GB))
        self.assertEqual(account.traffic_limit, 0)
        self.assertEqual(account.traffic_used, int(1.5 * vpnpanels.GB))
        self.assertLessEqual(abs(account.expire - expire), vpnpanels.DAY)
        self.assertEqual(account.subscription_url,
                         f"https://h.example/clientpath/{body['uuid']}/")

    def test_forever(self):
        self.assertEqual(HiddifyPanel._period(0)["package_days"], vpnpanels.FOREVER_DAYS)
        account = vpnpanels.hiddify_account({"package_days": vpnpanels.FOREVER_DAYS,
                                             "start_date": "2026-01-01"}, "")
        self.assertEqual(account.expire, 0)


class ListClientsTests(unittest.TestCase):
    """Списки клиентов (5.7.2): поля Telegram-id и идентификаторы записей."""

    def test_hiddify_uses_uuid_and_telegram_id(self):
        panel = HiddifyPanel("https://h.example/adminpath", token="admin-uuid")
        ident = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
        rec, patch = patched(panel, {("GET", "api/v2/admin/user/"): [
            {"uuid": ident, "name": "Иван", "telegram_id": 4242424242, "comment": "",
             "package_days": 30, "usage_limit_GB": 10}]})
        with patch:
            clients = run(panel.list_clients())
        self.assertEqual((clients[0].ref, clients[0].telegram), (ident, "4242424242"))
        self.assertEqual(panel._path(ident), f"api/v2/admin/user/{ident}/",
                         "привязанная запись находится по своему uuid")
        self.assertNotEqual(panel._path("radar_1"), f"api/v2/admin/user/radar_1/")

    def test_remnawave_pages(self):
        panel = RemnawavePanel("https://r.example", token="t")
        rows = [{"username": f"u{i}", "telegramId": 100000 + i, "status": "ACTIVE",
                 "expireAt": "2030-01-01T00:00:00Z", "trafficLimitBytes": 0}
                for i in range(3)]
        rec, patch = patched(panel, {("GET", "api/users?start=0&size=500"):
                                     {"response": {"users": rows, "total": 3}}})
        with patch:
            clients = run(panel.list_clients())
        self.assertEqual([c.telegram for c in clients], ["100000", "100001", "100002"])

    def test_outline_ref_is_key_id(self):
        panel = OutlinePanel("https://1.2.3.4:1234/SeCrEt", cert=CERT)
        rec, patch = patched(panel, {("GET", "access-keys"): {"accessKeys": [
            {"id": "7", "name": "Мама 4242424242", "accessUrl": "ss://x"}]}})
        with patch:
            clients = run(panel.list_clients())
        self.assertEqual((clients[0].ref, clients[0].title), ("7", "Мама 4242424242"))


class OutlineTests(unittest.TestCase):
    def setUp(self):
        self.panel = OutlinePanel("https://1.2.3.4:1234/SeCrEt", cert=CERT)

    def test_cert_required(self):
        self.assertTrue(OutlinePanel("https://1.2.3.4/x").problems())
        self.assertEqual(self.panel.problems(), [])

    def test_create_by_our_id_and_disable_by_zero_limit(self):
        key = {"id": "radar_1", "name": "radar_1", "accessUrl": "ss://abc@1.2.3.4:5/?outline=1"}
        rec, patch = patched(self.panel, {
            ("PUT", "access-keys/radar_1"): key,
            ("PUT", "access-keys/radar_1/data-limit"): None,
            ("DELETE", "access-keys/radar_1/data-limit"): None,
        })
        with patch:
            account = run(self.panel.create_user("radar_1", 1_800_000_000, 0))
            run(self.panel.disable("radar_1"))
            run(self.panel.enable("radar_1"))
        self.assertEqual(account.subscription_url, key["accessUrl"])
        self.assertEqual(account.expire, 0)
        self.assertEqual(rec.last("PUT", "access-keys/radar_1/data-limit"),
                         {"limit": {"bytes": 0}})

    def test_no_expiry(self):
        self.assertFalse(OutlinePanel.supports_expiry)
        with self.assertRaises(PanelError):
            run(self.panel.set_expiry("radar_1", 1))

    def test_zero_limit_reads_as_disabled(self):
        self.assertFalse(vpnpanels.outline_account({"dataLimit": {"bytes": 0}}, 0).enabled)
        self.assertTrue(vpnpanels.outline_account({}, 0).enabled)


class WgEasyTests(unittest.TestCase):
    def setUp(self):
        self.panel = WgEasyPanel("https://wg.example", user="admin", password="pw")

    def test_basic_auth(self):
        self.assertTrue(self.panel._base_headers()["Authorization"].startswith("Basic "))
        self.assertFalse(WgEasyPanel.supports_traffic)

    def test_expiry_roundtrips_full_client(self):
        full = {"id": 5, "name": "radar_1", "enabled": True, "expiresAt": None,
                "ipv4Address": "10.8.0.5", "mtu": 1420}
        rec, patch = patched(self.panel, {
            ("GET", "api/client"): [{"id": 5, "name": "radar_1", "enabled": True}],
            ("GET", "api/client/5"): full,
            ("POST", "api/client/5"): {"success": True},
        })
        with patch:
            run(self.panel.set_expiry("radar_1", 1_800_000_000))
        body = rec.last("POST", "api/client/5")
        self.assertEqual((body["ipv4Address"], body["mtu"]), ("10.8.0.5", 1420))
        self.assertEqual(vpnpanels.parse_time(body["expiresAt"]), 1_800_000_000)

    def test_one_time_link(self):
        rec, patch = patched(self.panel, {
            ("GET", "api/client"): [{"id": 5, "name": "radar_1",
                                     "oneTimeLink": {"oneTimeLink": "abc"}}],
            ("POST", "api/client/5/generateOneTimeLink"): {"success": True},
        })
        with patch:
            self.assertEqual(run(self.panel.subscription_url("radar_1")),
                             "https://wg.example/cnf/abc")


# --------------------------------------------------------------------------
#  Несколько панелей и решение суперадминистратора
# --------------------------------------------------------------------------

class FakePanel(vpnpanels.Panel):
    """Панель в памяти: проверяет логику выдачи, а не разметку запросов."""

    def __init__(self, kind="fake", *, delay=0.0, broken=False, expiry=True):
        super().__init__(f"http://{kind}", token="t")
        self.kind = kind
        self.title = kind
        self.supports_expiry = expiry
        self.delay = delay
        self.broken = broken
        self.users = {}
        self.created = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def _maybe(self):
        await asyncio.sleep(self.delay)
        if self.broken:
            raise PanelError(f"{self.kind} недоступна")

    async def create_user(self, name, expire, traffic):
        await self._maybe()
        self.created += 1
        self.users[name] = Account(name, True, expire, traffic, 0, f"https://{self.kind}/{name}")
        return self.users[name]

    async def get_user(self, name):
        await self._maybe()
        return self.users.get(name)

    async def set_expiry(self, name, expire):
        old = self.users[name]
        self.users[name] = Account(name, old.enabled, expire, old.traffic_limit, 0,
                                   old.subscription_url)

    async def set_traffic(self, name, traffic):
        pass

    async def disable(self, name):
        await self._maybe()
        old = self.users[name]
        self.users[name] = Account(name, False, old.expire, 0, 0, old.subscription_url)

    async def enable(self, name):
        old = self.users[name]
        self.users[name] = Account(name, True, old.expire, 0, 0, old.subscription_url)

    async def check(self):
        await self._maybe()
        return f"{self.kind} ok"

    async def list_clients(self):
        await self._maybe()
        return [vpnpanels.PanelClient(name, name, self.tg.get(name, ""),
                                      (name, self.notes.get(name, "")), account)
                for name, account in self.users.items()]

    tg: dict = {}
    notes: dict = {}


class MultiPanelBase(unittest.TestCase):
    SUPER = "superadmin"

    def setUp(self):
        self.meta = {}
        self.panels = {
            "1": FakePanel("3xui"),
            "2": FakePanel("remnawave"),
            "3": FakePanel("outline", expiry=False),
        }

        async def meta_get(key, default=None):
            return json.loads(json.dumps(self.meta.get(key, default)))

        async def meta_set(key, value):
            self.meta[key] = json.loads(json.dumps(value))

        from radar import storage

        features.set_local("vpn", True)
        self.patches = [
            mock.patch.object(storage, "meta_get", meta_get),
            mock.patch.object(storage, "meta_set", meta_set),
            mock.patch.object(vpn, "slots", self._slots),
            mock.patch.object(vpn, "_setting", lambda key: ""),
        ]
        for patch in self.patches:
            patch.start()

    def _slots(self):
        return [vpn.Slot(int(key), f"Панель {key}", panel)
                for key, panel in sorted(self.panels.items())]

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        features.apply({})


class SuperadminOnlyTests(MultiPanelBase):
    def test_only_superadmin_decides(self):
        for role in ("user", "moderator", "admin", None):
            self.assertFalse(vpn.can_decide(role), role)
            with self.assertRaises(PanelError):
                run(vpn.issue("1", ["1"], "9", role))
            with self.assertRaises(PanelError):
                run(vpn.deny("1", "9", role))
            with self.assertRaises(PanelError):
                run(vpn.extend("1", "1", 10, role))
            with self.assertRaises(PanelError):
                run(vpn.set_enabled("1", "1", True, role))
            with self.assertRaises(PanelError):
                run(vpn.revoke("1", "1", role))
        self.assertEqual(self.panels["1"].created, 0)

    def test_request_does_not_issue(self):
        """Заявка — только заявка: ни одной записи в панелях."""
        self.assertEqual(run(vpn.request("1")), vpn.PENDING)
        self.assertEqual(run(vpn.request("1")), vpn.PENDING)
        self.assertEqual(run(vpn.pending()), ["1"])
        self.assertEqual(sum(panel.created for panel in self.panels.values()), 0)

    def test_no_auto_issue_setting_left(self):
        from radar import secrets

        self.assertNotIn("VPN_AUTO_ROLE", secrets.BY_KEY)
        self.assertFalse(hasattr(vpn, "issues_without_request"))


class MultiPanelTests(MultiPanelBase):
    def test_issue_on_chosen_panels_only(self):
        run(vpn.request("1"))
        results = run(vpn.issue("1", ["1", "3"], "9", self.SUPER))
        self.assertEqual(set(results), {"1", "3"})
        self.assertEqual((self.panels["1"].created, self.panels["2"].created,
                          self.panels["3"].created), (1, 0, 1))
        entry = run(vpn.record("1"))
        self.assertEqual(entry["state"], vpn.ACTIVE)
        self.assertEqual(vpn.issued_slots(entry), ["1", "3"])

    def test_panel_without_expiry_gets_forever(self):
        run(vpn.issue("1", ["1", "3"], "9", self.SUPER))
        name = vpnpanels.account_name("1")
        self.assertGreater(self.panels["1"].users[name].expire, 0)
        self.assertEqual(self.panels["3"].users[name].expire, 0)
        with self.assertRaises(PanelError):
            run(vpn.extend("1", "3", 10, self.SUPER))

    def test_parallel_not_sequential(self):
        """Три панели по 0.3 с каждая — вместе заметно меньше 0.9 с."""
        for panel in self.panels.values():
            panel.delay = 0.3
        started = time.monotonic()
        run(vpn.issue("1", ["1", "2", "3"], "9", self.SUPER))
        self.assertLess(time.monotonic() - started, 0.85)

    def test_one_broken_panel_does_not_block_others(self):
        self.panels["2"].broken = True
        results = run(vpn.issue("1", ["1", "2", "3"], "9", self.SUPER))
        self.assertIsInstance(results["1"], Account)
        self.assertIsInstance(results["2"], PanelError)
        self.assertIsInstance(results["3"], Account)
        self.assertEqual(vpn.issued_slots(run(vpn.record("1"))), ["1", "3"])
        statuses = run(vpn.statuses("1"))
        self.assertEqual(set(statuses), {"1", "3"})

    def test_unexpected_exception_is_contained(self):
        async def boom(name):
            raise RuntimeError("внутренняя ошибка")

        self.panels["2"].get_user = boom
        results = run(vpn.issue("1", ["1", "2"], "9", self.SUPER))
        self.assertIsInstance(results["2"], PanelError)
        self.assertIsInstance(results["1"], Account)

    def test_reissue_keeps_key_per_panel(self):
        first = run(vpn.issue("1", ["1", "2"], "9", self.SUPER))
        run(vpn.set_enabled("1", "2", False, self.SUPER))
        second = run(vpn.issue("1", ["1", "2"], "9", self.SUPER))
        for key in ("1", "2"):
            self.assertEqual(first[key].subscription_url, second[key].subscription_url)
            self.assertEqual(self.panels[key].created, 1)
        self.assertTrue(second["2"].enabled)

    def test_extend_one_panel_leaves_others(self):
        run(vpn.issue("1", ["1", "2"], "9", self.SUPER))
        name = vpnpanels.account_name("1")
        before = {key: self.panels[key].users[name].expire for key in ("1", "2")}
        after = run(vpn.extend("1", "2", 10, self.SUPER)).expire
        self.assertEqual(after - before["2"], 10 * vpn.DAY)
        self.assertEqual(self.panels["1"].users[name].expire, before["1"])

    def test_revoke_disables_and_forgets(self):
        run(vpn.issue("1", ["1", "2"], "9", self.SUPER))
        run(vpn.revoke("1", "1", self.SUPER))
        name = vpnpanels.account_name("1")
        self.assertFalse(self.panels["1"].users[name].enabled)
        self.assertEqual(vpn.issued_slots(run(vpn.record("1"))), ["2"])

    def test_check_all_concurrently_with_failures(self):
        self.panels["3"].broken = True
        results = run(vpn.check_all())
        self.assertEqual(results["1"], (True, "3xui ok"))
        self.assertFalse(results["3"][0])

    def test_link_not_stored_in_db(self):
        run(vpn.issue("1", ["1", "2", "3"], "9", self.SUPER))
        self.assertNotIn("https://", json.dumps(self.meta))

    def test_replaced_panel_is_not_trusted(self):
        run(vpn.issue("1", ["1"], "9", self.SUPER))
        self.panels["1"] = FakePanel("marzban")
        result = run(vpn.statuses("1"))["1"]
        self.assertIsInstance(result, PanelError)
        self.assertIn("заменена", str(result))

    def test_legacy_record_from_5_0(self):
        self.meta[vpn.META_KEY] = {"1": {"state": "active", "name": "radar_1",
                                         "panel": "3xui", "issued": 1, "by": "9"}}
        self.assertEqual(vpn.issued_slots(run(vpn.record("1"))), ["1"])

    def test_deny_and_request_again(self):
        run(vpn.request("1"))
        run(vpn.deny("1", "9", self.SUPER))
        self.assertEqual(run(vpn.record("1"))["state"], vpn.DENIED)
        self.assertEqual(run(vpn.request("1")), vpn.PENDING)


class AdoptTests(MultiPanelBase):
    """Привязка клиентов, заведённых в панелях не ботом (5.7.2)."""

    UID = "4242424242"

    def setUp(self):
        super().setUp()
        from radar import storage

        self.users = mock.patch.object(storage, "users", lambda: {
            self.UID: {"role": "user"}, "5550001": {"role": "user"}, "vk:4242424242": {}})
        self.users.start()
        for panel in self.panels.values():
            panel.tg, panel.notes = {}, {}
        far = int(time.time()) + 10 * vpn.DAY
        self.panels["1"].users["old_client"] = Account("old_client", True, far, 0, 0, "https://x/1")
        self.panels["1"].tg = {"old_client": self.UID}
        self.panels["2"].users["user 4242424242"] = Account("user 4242424242", True, far, 0, 0, "")
        self.panels["2"].users["order_42424242421"] = Account("order_42424242421", True, far, 0, 0, "")

    def tearDown(self):
        self.users.stop()
        super().tearDown()

    def test_match_reasons(self):
        client = vpnpanels.PanelClient("a", "a", "", ("vpn_4242424242", ""))
        self.assertTrue(vpn.match_reason(client, self.UID))
        self.assertFalse(vpn.match_reason(
            vpnpanels.PanelClient("a", "a", "", ("42424242421",)), self.UID),
            "часть другого числа — не совпадение")
        self.assertFalse(vpn.match_reason(
            vpnpanels.PanelClient("a", "a", "", ("id 12345",)), "12345"),
            "короткие числа не сопоставляются")
        self.assertIn("поле", vpn.match_reason(
            vpnpanels.PanelClient("a", "a", self.UID, ()), self.UID))

    def test_find_bind_and_serve_by_own_name(self):
        with self.assertRaises(PanelError):
            run(vpn.matches("admin"))
        found, errors = run(vpn.matches(self.SUPER))
        self.assertEqual(errors, {})
        self.assertEqual(sorted((m.key, m.ref, m.uid) for m in found),
                         [("1", "old_client", self.UID), ("2", "user 4242424242", self.UID)])
        for match in found:
            run(vpn.bind(match.uid, match.key, match.ref, "9", self.SUPER))
        self.assertEqual(run(vpn.matches(self.SUPER))[0], [], "привязанное не предлагается")
        before = self.panels["1"].users["old_client"].expire
        run(vpn.extend(self.UID, "1", 5, self.SUPER))
        self.assertEqual(self.panels["1"].users["old_client"].expire, before + 5 * vpn.DAY)
        run(vpn.issue(self.UID, ["1", "2"], "9", self.SUPER))
        self.assertEqual((self.panels["1"].created, self.panels["2"].created), (0, 0),
                         "выдача нашла привязанные записи, а не завела вторые")
        statuses = run(vpn.statuses(self.UID))
        self.assertEqual(statuses["1"].name, "old_client")

    def test_bind_conflicts(self):
        run(vpn.bind(self.UID, "1", "old_client", "9", self.SUPER))
        with self.assertRaises(PanelError):
            run(vpn.bind("5550001", "1", "old_client", "9", self.SUPER))
        with self.assertRaises(PanelError):
            run(vpn.bind(self.UID, "1", "nobody", "9", self.SUPER))
        run(vpn.issue("5550001", ["2"], "9", self.SUPER))
        with self.assertRaises(PanelError):
            run(vpn.bind("5550001", "2", "user 4242424242", "9", self.SUPER))

    def test_forget_leaves_panel_untouched(self):
        run(vpn.bind(self.UID, "1", "old_client", "9", self.SUPER))
        run(vpn.forget(self.UID, "1", self.SUPER))
        self.assertTrue(self.panels["1"].users["old_client"].enabled)
        self.assertEqual(vpn.issued_slots(run(vpn.record(self.UID))), [])

    def test_deleted_bound_record_falls_back_to_own_name(self):
        run(vpn.bind(self.UID, "1", "old_client", "9", self.SUPER))
        del self.panels["1"].users["old_client"]
        run(vpn.issue(self.UID, ["1"], "9", self.SUPER))
        name = vpnpanels.account_name(self.UID)
        self.assertIn(name, self.panels["1"].users)
        self.assertEqual(run(vpn.record(self.UID))["panels"]["1"]["name"], name)

    def test_clients_excludes_bound(self):
        run(vpn.bind(self.UID, "1", "old_client", "9", self.SUPER))
        self.assertEqual([c.ref for c in run(vpn.clients("1", self.SUPER))], [])


class SelftestTests(MultiPanelBase):
    """Полный круг, которым автор проверяет живые панели на сервере."""

    def test_full_cycle_leaves_account_disabled(self):
        notes = run(vpn.selftest_panel(self.panels["1"]))
        self.assertIn("полный круг пройден", notes[-1])
        self.assertFalse(self.panels["1"].users[vpn.SELFTEST_NAME].enabled)

    def test_panel_that_ignores_changes_fails(self):
        """Панель ответила «успешно» и ничего не сделала — круг не проходит."""
        panel = self.panels["2"]

        async def lazy_disable(name):
            return None

        panel.disable = lazy_disable
        with self.assertRaises(PanelError) as caught:
            run(vpn.selftest_panel(panel))
        self.assertIn("не выключилась", str(caught.exception))

    def test_all_panels_at_once(self):
        self.panels["3"].broken = True
        results = run(vpn.selftest_all())
        self.assertTrue(results["1"][0] and results["2"][0])
        self.assertFalse(results["3"][0])


class CliTests(unittest.TestCase):
    def test_selftest_needs_yes(self):
        from radar import cli

        fake = [vpn.Slot(1, "A", FakePanel("a"))]
        with mock.patch.object(vpn, "slots", lambda: fake):
            self.assertEqual(cli.main(["vpn", "selftest"]), cli.NEEDS_YES)

    def test_check_reports_each_panel(self):
        from radar import cli

        fake = [vpn.Slot(1, "A", FakePanel("a")), vpn.Slot(2, "B", FakePanel("b", broken=True))]
        with mock.patch.object(vpn, "slots", lambda: fake):
            self.assertEqual(cli.main(["vpn", "check"]), cli.FAILED)
            fake.pop()
            self.assertEqual(cli.main(["vpn", "check"]), cli.OK)


class SlotConfigTests(unittest.TestCase):
    def test_slots_from_settings_and_legacy_names(self):
        values = {
            "VPN_PANEL": "3xui", "VPN_PANEL_URL": "http://old", "VPN_PANEL_TOKEN": "t",
            "VPN_XUI_INBOUND": "2",
            "VPN3_KIND": "outline", "VPN3_URL": "https://o/secret", "VPN3_CERT": CERT,
            "VPN3_TITLE": "Нидерланды",
            "VPN4_KIND": "amnezia",
        }
        with mock.patch.object(vpn, "_setting", lambda key: values.get(key, "")):
            found = vpn.slots()
            self.assertEqual([item.number for item in found], [1, 3])
            self.assertIsInstance(found[0].client, XuiPanel)
            self.assertEqual(found[0].client.inbound, 2)
            self.assertEqual(found[1].title, "Нидерланды")
            self.assertEqual(vpn.unknown_kinds(), ["слот 4: «amnezia»"])

    def test_settings_have_six_slots(self):
        from radar import secrets

        for slot in range(1, vpn.SLOTS + 1):
            for field in vpn.FIELDS:
                self.assertIn(f"VPN{slot}_{field}", secrets.BY_KEY)
        self.assertTrue(secrets.BY_KEY["VPN1_TOKEN"].secret)
        self.assertTrue(secrets.BY_KEY["VPN1_PASS"].secret)


class NotifyTests(unittest.TestCase):
    def test_requests_reach_superadmins_only(self):
        from radar import storage
        from radar.handlers import vpn as handler

        people = {"1": {"role": "user"}, "2": {"role": "admin"},
                  "3": {"role": "superadmin"}, "4": {"role": "moderator"}}
        sent = []

        async def fake_send(target, text, markup=None):
            sent.append(target)
            return True

        with mock.patch.object(storage, "users", lambda: people), \
                mock.patch.object(storage, "get_user", lambda uid: people.get(uid)), \
                mock.patch.object(handler, "send_html", fake_send):
            run(handler._notify_superadmins("1"))
        self.assertEqual(sent, ["3"])


class BoundaryTests(unittest.TestCase):
    """Границы из дорожной карты, закреплённые строкой."""

    def test_flag_off_by_default(self):
        self.assertFalse(features.BY_KEY["vpn"].default)

    def test_no_sdk_dependencies(self):
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as handle:
            text = handle.read().lower()
        for package in ("remnawave", "httpx", "orjson", "marzban"):
            self.assertNotIn(package, text)

    def test_monitor_does_not_touch_vpn(self):
        with open(os.path.join(ROOT, "radar", "monitor.py"), encoding="utf-8") as handle:
            self.assertNotIn("vpn", handle.read().lower())

    def test_tls_verification_never_disabled(self):
        with open(os.path.join(ROOT, "radar", "vpnpanels.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("ssl=False", source)
        self.assertNotIn("verify_ssl=False", source)


if __name__ == "__main__":
    unittest.main()
