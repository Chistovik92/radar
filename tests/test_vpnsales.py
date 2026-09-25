#!/usr/bin/env python3
"""Продажа VPN по тарифам и платёжный слой (5.0.2): без сети.

Деньги — место, где ошибка стоит дороже всего, поэтому здесь в первую
очередь закреплено то, что нельзя сломать молча: двойное нажатие
«Я оплатил» не выдаёт доступ дважды, подделанная кнопка не меняет цену,
ручную оплату подтверждает только суперадминистратор, продление
прибавляет дни к оставшимся и возвращает тот же ключ.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import hashlib
import hmac
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

from radar import features, payments, vpn, vpnpanels, vpnsales  # noqa: E402
from radar.vpnpanels import Account, PanelError  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_vpn import FakePanel  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class PlanTests(unittest.TestCase):
    def test_parse(self):
        plans = vpnsales.parse_plans("30:0:3:199; 90:100:5:499,50 ;мусор; 0:0:0:10; 7:0:0:0")
        self.assertEqual([(p.days, p.traffic_gb, p.devices, p.price) for p in plans],
                         [(30, 0, 3, 199.0), (90, 100, 5, 499.5)])

    def test_title(self):
        self.assertEqual(vpnsales.Plan(30, 0, 3, 199).title("RUB"),
                         "30 дн., без предела трафика, до 3 устр. — 199 RUB")
        self.assertEqual(vpnsales.Plan(7, 10, 0, 49.5).title("USD"),
                         "7 дн., 10 ГБ — 49.5 USD")


class CryptoPayTests(unittest.TestCase):
    def test_response_parsing(self):
        self.assertEqual(payments.parse_response('{"ok": true, "result": {"a": 1}}'), {"a": 1})
        with self.assertRaises(payments.PaymentError) as caught:
            payments.parse_response('{"ok": false, "error": {"code": 401, "name": "UNAUTHORIZED"}}')
        self.assertIn("UNAUTHORIZED", str(caught.exception))
        with self.assertRaises(payments.PaymentError):
            payments.parse_response("<html>")

    def test_invoice_link_fields(self):
        invoice = payments.invoice_from({"invoice_id": 42, "bot_invoice_url": "https://t.me/CryptoBot?start=IV",
                                         "amount": "199", "status": "active"}, "RUB")
        self.assertEqual((invoice.id, invoice.url, invoice.amount), ("42", "https://t.me/CryptoBot?start=IV", 199.0))
        with self.assertRaises(payments.PaymentError):
            payments.invoice_from({}, "RUB")

    def test_create_invoice_params(self):
        provider = payments.CryptoPayProvider("tok", assets="usdt, ton")
        seen = {}

        async def fake(method, params):
            seen.update(method=method, **params)
            return {"invoice_id": 1, "bot_invoice_url": "https://x", "amount": params["amount"]}

        with mock.patch.object(provider, "_call", fake):
            run(provider.create_invoice(199, "rub", "VPN", "vpn:abc"))
        self.assertEqual(seen["method"], "createInvoice")
        self.assertEqual((seen["currency_type"], seen["fiat"], seen["amount"]), ("fiat", "RUB", "199.00"))
        self.assertEqual(seen["accepted_assets"], "USDT,TON")

    def test_status_lookup(self):
        provider = payments.CryptoPayProvider("tok")

        async def fake(method, params):
            return {"items": [{"invoice_id": 7, "status": "paid"}]}

        with mock.patch.object(provider, "_call", fake):
            self.assertEqual(run(provider.status("7")), "paid")

    def test_cancel_deletes_invoice(self):
        provider = payments.CryptoPayProvider("tok")
        seen = {}

        async def fake(method, params):
            seen.update(method=method, **params)
            return True

        with mock.patch.object(provider, "_call", fake):
            self.assertTrue(run(provider.cancel("7")))
        self.assertEqual((seen["method"], seen["invoice_id"]), ("deleteInvoice", "7"))

        async def refuse(method, params):
            raise payments.PaymentError("Crypto Pay отказал: INVOICE_NOT_FOUND.")

        with mock.patch.object(provider, "_call", refuse):
            self.assertFalse(run(provider.cancel("7")))

    def test_timeout_is_payment_error(self):
        """Общий предел времени aiohttp — asyncio.TimeoutError, не ClientError."""
        provider = payments.CryptoPayProvider("tok")

        class Hanging:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                raise asyncio.TimeoutError

            async def __aexit__(self, *exc):
                return False

        import aiohttp

        # Заглушка aiohttp из stubcheck даёт ClientError не-исключение.
        with mock.patch.object(aiohttp, "ClientSession", Hanging), \
                mock.patch.object(aiohttp, "ClientError", type("ClientError", (Exception,), {}),
                                  create=True), \
                mock.patch.object(aiohttp, "ClientTimeout", lambda **kwargs: None, create=True):
            with self.assertRaises(payments.PaymentError):
                run(provider.status("7"))

    def test_webhook_signature(self):
        body = b'{"update_type":"invoice_paid"}'
        key = hashlib.sha256(b"tok").digest()
        good = hmac.new(key, body, hashlib.sha256).hexdigest()
        self.assertTrue(payments.verify_signature("tok", body, good))
        self.assertFalse(payments.verify_signature("tok", body, "0" * 64))
        self.assertFalse(payments.verify_signature("other", body, good))

    def test_provider_choice(self):
        values = {"PAY_PROVIDER": "cryptopay", "PAY_CRYPTOPAY_TOKEN": "t",
                  "PAY_CRYPTOPAY_TESTNET": "1"}
        with mock.patch.object(payments, "_setting", lambda key: values.get(key, "")):
            chosen = payments.provider()
        self.assertIsInstance(chosen, payments.CryptoPayProvider)
        self.assertEqual(chosen.base, payments.TESTNET)
        with mock.patch.object(payments, "_setting", lambda key: ""):
            self.assertIsInstance(payments.provider(), payments.ManualProvider)
        self.assertTrue(payments.CryptoPayProvider("").problems())


class FakeProvider(payments.Provider):
    kind = "fake"
    manual = False

    def __init__(self):
        self.invoices = {}

    async def create_invoice(self, amount, currency, description, payload, expires_in=3600):
        invoice_id = str(len(self.invoices) + 1)
        self.invoices[invoice_id] = payments.ACTIVE
        return payments.Invoice(invoice_id, f"https://pay/{invoice_id}", amount, currency)

    async def status(self, invoice_id):
        await asyncio.sleep(0.01)
        return self.invoices[invoice_id]

    async def cancel(self, invoice_id):
        if self.invoices[invoice_id] != payments.ACTIVE or getattr(self, "stuck", False):
            return False
        self.invoices[invoice_id] = "deleted"
        return True


class SalesBase(unittest.TestCase):
    PLANS = "30:0:3:199;90:50:0:499"

    def setUp(self):
        self.meta = {}
        self.panels = {"1": FakePanel("3xui"), "2": FakePanel("remnawave")}
        self.panels["1"].supports_devices = True
        self.devices = {}

        async def set_devices(name, devices):
            self.devices[name] = devices

        self.panels["1"].set_devices = set_devices
        self.provider = FakeProvider()
        self.values = {"VPN_PLANS": self.PLANS}

        async def meta_get(key, default=None):
            return json.loads(json.dumps(self.meta.get(key, default)))

        async def meta_set(key, value):
            self.meta[key] = json.loads(json.dumps(value))

        from radar import storage

        features.set_local("vpn", True)
        features.set_local("vpn_sales", True)
        self.patches = [
            mock.patch.object(storage, "meta_get", meta_get),
            mock.patch.object(storage, "meta_set", meta_set),
            mock.patch.object(vpn, "slots", lambda: [
                vpn.Slot(int(k), f"P{k}", p) for k, p in sorted(self.panels.items())]),
            mock.patch.object(vpn, "_setting", lambda key: ""),
            mock.patch.object(vpnsales, "_setting", lambda key: self.values.get(key, "")),
            mock.patch.object(payments, "provider", lambda: self.provider),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        features.apply({})

    def pay(self, entry):
        self.provider.invoices[entry["invoice"]] = payments.PAID


class ReadinessTests(SalesBase):
    def test_flag_plans_and_provider_required(self):
        self.assertTrue(vpnsales.ready()[0])
        features.set_local("vpn_sales", False)
        self.assertFalse(vpnsales.ready()[0])
        features.set_local("vpn_sales", True)
        self.values["VPN_PLANS"] = ""
        self.assertIn("Тарифы", vpnsales.ready()[1])

    def test_sales_flag_off_by_default(self):
        self.assertFalse(features.BY_KEY["vpn_sales"].default)

    def test_sale_slots_setting(self):
        self.values["VPN_PLAN_SLOTS"] = "2, 9"
        self.assertEqual(vpnsales.sale_slots(), ["2"])


class OrderTests(SalesBase):
    def test_forged_plan_index_rejected(self):
        for index in (-1, 2, 99):
            with self.assertRaises(vpnsales.SaleError):
                run(vpnsales.create("5", index))

    def test_price_frozen_in_order(self):
        entry = run(vpnsales.create("5", 0))
        self.values["VPN_PLANS"] = "30:0:3:1"
        self.assertEqual(run(vpnsales.order(entry["id"]))["amount"], 199.0)

    def test_unpaid_does_nothing(self):
        entry = run(vpnsales.create("5", 0))
        self.assertEqual(run(vpnsales.check(entry["id"], "5"))["status"], vpnsales.NEW)
        self.assertEqual(self.panels["1"].created, 0)

    def test_paid_issues_on_sale_slots_with_devices(self):
        entry = run(vpnsales.create("5", 0))
        self.pay(entry)
        done = run(vpnsales.check(entry["id"], "5"))
        self.assertEqual(done["status"], vpnsales.DONE)
        self.assertEqual(sorted(done["granted"]), ["1", "2"])
        name = vpnpanels.account_name("5")
        self.assertEqual(self.devices[name], 3)
        self.assertEqual(vpn.issued_slots(run(vpn.record("5"))), ["1", "2"])

    def test_double_check_issues_once(self):
        """Два «Я оплатил» одновременно — один срок, а не два."""
        entry = run(vpnsales.create("5", 0))
        self.pay(entry)

        async def both():
            return await asyncio.gather(vpnsales.check(entry["id"], "5"),
                                        vpnsales.check(entry["id"], "5"))

        run(both())
        name = vpnpanels.account_name("5")
        expire = self.panels["1"].users[name].expire
        self.assertLess(abs(expire - (time.time() + 30 * vpn.DAY)), 5)
        self.assertEqual(self.panels["1"].created, 1)

    def test_renewal_adds_days_and_keeps_key(self):
        first = run(vpnsales.create("5", 0))
        self.pay(first)
        run(vpnsales.check(first["id"], "5"))
        name = vpnpanels.account_name("5")
        link = self.panels["1"].users[name].subscription_url
        before = self.panels["1"].users[name].expire
        second = run(vpnsales.create("5", 0))
        self.pay(second)
        run(vpnsales.check(second["id"], "5"))
        after = self.panels["1"].users[name]
        self.assertEqual(after.subscription_url, link)
        self.assertEqual(after.expire - before, 30 * vpn.DAY)
        self.assertEqual(self.panels["1"].created, 1)

    def test_other_user_cannot_check(self):
        entry = run(vpnsales.create("5", 0))
        with self.assertRaises(vpnsales.SaleError):
            run(vpnsales.check(entry["id"], "6"))

    def test_expired_invoice(self):
        entry = run(vpnsales.create("5", 0))
        self.provider.invoices[entry["invoice"]] = payments.EXPIRED
        self.assertEqual(run(vpnsales.check(entry["id"], "5"))["status"], vpnsales.EXPIRED)

    def test_old_unpaid_order_expires_by_time(self):
        entry = run(vpnsales.create("5", 0))
        self.meta[vpnsales.META_KEY][entry["id"]]["created"] -= vpnsales.ORDER_TTL + 1
        self.assertEqual(run(vpnsales.check(entry["id"], "5"))["status"], vpnsales.EXPIRED)
        self.assertEqual(self.panels["1"].created, 0)

    def test_paid_at_last_minute_still_issued(self):
        """Оплатил в последнюю минуту, «Я оплатил» нажал после конца суток:
        провайдер подтверждает оплату — доступ выдаётся (до 5.6.2 — нет)."""
        entry = run(vpnsales.create("5", 0))
        self.meta[vpnsales.META_KEY][entry["id"]]["created"] -= vpnsales.ORDER_TTL + 1
        self.pay(entry)
        self.assertEqual(run(vpnsales.check(entry["id"], "5"))["status"], vpnsales.DONE)
        self.assertEqual(self.panels["1"].created, 1)

    def test_failure_then_retry_by_superadmin(self):
        for panel in self.panels.values():
            panel.broken = True
        entry = run(vpnsales.create("5", 0))
        self.pay(entry)
        failed = run(vpnsales.check(entry["id"], "5"))
        self.assertEqual(failed["status"], vpnsales.FAILED)
        with self.assertRaises(vpnsales.SaleError):
            run(vpnsales.retry(entry["id"], "admin"))
        for panel in self.panels.values():
            panel.broken = False
        self.assertEqual(run(vpnsales.retry(entry["id"], "superadmin"))["status"], vpnsales.DONE)

    def test_partial_failure_is_done_with_errors(self):
        self.panels["2"].broken = True
        entry = run(vpnsales.create("5", 0))
        self.pay(entry)
        done = run(vpnsales.check(entry["id"], "5"))
        self.assertEqual((done["status"], done["granted"]), (vpnsales.DONE, ["1"]))
        self.assertIn("2", done["errors"])

    def test_cancel(self):
        entry = run(vpnsales.create("5", 0))
        with self.assertRaises(vpnsales.SaleError):
            run(vpnsales.cancel(entry["id"], "6", "user"))
        self.assertEqual(run(vpnsales.cancel(entry["id"], "5", "user"))["status"],
                         vpnsales.CANCELLED)
        self.assertEqual(self.provider.invoices[entry["invoice"]], "deleted",
                         "счёт погашен и у провайдера")
        self.assertEqual(run(vpnsales.check(entry["id"], "5"))["status"], vpnsales.CANCELLED)

    def test_cancel_after_payment_issues_instead(self):
        entry = run(vpnsales.create("5", 0))
        self.pay(entry)
        self.assertEqual(run(vpnsales.cancel(entry["id"], "5", "user"))["status"],
                         vpnsales.DONE)
        self.assertEqual(self.panels["1"].created, 1)

    def test_cancel_refused_when_provider_keeps_invoice(self):
        entry = run(vpnsales.create("5", 0))
        self.provider.stuck = True
        with self.assertRaises(vpnsales.SaleError):
            run(vpnsales.cancel(entry["id"], "5", "user"))
        self.assertEqual(run(vpnsales.order(entry["id"]))["status"], vpnsales.NEW)

    def test_unexpected_grant_crash_marks_failed(self):
        """Непредвиденный сбой выдачи — «не выдано» с повтором, а не вечное
        «оплачен, выдаётся»."""
        entry = run(vpnsales.create("5", 0))
        self.pay(entry)

        async def crash(*args, **kwargs):
            raise KeyError("oops")

        with mock.patch.object(vpn, "grant_paid", crash):
            self.assertEqual(run(vpnsales.check(entry["id"], "5"))["status"], vpnsales.FAILED)
        self.assertEqual(run(vpnsales.retry(entry["id"], "superadmin"))["status"], vpnsales.DONE)

    def test_no_links_or_tokens_in_orders(self):
        entry = run(vpnsales.create("5", 0))
        self.pay(entry)
        run(vpnsales.check(entry["id"], "5"))
        dump = json.dumps(self.meta[vpnsales.META_KEY])
        self.assertNotIn("https://3xui", dump)
        self.assertNotIn("https://remnawave", dump)


class ManualTests(SalesBase):
    def setUp(self):
        super().setUp()
        self.provider = payments.ManualProvider()

    def test_user_cannot_self_confirm(self):
        entry = run(vpnsales.create("5", 0))
        self.assertEqual(entry["url"], "")
        self.assertEqual(run(vpnsales.check(entry["id"], "5"))["status"], vpnsales.NEW)
        for role in ("user", "moderator", "admin"):
            with self.assertRaises(vpnsales.SaleError):
                run(vpnsales.confirm(entry["id"], role, "5"))
        self.assertEqual(self.panels["1"].created, 0)

    def test_superadmin_confirms_once(self):
        entry = run(vpnsales.create("5", 0))
        done = run(vpnsales.confirm(entry["id"], "superadmin", "1"))
        self.assertEqual(done["status"], vpnsales.DONE)
        with self.assertRaises(vpnsales.SaleError):
            run(vpnsales.confirm(entry["id"], "superadmin", "1"))
        self.assertEqual(self.panels["1"].created, 1)


class GrantPaidTests(SalesBase):
    def test_free_issue_still_superadmin_only(self):
        """Путь продаж не открывает бесплатную выдачу."""
        with self.assertRaises(PanelError):
            run(vpn.issue("5", ["1"], "5", "admin"))
        self.assertFalse(hasattr(vpnsales, "issue"))

    def test_traffic_set_on_renewal(self):
        seen = {}

        async def set_traffic(name, traffic):
            seen[name] = traffic

        self.panels["1"].set_traffic = set_traffic
        run(vpn.grant_paid("5", ["1"], "o1", days=30, traffic=0))
        run(vpn.grant_paid("5", ["1"], "o2", days=90, traffic=50 * vpnpanels.GB))
        self.assertEqual(seen[vpnpanels.account_name("5")], 50 * vpnpanels.GB)
        self.assertIsInstance(run(vpn.statuses("5"))["1"], Account)

    def test_renewal_adds_traffic_to_used_and_left(self):
        """Предел в панели — на весь расход: продление прибавляет тариф
        к израсходованному и неистраченному остатку (5.6.2)."""
        import dataclasses

        seen = {}

        async def set_traffic(name, traffic):
            seen["limit"] = traffic

        self.panels["1"].set_traffic = set_traffic
        run(vpn.grant_paid("5", ["1"], "o1", days=30, traffic=50 * vpnpanels.GB))
        name = vpnpanels.account_name("5")
        users = self.panels["1"].users
        users[name] = dataclasses.replace(users[name], traffic_used=45 * vpnpanels.GB)
        run(vpn.grant_paid("5", ["1"], "o2", days=30, traffic=50 * vpnpanels.GB))
        self.assertEqual(seen["limit"], 100 * vpnpanels.GB, "45 потрачено + 5 остаток + 50")
        # Истёкший срок: остаток прошлого периода не переносится.
        users[name] = dataclasses.replace(users[name], expire=int(time.time()) - 10,
                                          traffic_limit=50 * vpnpanels.GB,
                                          traffic_used=10 * vpnpanels.GB)
        run(vpn.grant_paid("5", ["1"], "o3", days=30, traffic=50 * vpnpanels.GB))
        self.assertEqual(seen["limit"], 60 * vpnpanels.GB)


if __name__ == "__main__":
    unittest.main()
