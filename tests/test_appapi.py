#!/usr/bin/env python3
"""API для приложений HydraVPN (5.9.1): код, токен, подписки, отзыв.

Транспорт (заголовки, коды ответов) проверяет `tools/app_http_check.py`
на настоящем aiohttp; здесь — логика на заглушках.
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
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import appapi, features, storage, vpn  # noqa: E402
from radar.vpnpanels import Account, PanelError  # noqa: E402
from radar.web import auth  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.meta: dict = {}
        appapi._codes.clear()
        auth._attempts.clear()

        async def meta_get(key, default=None):
            return self.meta.get(key, default)

        async def meta_set(key, value):
            self.meta[key] = value

        self.patches = [
            mock.patch.object(storage, "meta_get", meta_get),
            mock.patch.object(storage, "meta_set", meta_set),
            mock.patch.object(features, "enabled", lambda name: True),
            mock.patch.object(storage, "get_user",
                              lambda uid: {"username": "ivan", "blocked": False}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()

    def link(self, uid="42", device="Pixel", app="hydravpn"):
        code = appapi.issue_code(uid)
        return run(appapi.exchange(code, device, app))


class CodeAndTokenTests(Base):
    def test_code_is_single_use(self) -> None:
        code = appapi.issue_code("42")
        self.assertTrue(run(appapi.exchange(code, "a", "hydravpn"))[0])
        token, _, why = run(appapi.exchange(code, "a", "hydravpn"))
        self.assertEqual(token, "")
        self.assertTrue(why)

    def test_code_expires(self) -> None:
        code = appapi.issue_code("42", now=1000)
        token, _, _ = run(appapi.exchange(code, "a", "hydravpn",
                                          now=1000 + appapi.CODE_TTL + 1))
        self.assertEqual(token, "")

    def test_new_code_kills_old_one(self) -> None:
        first = appapi.issue_code("42")
        appapi.issue_code("42")
        self.assertEqual(run(appapi.exchange(first, "a", "hydravpn"))[0], "")

    def test_token_is_stored_hashed(self) -> None:
        token, _, _ = self.link()
        stored = repr(self.meta)
        self.assertNotIn(token, stored)
        self.assertEqual(run(appapi.session_of(token))["uid"], "42")

    def test_wrong_token(self) -> None:
        self.link()
        self.assertIsNone(run(appapi.session_of("nope")))
        self.assertIsNone(run(appapi.session_of("")))

    def test_brute_force_is_limited(self) -> None:
        for _ in range(auth.MAX_ATTEMPTS):
            run(appapi.exchange("00000000", "a", "x", address="1.2.3.4"))
        code = appapi.issue_code("42")
        token, _, why = run(appapi.exchange(code, "a", "x", address="1.2.3.4"))
        self.assertEqual(token, "")
        self.assertIn("много", why)

    def test_device_limit_evicts_oldest(self) -> None:
        tokens = []
        for index in range(appapi.MAX_DEVICES + 1):
            token, _, _ = run(appapi.exchange(appapi.issue_code("42"), f"d{index}",
                                              "hydravpn", now=1000 + index))
            tokens.append(token)
        self.assertEqual(len(run(appapi.devices("42"))), appapi.MAX_DEVICES)
        self.assertIsNone(run(appapi.session_of(tokens[0])))
        self.assertIsNotNone(run(appapi.session_of(tokens[-1])))

    def test_revoke(self) -> None:
        token, device_id, _ = self.link()
        other, _, _ = self.link(uid="7")
        self.assertEqual(run(appapi.revoke("42", device_id)), 1)
        self.assertIsNone(run(appapi.session_of(token)))
        self.assertIsNotNone(run(appapi.session_of(other)))
        self.assertTrue(run(appapi.revoke_token(other)))
        self.assertFalse(run(appapi.revoke_token(other)))

    def test_unknown_app_and_device_name_are_cleaned(self) -> None:
        token, _, _ = self.link(device="\x00\x07Мой\nтелефон" + "я" * 100, app="evil")
        found = run(appapi.session_of(token))
        self.assertEqual(found["app"], "other")
        self.assertLessEqual(len(found["device"]), 40)
        self.assertNotIn("\n", found["device"])


class SubscriptionTests(Base):
    def setUp(self) -> None:
        super().setUp()
        client = SimpleNamespace(kind="3xui", link_kind="subscription")
        self.slots = [SimpleNamespace(key="1", title="Главный", client=client),
                      SimpleNamespace(key="2", title="Запасной", client=client)]
        self.entry = {"state": "active", "panels": {"1": {"name": "radar_42"},
                                                    "2": {"name": "radar_42"}}}
        self.results = {
            "1": Account("radar_42", True, 1900000000, 10 ** 10, 5 * 10 ** 8,
                         "https://sub.example/xyz"),
            "2": PanelError("нет связи"),
        }

        async def record(uid):
            return self.entry

        async def statuses(uid):
            return self.results

        async def subscription(uid, key):
            return "https://fallback.example/" + key

        for target, value in (("record", record), ("statuses", statuses),
                              ("subscription", subscription),
                              ("slots", lambda: self.slots)):
            patch = mock.patch.object(vpn, target, value)
            patch.start()
            self.patches.append(patch)

    def test_items(self) -> None:
        items = run(appapi.subscriptions("42"))
        self.assertEqual([item["panel"] for item in items], ["1", "2"])
        first, second = items
        self.assertEqual(first["url"], "https://sub.example/xyz")
        self.assertEqual(first["state"], "ok")
        self.assertEqual(first["traffic_limit"], 10 ** 10)
        self.assertEqual(second["state"], "panel_error")
        self.assertEqual(second["url"], "")

    def test_url_falls_back_to_panel_call(self) -> None:
        self.results["1"] = Account("radar_42", True, 0, 0, 0, "")
        first = run(appapi.subscriptions("42"))[0]
        self.assertEqual(first["url"], "https://fallback.example/1")

    def test_nothing_issued(self) -> None:
        self.entry = {"state": "denied", "panels": {}}
        self.assertEqual(run(appapi.subscriptions("42")), [])

    def test_blocked_user_gets_nothing(self) -> None:
        with mock.patch.object(storage, "get_user",
                               lambda uid: {"username": "x", "blocked": True}):
            self.assertEqual(run(appapi.subscriptions("42")), [])

    def test_profile(self) -> None:
        data = run(appapi.profile("42"))
        self.assertEqual(data["user_id"], "42")
        self.assertEqual(data["vpn"]["panels"], 2)
        self.assertEqual(data["vpn"]["state"], "active")


if __name__ == "__main__":
    unittest.main()
