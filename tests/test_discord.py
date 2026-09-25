#!/usr/bin/env python3
"""Discord (5.5): разметка, пределы, Gateway и сводка — без сети.

Протокол сверен с исходниками discord.py (discord/gateway.py, http.py),
транспорт по настоящему WebSocket проверяет `tools/discord_http_check.py`.
С живым Discord не проверялось.
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
from datetime import datetime
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import features, identity  # noqa: E402
from radar.platforms import discord, discordbot  # noqa: E402
from radar.platforms.base import Button, EventKind, OutboundMessage  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class RenderTests(unittest.TestCase):
    def test_html_to_markdown(self):
        self.assertEqual(
            discord.render('<b>Жирно</b> <i>курсив</i> <code>x</code> '
                           '<a href="https://e.x">ссылка</a> &amp; <span>т</span>'),
            "**Жирно** *курсив* `x` [ссылка](https://e.x) & т")

    def test_split_by_lines(self):
        text = "\n".join("строка %03d" % n for n in range(400))
        parts = discord.split_text(text)
        self.assertTrue(all(len(part) <= discord.TEXT_LIMIT for part in parts))
        self.assertEqual("\n".join(parts), text)

    def test_short_text_single_part(self):
        self.assertEqual(discord.split_text("а"), ["а"])


class ComponentTests(unittest.TestCase):
    def test_buttons_wrap_not_dropped(self):
        row = [Button(text=f"b{n}", payload=f"p{n}") for n in range(12)]
        groups = discord.components([row])
        rows = [r for group in groups for r in group]
        self.assertEqual([len(r["components"]) for r in rows], [5, 5, 2])
        self.assertEqual(sum(len(r["components"]) for r in rows), 12)

    def test_more_than_five_rows_go_to_next_message(self):
        keyboard = [[Button(text=str(n), payload=str(n))] for n in range(7)]
        groups = discord.components(keyboard)
        self.assertEqual([len(group) for group in groups], [5, 2])

    def test_link_and_callback_styles(self):
        rows = discord.components([[Button(text="сайт", url="https://x"),
                                    Button(text="ок", payload="ok")]])[0]
        link, press = rows[0]["components"]
        self.assertEqual((link["style"], link["url"]), (5, "https://x"))
        self.assertEqual((press["style"], press["custom_id"]), (2, "ok"))

    def test_payloads_attach_buttons_to_last_part(self):
        long_text = "x\n" * 1500
        message = OutboundMessage(text=long_text, keyboard=[[Button(text="a", payload="a")]])
        bodies = discord.payloads(message)
        self.assertGreater(len(bodies), 1)
        self.assertNotIn("components", bodies[0])
        self.assertIn("components", bodies[-1])
        self.assertTrue(all(body["allowed_mentions"] == {"parse": []} for body in bodies))

    def test_silent_empty_message_is_not_sent(self):
        self.assertEqual(discord.payloads(OutboundMessage(text="", silent=True)), [])


class InteractionTests(unittest.TestCase):
    def test_slash_command_in_guild(self):
        event = discord.parse_interaction({
            "id": "1", "token": "t", "type": 2, "channel_id": "55",
            "member": {"user": {"id": "42", "username": "vasya"}},
            "data": {"name": "status"},
        })
        self.assertEqual((event.kind, event.command, event.chat_id), (EventKind.COMMAND, "status", "55"))
        self.assertEqual(event.key, "discord:42")
        self.assertEqual(identity.parse("discord:42").platform, "discord")

    def test_button_in_dm(self):
        event = discord.parse_interaction({
            "type": 3, "channel_id": "9", "user": {"id": "7"}, "data": {"custom_id": "x:y"}})
        self.assertEqual((event.kind, event.payload), (EventKind.CALLBACK, "x:y"))

    def test_unknown_or_anonymous(self):
        self.assertIsNone(discord.parse_interaction({"type": 1, "user": {"id": "1"}}))
        self.assertIsNone(discord.parse_interaction({"type": 2, "data": {"name": "x"}}))


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000):
        self.closed = True


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.seen = []

        async def handler(event, transport):
            self.seen.append(event)

        self.transport = discord.DiscordTransport("tok", handler)

    def _hello(self, ws):
        async def go():
            with mock.patch.object(self.transport, "_heartbeat", self._no_beat):
                await self.transport.handle(ws, {"op": 10, "d": {"heartbeat_interval": 41250}})
                await asyncio.sleep(0)
        run(go())

    async def _no_beat(self, ws, interval):
        return None

    def test_hello_identifies_with_minimal_intents(self):
        ws = FakeWS()
        self._hello(ws)
        identify = ws.sent[-1]
        self.assertEqual(identify["op"], discord.IDENTIFY)
        self.assertEqual(identify["d"]["token"], "tok")
        self.assertEqual(identify["d"]["intents"], 1)

    def test_ready_then_resume_after_reconnect(self):
        ws = FakeWS()
        run(self.transport.handle(ws, {"op": 0, "t": "READY", "s": 1, "d": {
            "session_id": "S", "resume_gateway_url": "wss://resume.example",
            "application": {"id": "A"}}}))
        self.assertEqual((self.transport.session_id, self.transport.application_id,
                          self.transport.sequence), ("S", "A", 1))
        with self.assertRaises(discord.GatewayClosed) as caught:
            run(self.transport.handle(ws, {"op": 7, "d": None}))
        self.assertTrue(caught.exception.resume)
        ws2 = FakeWS()
        self._hello(ws2)
        self.assertEqual(ws2.sent[-1], {"op": 6, "d": {"token": "tok", "session_id": "S", "seq": 1}})

    def test_invalid_session_not_resumable_forgets_session(self):
        self.transport.session_id, self.transport.sequence = "S", 5
        with mock.patch.object(discord.asyncio, "sleep", mock.AsyncMock()):
            with self.assertRaises(discord.GatewayClosed) as caught:
                run(self.transport.handle(FakeWS(), {"op": 9, "d": False}))
        self.assertFalse(caught.exception.resume)
        self.assertEqual((self.transport.session_id, self.transport.sequence), ("", None))

    def test_server_heartbeat_request_and_ack(self):
        ws = FakeWS()
        self.transport.sequence = 3
        self.transport._acked = False
        run(self.transport.handle(ws, {"op": 1, "d": None}))
        self.assertEqual(ws.sent[-1], {"op": 1, "d": 3})
        run(self.transport.handle(ws, {"op": 11}))
        self.assertTrue(self.transport._acked)

    def test_interaction_reaches_handler(self):
        run(self.transport.handle(FakeWS(), {"op": 0, "t": "INTERACTION_CREATE", "s": 2, "d": {
            "type": 2, "id": "1", "token": "t", "channel_id": "5",
            "user": {"id": "9"}, "data": {"name": "help"}}}))
        self.assertEqual(self.seen[0].command, "help")
        self.assertEqual(self.transport.sequence, 2)

    def test_fatal_close_codes(self):
        for code in (4004, 4014):
            self.assertIn(code, discord.FATAL_CLOSE)
        self.assertNotIn(4000, discord.FATAL_CLOSE)


class ResponderTests(unittest.TestCase):
    def test_answers(self):
        def ask(command):
            event = discord.parse_interaction({"type": 2, "user": {"id": "1"},
                                               "data": {"name": command}})
            return discordbot.answer_for(event, status="✅ ok", username="radar_bot")

        self.assertIn("Discord", ask("about").text)
        self.assertEqual(ask("about").keyboard[0][0].url, "https://t.me/radar_bot")
        self.assertIn("✅ ok", ask("status").text)
        self.assertIn("/summary", ask("unknown").text)

    def test_every_public_text_has_disclaimer(self):
        phrase = "не заменяет официальные каналы оповещения"
        self.assertIn(phrase, discordbot.ABOUT)
        self.assertIn(phrase, discordbot.summary_text({}, datetime(2026, 9, 1, 20, 0)))
        event = discord.parse_interaction({"type": 2, "user": {"id": "1"}, "data": {"name": "status"}})
        self.assertIn(phrase, discordbot.answer_for(event, status="x").text)

    def test_summary_counts_only_categories(self):
        text = discordbot.summary_text(
            {"_total": 5, "_all_clear": 2, "bpla": 3, "jkh": 1}, datetime(2026, 9, 1, 20, 0))
        self.assertIn("Разобрано событий: <b>5</b>", text)
        self.assertIn("Отбоев: 2", text)
        self.assertIn("не тревога", text)

    def test_status_text(self):
        self.assertIn("работает", discordbot.status_text(True, 0))
        self.assertIn("10 мин", discordbot.status_text(False, 600))

    def test_due(self):
        now = datetime(2026, 9, 1, 20, 5)
        self.assertTrue(discordbot.due(now, "20:00", "2026-08-31"))
        self.assertFalse(discordbot.due(now, "20:00", "2026-09-01"))
        self.assertFalse(discordbot.due(datetime(2026, 9, 1, 19, 59), "20:00", ""))
        self.assertTrue(discordbot.due(now, "мусор", ""))

    def test_flag_off_by_default(self):
        self.assertFalse(features.BY_KEY["platform_discord"].default)


class BoundaryTests(unittest.TestCase):
    def test_no_new_dependency(self):
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as handle:
            self.assertNotIn("discord", handle.read().lower())

    def test_no_alert_delivery_to_discord(self):
        """Discord — канал сводок: монитор оповещений о нём не знает."""
        with open(os.path.join(ROOT, "radar", "monitor.py"), encoding="utf-8") as handle:
            self.assertNotIn("discord", handle.read().lower())

    def test_no_message_content_intent(self):
        self.assertEqual(discord.INTENTS & (1 << 15), 0)


if __name__ == "__main__":
    unittest.main()
