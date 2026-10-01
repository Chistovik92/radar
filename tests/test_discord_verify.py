#!/usr/bin/env python3
"""Проверка участников Discord (с 5.9.5).

Закреплено то, что ломается тихо: вопрос влезает в подпись окна Discord,
попытки не сбрасываются подбором, связанный аккаунт проходит без вопроса,
исключение — только при включённой возможности, а нехватка привилегированного
намерения не останавливает бота.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import random
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import discordverify as dv, features, secrets  # noqa: E402
from radar.platforms import discord, discordbot  # noqa: E402
from radar.platforms.base import EventKind  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def snowflake(created_at: float) -> int:
    return (int(created_at * 1000) - dv.DISCORD_EPOCH_MS) << 22


class Pure(unittest.TestCase):
    def test_account_age_from_id(self):
        now = time.time()
        young = snowflake(now - 2 * 86400)
        old = snowflake(now - 400 * 86400)
        self.assertAlmostEqual(dv.account_age_days(young, now), 2, delta=0.01)
        self.assertGreater(dv.account_age_days(old, now), 399)

    def test_questions_fit_modal_label_and_have_answers(self):
        rng = random.Random(1)
        kinds = set()
        for _ in range(300):
            question, answer = dv.make_question(rng)
            self.assertLessEqual(len(question), 45, question)   # предел подписи Discord
            self.assertTrue(answer)
            kinds.add(question.split()[0])
        self.assertGreater(len(kinds), 1)

    def test_question_answers_are_correct(self):
        rng = random.Random(2)
        for _ in range(200):
            question, answer = dv.make_question(rng)
            if "+" in question:
                a, b = (int(x) for x in question.replace("?", "").split()[2::2])
                self.assertEqual(int(answer), a + b)
            elif "−" in question:
                parts = question.replace("?", "").split()
                self.assertEqual(int(answer), int(parts[2]) - int(parts[4]))
            elif "наоборот" in question:
                word = question.split("«")[1].split("»")[0]
                self.assertEqual(answer, word[::-1])
            else:
                word = question.split("«")[1].split("»")[0]
                self.assertEqual(int(answer), len(word))

    def test_suspicious_names(self):
        self.assertTrue(dv.suspicious_name("free nitro here"))
        self.assertTrue(dv.suspicious_name("x", "join discord.gg/abc"))
        self.assertTrue(dv.suspicious_name("t.me/spam"))
        self.assertFalse(dv.suspicious_name("Иван", "Ivan"))

    def test_evaluate(self):
        now = time.time()
        young = snowflake(now - 86400)
        self.assertEqual(dv.evaluate(young, "a", "", min_days=3, now=now).action, "kick")
        self.assertEqual(dv.evaluate(young, "a", "", min_days=0, now=now).action, "allow")
        self.assertEqual(dv.evaluate(snowflake(now - 99 * 86400), "a", "",
                                     min_days=3, now=now).action, "allow")
        self.assertEqual(dv.evaluate(snowflake(now - 99 * 86400), "discord.gg/x", "",
                                     now=now).action, "kick")


class GateTests(unittest.TestCase):
    def make(self):
        self.t = 1000.0
        return dv.Gate(clock=lambda: self.t, rng=random.Random(3))

    def solve(self, gate, g="1", u="2"):
        gate.ask(g, u)
        return gate.pending[(g, u)].answer

    def test_correct_answer_passes_and_clears(self):
        gate = self.make()
        gate.joined("1", "2")
        self.assertEqual(gate.check("1", "2", self.solve(gate)), dv.OK)
        self.assertNotIn(("1", "2"), gate.pending)

    def test_answer_is_normalised(self):
        gate = self.make()
        answer = self.solve(gate)
        self.assertEqual(gate.check("1", "2", f"  {answer.upper()} "), dv.OK)

    def test_no_question_no_pass(self):
        gate = self.make()
        self.assertEqual(gate.check("1", "2", "5"), dv.NONE)
        gate.joined("1", "2")
        self.assertEqual(gate.check("1", "2", "5"), dv.NONE)

    def test_wrong_answers_lock_after_limit_and_do_not_reset(self):
        gate = self.make()
        results = []
        for _ in range(dv.MAX_ATTEMPTS):
            self.solve(gate)
            results.append(gate.check("1", "2", "zzz"))
        self.assertEqual(results[:-1], [dv.WRONG] * (dv.MAX_ATTEMPTS - 1))
        self.assertEqual(results[-1], dv.LOCKED)
        # Новый вопрос попытки не возвращает.
        self.solve(gate)
        self.assertEqual(gate.check("1", "2", gate.pending[("1", "2")].answer), dv.LOCKED)

    def test_wrong_answer_burns_the_question(self):
        # Нельзя подбирать ответ на тот же вопрос.
        gate = self.make()
        answer = self.solve(gate)
        self.assertEqual(gate.check("1", "2", "zzz"), dv.WRONG)
        self.assertEqual(gate.check("1", "2", answer), dv.NONE)

    def test_question_expires(self):
        gate = self.make()
        answer = self.solve(gate)
        self.t += dv.QUESTION_TTL + 1
        self.assertEqual(gate.check("1", "2", answer), dv.EXPIRED)

    def test_overdue(self):
        gate = self.make()
        gate.joined("1", "old")
        self.t += 11 * 60
        gate.joined("1", "new")
        self.assertEqual(gate.overdue(10), [("1", "old")])
        self.assertEqual(gate.overdue(0), [])          # 0 — тайм-аута нет

    def test_rejoin_does_not_reset_clock(self):
        gate = self.make()
        gate.joined("1", "2")
        self.t += 600
        gate.joined("1", "2")
        self.assertEqual(gate.pending[("1", "2")].joined, 1000.0)


class FakeTransport:
    def __init__(self, add_ok=True, kick_ok=True):
        self.add_ok, self.kick_ok = add_ok, kick_ok
        self.roles, self.kicks, self.responses, self.modals, self.sent = [], [], [], [], []

    async def add_role(self, guild, user, role):
        self.roles.append((guild, user, role))
        return self.add_ok

    async def kick(self, guild, user):
        self.kicks.append((guild, user))
        return self.kick_ok

    async def respond(self, event, message, *, update=False, ephemeral=False):
        self.responses.append((message, ephemeral))
        return True

    async def respond_modal(self, event, custom_id, title, label, **kw):
        self.modals.append((custom_id, label))
        return True

    async def send(self, chat_id, message):
        self.sent.append((chat_id, message))
        return True


def event(kind, *, payload="", command="", text="", roles=(), perms=0, user="42"):
    from radar.identity import make
    from radar.platforms.base import InboundEvent

    return InboundEvent(
        platform="discord", identity=make("discord", user), chat_id="900", kind=kind,
        command=command, payload=payload, text=text,
        raw={"guild_id": "1", "id": "i", "token": "t",
             "member": {"roles": list(roles), "permissions": str(perms),
                        "user": {"id": user}}})


class Flow(unittest.TestCase):
    ROLE = "777"

    def setUp(self):
        self.gate_was = discordbot.GATE
        discordbot.GATE = dv.Gate(rng=random.Random(5))
        self.flag_was = features.enabled("discord_verify")
        features.set_local("discord_verify", True)
        self.values = {"DISCORD_VERIFY_ROLE_ID": self.ROLE, "DISCORD_MIN_ACCOUNT_DAYS": "3",
                       "DISCORD_VERIFY_MINUTES": "10", "DISCORD_LOG_CHANNEL_ID": ""}
        self.patch = mock.patch.object(secrets, "get", lambda k: self.values.get(k, ""))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        features.set_local("discord_verify", self.flag_was)
        discordbot.GATE = self.gate_was

    def owner(self, value):
        from radar import links

        async def fake(platform, external_id):
            return value

        return mock.patch.object(links, "owner_of", fake)

    def click(self, transport, **kw):
        run(discordbot.verification(event(EventKind.CALLBACK, payload="dv:start", **kw),
                                    transport))

    def answer(self, transport, text, **kw):
        run(discordbot.verification(
            event(EventKind.CALLBACK, payload="dv:answer", text=text, **kw), transport))

    def test_button_opens_modal_with_question(self):
        t = FakeTransport()
        with self.owner(""):
            self.click(t)
        self.assertEqual(len(t.modals), 1)
        self.assertEqual(t.modals[0][0], "dv:answer")
        self.assertEqual(t.roles, [])

    def test_correct_answer_grants_role(self):
        t = FakeTransport()
        with self.owner(""):
            self.click(t)
        correct = discordbot.GATE.pending[("1", "42")].answer
        self.answer(t, correct)
        self.assertEqual(t.roles, [("1", "42", self.ROLE)])
        self.assertTrue(t.responses[-1][1])                     # ответ виден только ему

    def test_wrong_answer_offers_retry_without_kick(self):
        t = FakeTransport()
        with self.owner(""):
            self.click(t)
        self.answer(t, "zzz")
        self.assertEqual(t.roles, [])
        self.assertEqual(t.kicks, [])
        self.assertIn("Осталось попыток: 2", t.responses[-1][0].text)
        self.assertTrue(t.responses[-1][0].keyboard)

    def test_three_failures_kick(self):
        t = FakeTransport()
        for _ in range(dv.MAX_ATTEMPTS):
            with self.owner(""):
                self.click(t)
            self.answer(t, "zzz")
        self.assertEqual(t.kicks, [("1", "42")])

    def test_linked_account_skips_the_question(self):
        t = FakeTransport()
        with self.owner("123456"):
            self.click(t)
        self.assertEqual(t.modals, [])
        self.assertEqual(t.roles, [("1", "42", self.ROLE)])

    def test_already_verified(self):
        t = FakeTransport()
        with self.owner(""):
            self.click(t, roles=[self.ROLE])
        self.assertEqual(t.roles, [])
        self.assertEqual(t.modals, [])
        self.assertIn("уже", t.responses[-1][0].text)

    def test_role_failure_is_reported_not_silent(self):
        t = FakeTransport(add_ok=False)
        with self.owner(""):
            self.click(t)
        self.answer(t, discordbot.GATE.pending[("1", "42")].answer)
        self.assertIn("не удалось", t.responses[-1][0].text)

    def test_disabled_flag_does_nothing(self):
        features.set_local("discord_verify", False)
        t = FakeTransport()
        with self.owner(""):
            self.click(t)
        self.assertEqual(t.modals, [])
        self.assertIn("выключена", t.responses[-1][0].text)

    def test_setup_command_is_for_managers_only(self):
        t = FakeTransport()
        run(discordbot.verification(
            event(EventKind.COMMAND, command="verifysetup", perms=0), t))
        self.assertIn("только для управляющих", t.responses[-1][0].text)
        t2 = FakeTransport()
        run(discordbot.verification(
            event(EventKind.COMMAND, command="verifysetup", perms=0x20), t2))
        self.assertTrue(t2.responses[-1][0].keyboard)

    def test_join_kicks_young_account_and_queues_others(self):
        t = FakeTransport()
        now = time.time()
        young = {"guild_id": "1", "user": {"id": str(snowflake(now - 86400)), "username": "a"}}
        old = {"guild_id": "1", "user": {"id": str(snowflake(now - 90 * 86400)), "username": "b"}}
        bot = {"guild_id": "1", "user": {"id": "5", "bot": True}}
        for data in (young, old, bot):
            run(discordbot.on_member_add(data, t))
        self.assertEqual(t.kicks, [("1", young["user"]["id"])])
        self.assertIn(("1", old["user"]["id"]), discordbot.GATE.pending)
        self.assertNotIn(("1", "5"), discordbot.GATE.pending)

    def test_join_ignored_when_disabled(self):
        features.set_local("discord_verify", False)
        t = FakeTransport()
        run(discordbot.on_member_add({"guild_id": "1", "user": {"id": "9", "username": "x"}}, t))
        self.assertEqual(t.kicks, [])
        self.assertEqual(discordbot.GATE.pending, {})

    def test_no_role_means_disabled(self):
        self.values["DISCORD_VERIFY_ROLE_ID"] = ""
        self.assertFalse(discordbot.verify_enabled())


class Transport(unittest.TestCase):
    def test_modal_submit_is_parsed(self):
        data = {"type": 5, "id": "1", "token": "t", "channel_id": "9",
                "member": {"user": {"id": "42", "username": "u"}},
                "data": {"custom_id": "dv:answer", "components": [
                    {"type": 1, "components": [{"type": 4, "custom_id": "answer",
                                                "value": " 12 "}]}]}}
        parsed = discord.parse_interaction(data)
        self.assertEqual(parsed.kind, EventKind.CALLBACK)
        self.assertEqual(parsed.payload, "dv:answer")
        self.assertEqual(parsed.text, "12")

    def test_members_intent_only_when_asked(self):
        plain = discord.DiscordTransport("t")
        wanted = discord.DiscordTransport("t", member_events=True)
        self.assertEqual(plain.identify()["d"]["intents"], discord.INTENTS)
        self.assertTrue(wanted.identify()["d"]["intents"] & discord.INTENT_MEMBERS)

    def test_denied_intent_rolls_back_instead_of_stopping(self):
        transport = discord.DiscordTransport("t", member_events=True)
        calls = []

        async def once():
            calls.append(transport.intents)
            if len(calls) == 1:
                raise discord.GatewayClosed(4014, resume=False)
            transport._stopping = True

        transport._run_once = once

        async def go():
            with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
                await transport.start()

        run(go())
        self.assertTrue(calls[0] & discord.INTENT_MEMBERS)
        self.assertFalse(calls[1] & discord.INTENT_MEMBERS)       # откатились
        self.assertTrue(transport.members_denied)

    def test_denied_intent_without_members_is_still_fatal(self):
        transport = discord.DiscordTransport("t")
        calls = []

        async def once():
            calls.append(1)
            raise discord.GatewayClosed(4014, resume=False)

        transport._run_once = once
        run(transport.start())
        self.assertEqual(len(calls), 1)                          # остановился

    def test_member_add_is_dispatched(self):
        transport = discord.DiscordTransport("t", member_events=True)
        seen = []

        async def handler(data):
            seen.append(data["user"]["id"])

        transport.member_handler = handler
        run(transport._dispatch("GUILD_MEMBER_ADD", {"user": {"id": "7"}}))
        self.assertEqual(seen, ["7"])

    def test_restricted_commands_are_manager_only(self):
        transport = discord.DiscordTransport("t")
        transport.application_id = "app"
        sent = {}

        async def request(method, path, body=None, **kw):
            sent["body"] = body
            return {}

        transport.request = request
        run(transport.set_commands(discordbot.COMMANDS, restricted=discordbot.RESTRICTED))
        by_name = {item["name"]: item for item in sent["body"]}
        self.assertEqual(by_name["verifysetup"]["default_member_permissions"], "32")
        self.assertNotIn("default_member_permissions", by_name["about"])

    def test_defaults(self):
        flag = features.resolve("discord_verify")
        self.assertIsNotNone(flag)
        self.assertFalse(flag.default)


if __name__ == "__main__":
    unittest.main(verbosity=2)
