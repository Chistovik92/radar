#!/usr/bin/env python3
"""Страницы панели 5.9.2.1: VPN-панели, доступы и заказы, подписка бота.

До 5.9.2.1 панель VPN можно было завести только правкой десяти ключей
вручную, а подпиской бота из веб-панели управлять было нельзя вовсе.
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
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import redeem, secrets, storage, subscription, vpn, vpnsales, vpnslots  # noqa: E402
from radar.vpnpanels import Account  # noqa: E402
from radar.web import adminpages, panel  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Form(dict):
    """Минимальная замена данным формы aiohttp."""

    def getall(self, key, default=None):
        value = self.get(key, default or [])
        return value if isinstance(value, list) else [value]


class SlotStore(unittest.TestCase):
    """Слоты читаются из «окружения», пишутся пачкой — проверяем и то и другое."""

    def setUp(self) -> None:
        self.env: dict[str, str] = {}
        self.writes: list[dict[str, str]] = []

        def write_many(values):
            self.writes.append(dict(values))
            self.env.update(values)
            return True

        for patch in (mock.patch.object(vpn, "_setting", lambda key: self.env.get(key, "")),
                      mock.patch.object(secrets, "write_many", write_many)):
            patch.start()
            self.addCleanup(patch.stop)

    def good(self, **extra) -> dict[str, str]:
        form = {"KIND": "3xui", "TITLE": "NL", "URL": "https://panel.example:2053/x/",
                "TOKEN": "tok", "INBOUND": "1", "SUB_URL": "https://sub.example/s/"}
        form.update(extra)
        return form

    def test_save_writes_all_fields_in_one_pass(self) -> None:
        self.assertEqual(vpnslots.save(2, self.good()), "")
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.env["VPN2_KIND"], "3xui")
        self.assertEqual(self.env["VPN2_URL"], "https://panel.example:2053/x/")
        self.assertEqual(set(self.writes[0]), {f"VPN2_{f}" for f in vpnslots.FIELDS})
        self.assertTrue(vpnslots.configured(2))

    def test_alias_kind_is_normalised(self) -> None:
        self.assertEqual(vpnslots.save(1, self.good(KIND="3x-ui")), "")
        self.assertEqual(self.env["VPN1_KIND"], "3xui")

    def test_empty_secret_keeps_the_old_one_on_edit(self) -> None:
        vpnslots.save(1, self.good())
        self.assertEqual(vpnslots.save(1, self.good(TOKEN="", TITLE="Другое")), "")
        self.assertEqual(self.env["VPN1_TOKEN"], "tok")
        self.assertEqual(self.env["VPN1_TITLE"], "Другое")

    def test_empty_plain_field_is_cleared(self) -> None:
        vpnslots.save(1, self.good())
        vpnslots.save(1, self.good(INBOUND=""))
        self.assertEqual(self.env["VPN1_INBOUND"], "")

    def test_validation_messages(self) -> None:
        cases = [
            ({"KIND": ""}, "вид"),
            ({"KIND": "amnezia"}, "SSH"),
            ({"KIND": "nope"}, "Незнакомый"),
            ({"URL": ""}, "адрес"),
            ({"URL": "ftp://x"}, "http"),
            ({"INBOUND": "abc"}, "число"),
            ({"SUB_URL": "sub.example"}, "http"),
            ({"CERT": "zz"}, "64"),
            ({"TOKEN": ""}, "токен"),
        ]
        for patch, word in cases:
            form = self.good()
            form.update(patch)
            problem = vpnslots.save(3, form)
            self.assertIn(word.lower(), problem.lower(), (patch, problem))
        self.assertEqual(self.writes, [], "негодный слот не должен ничего записывать")

    def test_outline_needs_certificate_but_not_token(self) -> None:
        form = {"KIND": "outline", "URL": "https://1.2.3.4:5/abc"}
        self.assertIn("отпечаток", vpnslots.save(1, form).lower())
        form["CERT"] = ("AB:" * 31) + "AB"
        self.assertEqual(vpnslots.save(1, form), "")
        self.assertEqual(self.env["VPN1_CERT"], ("ab" * 32))

    def test_login_and_password_instead_of_token(self) -> None:
        form = self.good(TOKEN="", USER="admin", PASS="pw")
        self.assertEqual(vpnslots.save(1, form), "")

    def test_remove_clears_every_field_and_legacy_names_for_slot_one(self) -> None:
        vpnslots.save(1, self.good())
        self.assertTrue(vpnslots.remove(1))
        cleared = self.writes[-1]
        self.assertTrue(all(value == "" for value in cleared.values()))
        self.assertIn("VPN_PANEL", cleared)
        self.assertFalse(vpnslots.configured(1))
        self.assertTrue(vpnslots.remove(2))
        self.assertNotIn("VPN_PANEL", self.writes[-1])

    def test_free_number_and_bad_numbers(self) -> None:
        self.assertEqual(vpnslots.free_number(), 1)
        vpnslots.save(1, self.good())
        self.assertEqual(vpnslots.free_number(), 2)
        self.assertNotEqual(vpnslots.save(99, self.good()), "")
        self.assertFalse(vpnslots.remove(0))


class WriteManyTests(unittest.TestCase):
    def test_one_backup_and_one_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# комментарий\nA=1\nB=2\n")
            calls = []
            with mock.patch.object(secrets, "ENV_PATH", path), \
                    mock.patch("radar.backup.backup_env", lambda: calls.append(1)), \
                    mock.patch.dict(os.environ, {}, clear=False):
                self.assertTrue(secrets.write_many({"A": "10", "C": "3", "D": ""}))
                self.assertEqual(os.environ["C"], "3")
            text = open(path, encoding="utf-8").read()
            self.assertIn("# комментарий", text)
            self.assertIn("A=10\n", text)
            self.assertIn("B=2\n", text)
            self.assertIn("C=3\n", text)
            self.assertIn("D=\n", text)
            self.assertEqual(len(calls), 1)

    def test_newline_is_refused(self) -> None:
        self.assertFalse(secrets.write_many({"A": "x\ny"}))


class SettingValidationTests(unittest.TestCase):
    def test_digest_plans(self) -> None:
        self.assertEqual(panel._validate_setting("DIGEST_PLANS", "30:150, 90:400"), "")
        for bad in ("30", "30:0", "abc", "30:150;90:400"):
            self.assertTrue(panel._validate_setting("DIGEST_PLANS", bad), bad)

    def test_vpn_plans(self) -> None:
        self.assertEqual(panel._validate_setting("VPN_PLANS", "30:0:3:199; 90:0:3:499"), "")
        self.assertTrue(panel._validate_setting("VPN_PLANS", "30:0:3:199; мусор"))

    def test_numbers(self) -> None:
        self.assertEqual(panel._validate_setting("VPN_DEVICES", "25"), "")
        self.assertTrue(panel._validate_setting("VPN_DEVICES", "много"))
        self.assertTrue(panel._validate_setting("VPN_DAYS", "0"))
        self.assertEqual(panel._validate_setting("VPN_DAYS", ""), "")

    def test_groups_with_their_own_page_leave_keys(self) -> None:
        self.assertTrue(panel._in_own_section("VPN 2"))
        self.assertTrue(panel._in_own_section("Подписка бота"))
        self.assertFalse(panel._in_own_section("Discord"))
        self.assertEqual(secrets.BY_KEY["DIGEST_PLANS"].group, "Подписка бота")


class SubscriptionRevokeTests(unittest.TestCase):
    def test_grant_then_revoke_clears_every_part(self) -> None:
        user = {"role": "user", "digest": {"paid_until": "2999-01-01T00:00:00+00:00"},
                "media_quota": {"paid_until": "2999-02-01T00:00:00+00:00"}}
        subscription.grant(user, 10)
        self.assertTrue(subscription.paid(user))
        self.assertTrue(subscription.revoke(user))
        self.assertFalse(subscription.paid(user))
        self.assertEqual(subscription.paid_until(user), "")
        self.assertFalse(subscription.revoke(user), "второй раз снимать нечего")

    def test_trial_stays_used(self) -> None:
        user = {"role": "user"}
        subscription.start_trial(user)
        subscription.revoke(user)
        self.assertTrue(subscription.trial_used(user))
        self.assertFalse(subscription.start_trial(user))


class SubscriptionPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.users = {
            "42": {"username": "ivan", "role": "user"},
            "43": {"username": "petr", "role": "user"},
        }
        subscription.grant(self.users["42"], 30)
        self.saved: list[str] = []
        self.codes = [{"code": "ABCDE-1", "days": 28, "used_by": "", "used_at": ""}]

        async def save(uid=None):
            self.saved.append(str(uid))

        async def load():
            return list(self.codes)

        for patch in (mock.patch.object(storage, "users", lambda: self.users),
                      mock.patch.object(storage, "get_user", lambda uid: self.users.get(str(uid))),
                      mock.patch.object(storage, "save", save),
                      mock.patch.object(redeem, "load", load)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_default_list_is_paid_people_and_search_finds_others(self) -> None:
        page = run(adminpages.subscriptions_body("CSRF"))
        self.assertIn("@ivan", page)
        self.assertNotIn("@petr", page)
        self.assertIn("ABCDE-1", page)
        self.assertIn("DIGEST_PLANS", page)
        found = run(adminpages.subscriptions_body("CSRF", query="pet"))
        self.assertIn("@petr", found)
        self.assertNotIn("@ivan", found)

    def test_grant_and_revoke_save_the_user(self) -> None:
        done, failed = run(adminpages.subscriptions_act(
            Form(action="grant", uid="43", days="15")))
        self.assertEqual(failed, "")
        self.assertTrue(subscription.paid(self.users["43"]))
        self.assertEqual(self.saved, ["43"])
        done, failed = run(adminpages.subscriptions_act(Form(action="revoke", uid="43")))
        self.assertEqual(failed, "")
        self.assertFalse(subscription.paid(self.users["43"]))

    def test_bad_input_is_refused_without_saving(self) -> None:
        for form in (Form(action="grant", uid="43", days="0"),
                     Form(action="grant", uid="43", days="99999"),
                     Form(action="grant", uid="43", days="x"),
                     Form(action="grant", uid="999", days="5"),
                     Form(action="nope", uid="43")):
            _, failed = run(adminpages.subscriptions_act(form))
            self.assertTrue(failed, form)
        self.assertEqual(self.saved, [])

    def test_codes_add_and_drop(self) -> None:
        async def add(text, days):
            return ["NEWCODE1"], ["!!"]

        async def drop(code):
            return code == "ABCDE-1"

        with mock.patch.object(redeem, "add", add), mock.patch.object(redeem, "drop", drop):
            done, failed = run(adminpages.subscriptions_act(
                Form(action="code_add", codes="NEWCODE1 !!", days="30")))
            self.assertIn("1", done)
            self.assertEqual(failed, "")
            self.assertEqual(run(adminpages.subscriptions_act(
                Form(action="code_drop", code="ABCDE-1")))[1], "")
            self.assertTrue(run(adminpages.subscriptions_act(
                Form(action="code_drop", code="nope")))[1])


class AccessPageTests(unittest.TestCase):
    def setUp(self) -> None:
        client = SimpleNamespace(kind="3xui", link_kind="subscription")
        self.slots = [SimpleNamespace(key="1", title="NL", client=client)]
        self.record = {"state": "active", "panels": {"1": {"name": "radar_42"}}}
        self.calls: list[tuple] = []

        async def pending():
            return ["7"]

        async def records():
            return {"42": self.record}

        async def record(uid):
            return self.record if str(uid) == "42" else None

        async def statuses(uid):
            return {"1": Account("radar_42", True, 1900000000, 10 ** 10, 1000, "https://s/x")}

        async def issue(uid, keys, by, role, **kw):
            self.calls.append(("issue", uid, keys))
            return {k: Account("n", True) for k in keys}

        async def extend(uid, key, days, role):
            self.calls.append(("extend", uid, key, days))

        async def recent(limit=20):
            return [{"id": "o1", "uid": "42", "status": "new", "created": 1790000000,
                     "plan": {"days": 30, "traffic_gb": 0, "devices": 3},
                     "amount": 199.0, "currency": "RUB"},
                    {"id": "o2", "uid": "42", "status": "failed", "created": 1790000100,
                     "plan": {"days": 90}, "amount": 499.0, "currency": "RUB"}]

        patches = [
            mock.patch.object(storage, "get_user", lambda uid: {"username": "ivan"}),
            mock.patch.object(vpn, "slots", lambda: self.slots),
            mock.patch.object(vpn, "pending", pending),
            mock.patch.object(vpn, "records", records),
            mock.patch.object(vpn, "record", record),
            mock.patch.object(vpn, "statuses", statuses),
            mock.patch.object(vpn, "issue", issue),
            mock.patch.object(vpn, "extend", extend),
            mock.patch.object(vpnsales, "recent", recent),
            mock.patch.object(adminpages.features, "enabled", lambda name: True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_page_shows_requests_issued_person_card_and_orders(self) -> None:
        page = run(adminpages.access_body("CSRF", uid="42"))
        self.assertIn("@ivan", page)
        self.assertIn('name="action" value="issue"', page)
        self.assertIn('name="action" value="deny"', page)
        self.assertIn("продлить", page)
        self.assertIn("отозвать", page)
        self.assertIn("подтвердить оплату", page)   # заказ ждёт оплаты
        self.assertIn("повторить выдачу", page)     # заказ не выдан
        self.assertNotIn("https://s/x", page, "ссылка подписки на странице не нужна")

    def test_actions_are_dispatched_with_validation(self) -> None:
        done, failed = run(adminpages.access_act(
            Form(action="issue", uid="42", slot=["1"]), "1", "superadmin"))
        self.assertEqual((done, failed), ("Выдано на панелях: 1.", ""))
        self.assertEqual(self.calls[-1], ("issue", "42", ["1"]))
        for form in (Form(action="issue", uid="", slot=["1"]),
                     Form(action="issue", uid="42"),
                     Form(action="extend", uid="42", slot="1", days="0"),
                     Form(action="extend", uid="42", slot="1", days="9999"),
                     Form(action="wat")):
            self.assertTrue(run(adminpages.access_act(form, "1", "superadmin"))[1], form)
        done, _ = run(adminpages.access_act(
            Form(action="extend", uid="42", slot="1", days="30"), "1", "superadmin"))
        self.assertEqual(self.calls[-1], ("extend", "42", "1", 30))


class PanelsPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = {"VPN1_KIND": "3xui", "VPN1_TITLE": "NL", "VPN1_URL": "https://p.example:2053/x",
                    "VPN1_TOKEN": "SECRET-TOKEN-VALUE"}

        async def records():
            return {"42": {"panels": {"1": {}}}, "43": {"panels": {"1": {}}}}

        for patch in (mock.patch.object(vpn, "_setting", lambda key: self.env.get(key, "")),
                      mock.patch.object(vpn, "records", records)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_list_form_and_no_secret_leak(self) -> None:
        page = run(adminpages.panels_body("CSRF"))
        self.assertIn("NL", page)
        self.assertIn("p.example:2053", page)
        self.assertIn("Доступов выдано на этой панели: 2", page)
        self.assertIn("Добавить панель (слот 2)", page)
        self.assertNotIn("SECRET-TOKEN-VALUE", page)
        self.assertIn('action="/vpn/panels/save"', page)

    def test_edit_form_keeps_secret_out_of_the_page(self) -> None:
        page = run(adminpages.panels_body("CSRF", edit=1))
        self.assertIn("Изменить панель (слот 1)", page)
        self.assertIn("оставьте пустым", page)
        self.assertNotIn("SECRET-TOKEN-VALUE", page)
        self.assertIn('value="https://p.example:2053/x"', page)

    def test_all_kinds_are_offered(self) -> None:
        page = run(adminpages.panels_body("CSRF"))
        for title in ("3x-ui", "Marzban", "PasarGuard", "Remnawave", "Hiddify", "Outline", "wg-easy"):
            self.assertIn(title, page)


class NavigationTests(unittest.TestCase):
    def test_owner_gets_vpn_section_and_subscription_page(self) -> None:
        groups = {key: items for _, _, key, items in panel._nav_groups("superadmin")}
        self.assertEqual([i[0] for i in groups["vpn"]], ["/vpn", "/vpn/panels", "/vpn/access"])
        self.assertIn("/subscriptions", [i[0] for i in groups["users"]])

    def test_others_do_not(self) -> None:
        for role in ("admin", "moderator"):
            flat = [item[0] for item in panel._links_for(role)]
            self.assertFalse(any(h.startswith(("/vpn", "/subscriptions")) for h in flat), role)

    def test_handlers_are_owner_only(self) -> None:
        source = open(os.path.join(ROOT, "radar", "web", "panel.py"), encoding="utf-8").read()
        for handler in ("vpn_panels_page", "vpn_access_page", "subscriptions_page"):
            index = source.index(f"async def {handler}")
            self.assertIn("@owner_only", source[index - 40:index], handler)
        for handler in ("vpn_panels_save", "vpn_panels_remove", "vpn_panels_check",
                        "vpn_access_act", "subscriptions_act"):
            index = source.index(f"async def {handler}")
            body = source[index:index + 400]
            self.assertIn('_guarded_form(request, "superadmin")', body, handler)


if __name__ == "__main__":
    unittest.main()
