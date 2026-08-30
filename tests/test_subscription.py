#!/usr/bin/env python3
"""Подписка: пробный период, подарочные дни, погашение кодов.

Подписка одна на бота: оплата любой части открывает обе, и продавать
их раздельно нельзя — человек заплатил бы дважды за одно ощущение.
Здесь закреплено то, что ломается тихо и обнаруживается платящим:

* пробный период даётся один раз и не возобновляется;
* подарочные дни прибавляются к концу срока, а не заменяют его —
  иначе подарок поверх оплаченного укорачивал бы оплаченное;
* код одноразовый, и повторный ввод не начисляет дни второй раз.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import redeem, subscription  # noqa: E402


def days_from_now(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class Trial(unittest.TestCase):
    def test_given_once(self) -> None:
        user: dict = {}
        self.assertTrue(subscription.start_trial(user))
        self.assertFalse(subscription.start_trial(user))

    def test_opens_paid_features(self) -> None:
        user: dict = {}
        self.assertFalse(subscription.active(user, "user"))
        subscription.start_trial(user)
        self.assertTrue(subscription.active(user, "user"))

    def test_length_matches_setting(self) -> None:
        user: dict = {}
        subscription.start_trial(user)
        self.assertEqual(subscription.days_left(user), subscription.TRIAL_DAYS)

    def test_recognised_as_trial(self) -> None:
        user: dict = {}
        subscription.start_trial(user)
        self.assertTrue(subscription.on_trial(user))
        self.assertIn("Пробный", subscription.describe(user, "user"))

    def test_used_flag_survives_expiry(self) -> None:
        # Иначе пробный период возобновлялся бы вечно.
        user = {"sub": {"trial_started": days_from_now(-30),
                        "until": days_from_now(-23)}}
        self.assertFalse(subscription.active(user, "user"))
        self.assertTrue(subscription.trial_used(user))
        self.assertFalse(subscription.start_trial(user))

    def test_offer_mentioned_while_unused(self) -> None:
        self.assertIn(str(subscription.TRIAL_DAYS),
                      subscription.describe({}, "user"))


class Grant(unittest.TestCase):
    def test_adds_days(self) -> None:
        user: dict = {}
        subscription.grant(user, 28)
        self.assertEqual(subscription.days_left(user), 28)
        self.assertTrue(subscription.active(user, "user"))

    def test_extends_from_the_end_not_from_today(self) -> None:
        # Подарок поверх оплаченного не должен укорачивать оплаченное.
        user = {"digest": {"paid_until": days_from_now(10)}}
        subscription.grant(user, 28)
        self.assertEqual(subscription.days_left(user), 38)

    def test_expired_subscription_starts_from_today(self) -> None:
        user = {"digest": {"paid_until": days_from_now(-40)}}
        subscription.grant(user, 28)
        self.assertEqual(subscription.days_left(user), 28)

    def test_negative_ignored(self) -> None:
        user: dict = {}
        subscription.grant(user, -5)
        self.assertEqual(subscription.days_left(user), 0)


class Unified(unittest.TestCase):
    """Подписка одна: любая часть открывает обе."""

    def test_digest_payment_opens_media(self) -> None:
        user = {"digest": {"paid_until": days_from_now(30)}}
        self.assertTrue(subscription.active(user, "user"))

    def test_media_payment_opens_digest(self) -> None:
        user = {"media_quota": {"paid_until": days_from_now(30)}}
        self.assertTrue(subscription.active(user, "user"))

    def test_longest_wins(self) -> None:
        user = {"digest": {"paid_until": days_from_now(5)},
                "media_quota": {"paid_until": days_from_now(40)}}
        self.assertEqual(subscription.days_left(user), 40)

    def test_staff_needs_no_payment(self) -> None:
        self.assertTrue(subscription.active({}, "admin"))
        self.assertIn("Служебный", subscription.describe({}, "admin"))


class Codes(unittest.TestCase):
    """Коды, выданные на стороне партнёра."""

    def setUp(self) -> None:
        self.store: list = []

        async def load():
            return list(self.store)

        async def save(items):
            self.store = list(items)

        for name, func in (("load", load), ("save", save)):
            patcher = mock.patch.object(redeem, name, func)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_shape_recognised(self) -> None:
        self.assertTrue(redeem.looks_like_code("HYDRA-2026"))
        self.assertTrue(redeem.looks_like_code("hydra-2026"))

    def test_ordinary_text_not_taken_for_a_code(self) -> None:
        # Иначе бот перехватывал бы у ассистента обычные реплики.
        for text in ("привет", "как дела", "да", "ok", "http://example.ru"):
            with self.subTest(text=text):
                self.assertFalse(redeem.looks_like_code(text))

    def test_added_and_redeemed(self) -> None:
        added, skipped = self.run_async(redeem.add("HYDRA-2026"))
        self.assertEqual(added, ["HYDRA-2026"])
        self.assertEqual(skipped, [])
        days = self.run_async(redeem.redeem("hydra-2026", "telegram:1"))
        self.assertEqual(days, redeem.DEFAULT_DAYS)

    def test_single_use(self) -> None:
        self.run_async(redeem.add("HYDRA-2026"))
        self.assertTrue(self.run_async(redeem.redeem("HYDRA-2026", "telegram:1")))
        self.assertEqual(self.run_async(redeem.redeem("HYDRA-2026", "telegram:1")), 0)

    def test_unknown_code_gives_nothing(self) -> None:
        self.assertEqual(self.run_async(redeem.redeem("HYDRA-0000", "telegram:1")), 0)

    def test_duplicates_not_added_twice(self) -> None:
        self.run_async(redeem.add("HYDRA-2026"))
        added, skipped = self.run_async(redeem.add("HYDRA-2026"))
        self.assertEqual(added, [])
        self.assertEqual(len(skipped), 1)

    def test_several_at_once(self) -> None:
        added, _ = self.run_async(redeem.add("HYDRA-1, HYDRA-2\nHYDRA-3"))
        self.assertEqual(len(added), 3)

    def test_redeemer_recorded(self) -> None:
        # Без этого на вопрос «почему у него подписка» ответить нечем.
        self.run_async(redeem.add("HYDRA-2026"))
        self.run_async(redeem.redeem("HYDRA-2026", "telegram:77"))
        self.assertEqual(self.store[0]["used_by"], "telegram:77")

    def test_dropped_code_stops_working(self) -> None:
        self.run_async(redeem.add("HYDRA-2026"))
        self.assertTrue(self.run_async(redeem.drop("HYDRA-2026")))
        self.assertEqual(self.run_async(redeem.redeem("HYDRA-2026", "telegram:1")), 0)


class DropLimits(unittest.TestCase):
    """Подписи о пределе должны совпадать с самим пределом."""

    def test_five_gigabytes_shown_as_five(self) -> None:
        # На 5000 МБ целочисленное деление давало 4, и в боте стояло
        # «до 4 ГБ» при заявленных пяти. Мегабайты двоичные.
        from radar import filedrop

        self.assertEqual(filedrop.MAX_FILE_MB // 1024, 5)

    def test_budget_holds_more_than_one_file(self) -> None:
        # Иначе первый же файл занимал бы всю раздачу, и следующему
        # человеку места не оставалось.
        from radar import filedrop

        self.assertGreater(filedrop.BUDGET_MB, filedrop.MAX_FILE_MB)


class TopicCount(unittest.TestCase):
    """Число тематик считается, а не вписано словом."""

    def test_no_hardcoded_number_in_texts(self) -> None:
        # «двенадцать» в тексте расходилось с восемнадцатью в списке:
        # человек читал одно, а получал другое.
        source = pathlib.Path("radar/handlers/digest.py").read_text(encoding="utf-8")
        self.assertNotIn("двенадцать", source)


if __name__ == "__main__":
    unittest.main()
