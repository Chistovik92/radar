#!/usr/bin/env python3
"""Привязка аккаунтов, зеркало тревог и адаптер ВКонтакте (5.6): без сети.

Главное, что здесь закреплено: связь подтверждает владелец адресов (код
из Telegram), перебор кода ограничен, копия тревоги уходит только после
доставки в Telegram и никогда не задерживает и не роняет её.
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

from radar import features, identity, links, mirror  # noqa: E402
from radar.platforms import vk, vkbot  # noqa: E402
from radar.platforms.base import EventKind  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class MetaMixin:
    def setUp(self):
        self.meta = {}

        async def meta_get(key, default=None):
            return json.loads(json.dumps(self.meta.get(key, default)))

        async def meta_set(key, value):
            self.meta[key] = json.loads(json.dumps(value))

        from radar import storage

        self.patches = [mock.patch.object(storage, "meta_get", meta_get),
                        mock.patch.object(storage, "meta_set", meta_set)]
        for patch in self.patches:
            patch.start()
        links.reset()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        links.reset()


class CodeTests(MetaMixin, unittest.TestCase):
    def test_extract(self):
        self.assertEqual(links.extract_code(" 012345 "), "012345")
        self.assertEqual(links.extract_code("/link 123456"), "123456")
        for text in ("12345", "1234567", "код 123456", "", "abcdef"):
            self.assertEqual(links.extract_code(text), "", text)

    def test_link_flow(self):
        code = links.new_code("100")
        uid, reason = run(links.redeem("vk", "555", code))
        self.assertEqual((uid, reason), ("100", ""))
        self.assertEqual(run(links.links_of("100")), {"vk": "555"})
        self.assertEqual(run(links.owner_of("vk", "555")), "100")
        # Код одноразовый.
        self.assertEqual(run(links.redeem("vk", "556", code))[0], "")

    def test_code_expires(self):
        code = links.new_code("100", now=1000)
        uid, _ = run(links.redeem("vk", "555", code, now=1000 + links.CODE_TTL + 1))
        self.assertEqual(uid, "")

    def test_new_code_cancels_previous(self):
        first = links.new_code("100")
        links.new_code("100")
        self.assertEqual(run(links.redeem("vk", "555", first))[0], "")

    def test_bruteforce_limited(self):
        code = links.new_code("100")
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(links.MAX_FAILURES):
            run(links.redeem("vk", "666", wrong))
        uid, reason = run(links.redeem("vk", "666", code))
        self.assertEqual(uid, "")
        self.assertIn("Слишком много", reason)
        # Другой аккаунт тем временем не заблокирован.
        self.assertEqual(run(links.redeem("vk", "777", code))[0], "100")

    def test_relink_moves_ownership(self):
        run(links.redeem("vk", "555", links.new_code("100")))
        run(links.redeem("vk", "555", links.new_code("200")))
        self.assertEqual(run(links.links_of("100")), {})
        self.assertEqual(run(links.owner_of("vk", "555")), "200")

    def test_unlink_both_sides(self):
        run(links.redeem("vk", "555", links.new_code("100")))
        run(links.redeem("max", "9", links.new_code("100")))
        self.assertEqual(run(links.unlink("100", "vk")), ["vk"])
        self.assertTrue(run(links.unlink_external("max", "9")))
        self.assertEqual(run(links.links_of("100")), {})

    def test_unknown_platform(self):
        self.assertEqual(run(links.redeem("viber", "1", links.new_code("100")))[0], "")

    def test_handle_text(self):
        code = links.new_code("100")
        self.assertIn("привязан", run(links.handle_text("vk", "5", code)))
        self.assertIn("снята", run(links.handle_text("vk", "5", "/unlink")))
        self.assertEqual(run(links.handle_text("vk", "5", "привет")), "")


class MirrorTests(MetaMixin, unittest.TestCase):
    def tearDown(self):
        mirror.unregister("vk")
        mirror.unregister("max")
        super().tearDown()

    def test_copy_goes_to_linked_platforms_only(self):
        sent = []

        async def to_vk(external, text):
            sent.append(("vk", external, text))
            return True

        async def to_max(external, text):
            sent.append(("max", external, text))
            return True

        mirror.register("vk", to_vk)
        mirror.register("max", to_max)
        run(links.redeem("vk", "555", links.new_code("100")))

        async def go():
            mirror.alert("100", "тревога")
            mirror.alert("200", "чужая")
            await mirror.drain()

        run(go())
        self.assertEqual(sent, [("vk", "555", "тревога")])

    def test_failing_platform_does_not_raise(self):
        async def broken(external, text):
            raise RuntimeError("VK упал")

        mirror.register("vk", broken)
        run(links.redeem("vk", "555", links.new_code("100")))

        async def go():
            mirror.alert("100", "тревога")
            await mirror.drain()

        run(go())   # не падает

    def test_alert_does_not_wait(self):
        """Telegram не ждёт зеркала: alert возвращается сразу."""
        started = asyncio.Event()

        async def slow(external, text):
            started.set()
            await asyncio.sleep(10)
            return True

        mirror.register("vk", slow)
        run(links.redeem("vk", "555", links.new_code("100")))

        async def go():
            loop = asyncio.get_running_loop()
            before = loop.time()
            mirror.alert("100", "тревога")
            self.assertLess(loop.time() - before, 0.05)
            for task in list(mirror._tasks):
                task.cancel()

        run(go())

    def test_monitor_mirrors_only_delivered(self):
        with open(os.path.join(ROOT, "radar", "monitor.py"), encoding="utf-8") as handle:
            source = handle.read()
        position = source.index("mirror.alert(uid, text)")
        before = source[:position]
        self.assertGreater(before.rfind("if await send_html(uid, text):"),
                           before.rfind("for text in outgoing:"))

    def test_released_held_alerts_are_mirrored(self):
        """Придержанное тихими часами после выхода уходит и на привязанные
        площадки — до 5.6.2 копия не отправлялась вовсе."""
        with open(os.path.join(ROOT, "radar", "monitor.py"), encoding="utf-8") as handle:
            source = handle.read()
        body = source[source.index("async def release_held"):source.index("async def repeat_sos")]
        self.assertIn("mirror.alert(uid, item.text)", body)
        self.assertGreater(body.index("mirror.alert(uid, item.text)"),
                           body.index("if not await send_html(uid, item.text):"))


class VkParseTests(unittest.TestCase):
    def _update(self, **message):
        base = {"from_id": 5, "peer_id": 5, "text": "привет", "id": 1}
        base.update(message)
        return {"type": "message_new", "object": {"message": base}}

    def test_private_message(self):
        event = vk.parse_update(self._update())
        self.assertEqual((event.key, event.chat_id, event.kind), ("vk:5", "5", EventKind.MESSAGE))
        self.assertEqual(identity.parse("vk:5").platform, "vk")

    def test_command(self):
        event = vk.parse_update(self._update(text="/Status now"))
        self.assertEqual((event.kind, event.command, event.args), (EventKind.COMMAND, "status", "now"))

    def test_chats_and_communities_ignored(self):
        self.assertIsNone(vk.parse_update(self._update(peer_id=2_000_000_001)))
        self.assertIsNone(vk.parse_update(self._update(from_id=-1)))
        self.assertIsNone(vk.parse_update({"type": "message_reply", "object": {}}))

    def test_render_and_split(self):
        self.assertEqual(vk.render('<b>Тревога</b> <a href="https://x">карта</a> &amp;'),
                         "Тревога карта (https://x) &")
        parts = vk.split_text("строка\n" * 1000)
        self.assertTrue(all(len(part) <= vk.TEXT_LIMIT for part in parts))


class VkLongPollTests(unittest.TestCase):
    def setUp(self):
        self.seen = []

        async def handler(event, transport):
            self.seen.append(event)

        self.transport = vk.VkTransport("tok", "123", handler)
        self.server = {"server": "https://lp", "key": "K", "ts": "10"}

    def step(self, payload, fresh=None):
        async def poll(server):
            return payload

        async def server():
            return fresh or {"server": "https://lp2", "key": "K2", "ts": "99"}

        with mock.patch.object(self.transport, "poll", poll), \
                mock.patch.object(self.transport, "server", server):
            return run(self.transport.step(self.server))

    def test_updates_dispatched_and_ts_advanced(self):
        result = self.step({"ts": "11", "updates": [
            {"type": "message_new", "object": {"message": {"from_id": 5, "peer_id": 5, "text": "hi"}}}]})
        self.assertEqual(result["ts"], "11")
        self.assertEqual(self.seen[0].text, "hi")

    def test_failed_1_takes_ts_from_answer(self):
        self.assertEqual(self.step({"failed": 1, "ts": "50"}), dict(self.server, ts="50"))

    def test_failed_2_new_key_same_ts(self):
        result = self.step({"failed": 2})
        self.assertEqual((result["key"], result["ts"]), ("K2", "10"))

    def test_failed_3_everything_new(self):
        self.assertEqual(self.step({"failed": 3})["ts"], "99")

    def test_configured(self):
        self.assertFalse(vk.VkTransport("tok", "abc").configured)
        self.assertTrue(vk.VkTransport("tok", "-123").configured)


class VkBotTests(MetaMixin, unittest.TestCase):
    def test_code_links(self):
        code = links.new_code("100")
        event = vk.parse_update({"type": "message_new", "object": {"message": {
            "from_id": 5, "peer_id": 5, "text": code}}})
        self.assertIn("привязан", run(vkbot.answer(event)))
        self.assertEqual(run(links.owner_of("vk", "5")), "100")

    def test_status_and_help(self):
        event = vk.parse_update({"type": "message_new", "object": {"message": {
            "from_id": 5, "peer_id": 5, "text": "/status"}}})
        with mock.patch.object(vkbot, "status_text", lambda: "✅ ok"):
            text = run(vkbot.answer(event))
        self.assertIn("✅ ok", text)
        self.assertIn("не заменяет официальные каналы оповещения", text)
        other = vk.parse_update({"type": "message_new", "object": {"message": {
            "from_id": 5, "peer_id": 5, "text": "что это"}}})
        self.assertIn("Telegram", run(vkbot.answer(other)))

    def test_flags_off_by_default(self):
        self.assertFalse(features.BY_KEY["platform_vk"].default)


if __name__ == "__main__":
    unittest.main()
