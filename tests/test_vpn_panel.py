#!/usr/bin/env python3
"""Лимит устройств на подписку и раздел «VPN» веб-панели (5.9.2).

До 5.9.2 выдача вручную не задавала число устройств вовсе, а настройки VPN
были разбросаны: тумблеры в «Возможностях», значения в «Ключах», устройства
приложений нигде. Здесь закреплено: по умолчанию 25 на подписку, значение
правится в панели, а настройки VPN собраны в разделе «VPN».
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

from radar import appapi, secrets, storage, vpn  # noqa: E402
from radar.web import auth, panel  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class DeviceLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values: dict[str, str] = {}
        patch = mock.patch.object(vpn, "_setting", lambda key: self.values.get(key, ""))
        patch.start()
        self.addCleanup(patch.stop)

    def test_default_is_25(self) -> None:
        self.assertEqual(vpn.default_devices(), 25)

    def test_setting_overrides_and_zero_means_unlimited(self) -> None:
        self.values["VPN_DEVICES"] = "10"
        self.assertEqual(vpn.default_devices(), 10)
        self.values["VPN_DEVICES"] = "0"
        self.assertEqual(vpn.default_devices(), 0)

    def test_garbage_falls_back_and_huge_is_capped(self) -> None:
        self.values["VPN_DEVICES"] = "много"
        self.assertEqual(vpn.default_devices(), 25)
        self.values["VPN_DEVICES"] = "999999"
        self.assertEqual(vpn.default_devices(), vpn.MAX_DEVICES_SETTING)

    def test_issue_passes_the_limit_to_the_panels(self) -> None:
        captured: dict = {}

        async def fake_grant(uid, targets, by, **kwargs):
            captured.update(kwargs)
            return {}

        slot = SimpleNamespace(key="1")
        with mock.patch.object(vpn, "_grant", fake_grant), \
                mock.patch.object(vpn, "_pick", lambda keys: [slot]), \
                mock.patch.object(vpn, "ready", lambda: (True, "")), \
                mock.patch.object(vpn, "can_decide", lambda role: True):
            run(vpn.issue("42", ["1"], "1", "superadmin"))
        self.assertEqual(captured.get("devices"), 25)

    def test_setting_is_declared_in_the_vpn_group(self) -> None:
        setting = secrets.BY_KEY["VPN_DEVICES"]
        self.assertEqual(setting.group, "VPN")
        self.assertFalse(setting.secret)


class PanelPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = SimpleNamespace(user_key="1", role="superadmin")
        self.patches = [
            mock.patch.object(auth, "csrf_token", lambda session: "CSRF"),
            mock.patch.object(vpn, "ready", lambda: (True, "")),
            mock.patch.object(vpn, "slots", lambda: []),
            mock.patch.object(storage, "get_user", lambda uid: {"username": "ivan"}),
        ]

        async def pending():
            return ["7"]

        async def issued():
            return ["42", "43"]

        async def devices():
            return [{"uid": "42", "id": "a1", "device": "Pixel 8", "app": "hydravpn",
                     "created": 1790000000, "seen": 1790000500}]

        self.patches += [mock.patch.object(vpn, "pending", pending),
                         mock.patch.object(vpn, "issued", issued),
                         mock.patch.object(appapi, "all_devices", devices)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_vpn_settings_live_on_the_vpn_page_only(self) -> None:
        keys = panel._keys_body(self.session)
        self.assertNotIn("VPN_DEVICES", keys)
        self.assertNotIn("VPN_PLANS", keys)
        self.assertIn('href="/vpn"', keys)
        page = run(panel._vpn_body(self.session))
        for needle in ("VPN_DEVICES", "VPN_DAYS", "VPN_PLANS"):
            self.assertIn(needle, page)
        # Слоты панелей — форма на своей странице, а не десяток ключей (5.9.2.1).
        self.assertNotIn("VPN1_KIND", page)
        self.assertIn('href="/vpn/panels"', page)

    def test_forms_return_to_the_vpn_page(self) -> None:
        page = run(panel._vpn_body(self.session))
        self.assertIn('name="back" value="/vpn"', page)
        self.assertIn('action="/features/toggle"', page)
        for flag in ("vpn", "vpn_sales", "app_api"):
            self.assertIn(f'name="key" value="{flag}"', page)

    def test_devices_and_counts_are_shown_without_tokens(self) -> None:
        page = run(panel._vpn_body(self.session))
        self.assertIn("Pixel 8", page)
        self.assertIn("@ivan", page)
        self.assertIn('action="/vpn/app-revoke"', page)
        self.assertIn("Заявок ждёт решения: 1", page)
        self.assertIn("выдано доступов: 2", page)

    def test_group_split(self) -> None:
        self.assertTrue(panel._is_vpn_group("VPN"))
        self.assertTrue(panel._is_vpn_group("VPN 3"))
        self.assertTrue(panel._is_vpn_group("Продажа VPN"))
        self.assertFalse(panel._is_vpn_group("Discord"))

    def test_page_is_for_the_superadmin_only(self) -> None:
        self.assertIn("/vpn", [href for href, *_ in panel._nav_groups("superadmin")])
        for role in ("admin", "moderator", "user"):
            self.assertNotIn("/vpn", [href for href, *_ in panel._nav_groups(role)], role)


if __name__ == "__main__":
    unittest.main()
