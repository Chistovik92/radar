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
from radar.platforms import discord, textbot, vk, vkbot  # noqa: E402
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

        async def save(uid=None):
            self.saved.append(uid)

        async def drop_user(uid):
            storage.DB["users"].pop(storage._key(uid), None)

        self.saved = []
        self.users_before = dict(storage.DB["users"])
        storage.DB["users"].clear()
        self.patches = [mock.patch.object(storage, "meta_get", meta_get),
                        mock.patch.object(storage, "meta_set", meta_set),
                        mock.patch.object(storage, "save", save),
                        mock.patch.object(storage, "drop_user", drop_user)]
        for patch in self.patches:
            patch.start()
        links.reset()
        textbot.reset()

    def tearDown(self):
        from radar import storage

        for patch in self.patches:
            patch.stop()
        storage.DB["users"].clear()
        storage.DB["users"].update(self.users_before)
        links.reset()
        textbot.reset()


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

    def test_relink_to_other_telegram_refused(self):
        """У аккаунта одна запись в каждой сети (5.7): ВК, привязанный к одному
        Telegram, не переходит к другому молча — сначала /unlink."""
        run(links.redeem("vk", "555", links.new_code("100")))
        uid, reason = run(links.redeem("vk", "555", links.new_code("200")))
        self.assertEqual(uid, "")
        self.assertIn("Telegram", reason)
        self.assertEqual(run(links.owner_of("vk", "555")), "100")
        run(links.unlink_external("vk", "555"))
        self.assertEqual(run(links.redeem("vk", "555", links.new_code("200")))[0], "200")

    def test_unlink_both_sides(self):
        run(links.redeem("vk", "555", links.new_code("100")))
        run(links.redeem("max", "9", links.new_code("100")))
        self.assertEqual(run(links.unlink("100", "vk")), ["vk"])
        self.assertTrue(run(links.unlink_external("max", "9")))
        self.assertEqual(run(links.links_of("100")), {})

    def test_unknown_platform(self):
        self.assertEqual(run(links.redeem("viber", "1", links.new_code("100")))[0], "")

    def test_handle_text_needs_confirmation(self):
        code = links.new_code("100")
        proposal = run(links.handle_text("vk", "5", code))
        self.assertIn("Telegram", proposal)
        self.assertIn("«да»", proposal)
        self.assertEqual(run(links.owner_of("vk", "5")), "", "без «да» связи нет")

        async def confirm():
            return await links.handle_text("vk", "5", "да")

        self.assertIn("связаны", run(confirm()))
        self.assertEqual(run(links.owner_of("vk", "5")), "100")
        self.assertIn("снята", run(links.handle_text("vk", "5", "/unlink")))
        self.assertEqual(run(links.handle_text("vk", "5", "привет")), "")

    def test_decline(self):
        run(links.handle_text("vk", "5", links.new_code("100")))
        self.assertIn("не связаны", run(links.handle_text("vk", "5", "нет")))
        self.assertEqual(run(links.owner_of("vk", "5")), "")


class AccountTests(MetaMixin, unittest.TestCase):
    """Общий аккаунт (5.7): вход из любой сети, Telegram — основной ключ."""

    def _profile(self, key, *points, role="user", lang=""):
        from radar import storage

        user = storage.register(key)
        user["role"], user["lang"] = role, lang
        for index, (lat, lon) in enumerate(points):
            user["locs"].append(storage.new_location(f"место {index}", lat, lon))
        return user

    def test_code_from_vk_entered_in_telegram(self):
        """Код можно выдать и во ВКонтакте — Telegram всё равно основной."""
        self._profile("vk:5", (55.75, 37.61))
        self._profile("100", role="moderator")
        code = run(links.handle_text("vk", "5", "/link")).split()[2]
        uid, reason = run(links.redeem("telegram", "100", code))
        self.assertEqual((uid, reason), ("100", ""))
        from radar import storage

        self.assertIsNone(storage.get_user("vk:5"), "профиль ВК влился в Telegram")
        self.assertEqual(len(storage.get_user("100")["locs"]), 1)
        self.assertEqual(storage.get_user("100")["role"], "moderator")
        self.assertEqual(run(links.canonical("vk:5")), "100")
        self.assertEqual(run(links.members("vk:5")), {"telegram": "100", "vk": "5"})

    def test_merge_keeps_places_without_duplicates(self):
        self._profile("100", (55.75, 37.61), lang="en")
        self._profile("max:9", (55.75001, 37.61001), (59.93, 30.33), role="admin")
        run(links.redeem("max", "9", links.new_code("100")))
        from radar import storage

        user = storage.get_user("100")
        self.assertEqual(len(user["locs"]), 2, "точка ближе 40 м — та же")
        self.assertEqual(user["role"], "user", "слияние не повышает роль")
        self.assertEqual(user["lang"], "en")

    def test_without_telegram_issuer_is_primary(self):
        self._profile("vk:5", (55.75, 37.61))
        run(links.redeem("max", "9", links.new_code("vk:5")))
        self.assertEqual(run(links.canonical("max:9")), "vk:5")
        self.assertEqual(run(links.links_of("vk:5")), {"max": "9"})
        # Позже приходит Telegram — профиль переезжает под Telegram-ключ.
        run(links.redeem("telegram", "100", links.new_code("max:9")))
        from radar import storage

        self.assertEqual(run(links.canonical("vk:5")), "100")
        self.assertEqual(run(links.links_of("100")), {"vk": "5", "max": "9"})
        self.assertEqual(len(storage.get_user("100")["locs"]), 1)
        self.assertIsNone(storage.get_user("vk:5"))

    def test_two_telegrams_never_merge(self):
        run(links.redeem("vk", "5", links.new_code("100")))
        uid, reason = run(links.redeem("telegram", "200", links.new_code("vk:5")))
        self.assertEqual(uid, "")
        self.assertIn("Telegram", reason)

    def test_own_code_is_not_a_link(self):
        run(links.redeem("vk", "5", links.new_code("100")))
        self.assertIn("уже связаны", run(links.redeem("vk", "5", links.new_code("100")))[1])

    def test_unlink_from_primary_detaches_others(self):
        run(links.redeem("max", "9", links.new_code("vk:5")))
        self.assertTrue(run(links.unlink_external("vk", "5")))
        self.assertEqual(run(links.canonical("max:9")), "max:9")

    def test_legacy_links_still_read(self):
        """Привязки 5.6 ({tg: {vk: id}}) читаются без переделки."""
        self.meta[links.META_KEY] = {"100": {"vk": "5"}}
        self.assertEqual(run(links.canonical("vk:5")), "100")

    def test_panel_code_only_for_moderators(self):
        from radar import features
        from radar.web import auth

        features.set_local("web_panel", True)
        try:
            text, issued = links.panel_code("100", {"role": "user"})
            self.assertFalse(issued)
            text, issued = links.panel_code("100", {"role": "moderator"})
            self.assertTrue(issued)
            code = text.split()[4]
            session, reason = auth.authenticate_code(code, lambda key: "moderator", "1.2.3.4")
            self.assertEqual((session.user_key, reason), ("100", ""))
            again, reason = auth.authenticate_code(code, lambda key: "moderator", "1.2.3.4")
            self.assertIsNone(again, "код одноразовый")
        finally:
            features.apply({})


class TextBotTests(MetaMixin, unittest.TestCase):
    """Адреса из ВК и MAX (5.7): сохраняются только после «да»."""

    def setUp(self):
        super().setUp()
        self.found = [{"name": "Тверская, 1", "lat": "55.757", "lon": "37.613",
                       "street": "Тверская", "house": "1", "city": "Москва",
                       "district": "", "region": ""}]

        async def forward(query, hint):
            return list(self.found)

        async def point(lat, lon):
            return {"name": "Точка", "lat": lat, "lon": lon, "street": "", "house": "",
                    "city": "Москва", "district": "", "region": ""}

        self.geo = [mock.patch.object(textbot, "_geocode_text", forward),
                    mock.patch.object(textbot, "_geocode_point", point)]
        for patch in self.geo:
            patch.start()

    def tearDown(self):
        for patch in self.geo:
            patch.stop()
        super().tearDown()

    def say(self, text, platform="vk", who="5", location=None):
        return run(textbot.answer(platform, who, text, location=location))

    def test_address_saved_only_after_yes(self):
        from radar import storage

        self.assertIn("Тверская", self.say("/address Тверская 1, Москва"))
        self.assertIsNone(storage.get_user("vk:5"), "без «да» ничего не сохранено")
        self.assertIn("сохранён", self.say("да"))
        self.assertEqual(storage.get_user("vk:5")["locs"][0]["street"], "Тверская")
        self.assertIn("уже сохранён", self.say("/address Тверская 1"))
        self.assertIn("1. Тверская", self.say("/addresses"))
        self.assertIn("Удалено", self.say("/remove 1"))
        self.assertEqual(storage.get_user("vk:5")["locs"], [])

    def test_no_saves_nothing(self):
        from radar import storage

        self.say("/address Тверская 1")
        self.assertIn("не сохраняю", self.say("нет"))
        self.assertIsNone(storage.get_user("vk:5"))

    def test_geolocation(self):
        from radar import storage

        self.assertIn("Точка", self.say("", platform="max", who="9", location=(55.7, 37.6)))
        self.say("да", platform="max", who="9")
        self.assertEqual(len(storage.get_user("max:9")["locs"]), 1)

    def test_address_from_vk_goes_to_linked_telegram_profile(self):
        from radar import storage

        storage.register("100")
        run(links.redeem("vk", "5", links.new_code("100")))
        self.say("/address Тверская 1")
        self.say("да")
        self.assertEqual(len(storage.get_user("100")["locs"]), 1)
        self.assertIsNone(storage.get_user("vk:5"))

    def test_not_found(self):
        self.found = []
        self.assertIn("не найден", self.say("/address нигде"))

    def test_help_mentions_disclaimer(self):
        text = self.say("привет")
        self.assertIn("/address", text)
        self.assertIn("не заменяет официальные каналы оповещения", text)

    def test_english(self):
        self.say("/lang en")
        self.assertIn("/address", self.say("hello"))


class RoutingTests(MetaMixin, unittest.TestCase):
    def test_send_html_routes_other_networks(self):
        from radar import tg

        sent = []

        async def to_vk(external, text):
            sent.append((external, text))
            return True

        mirror.register("vk", to_vk)
        try:
            self.assertTrue(run(tg.send_html("vk:5", "тревога")))
            self.assertFalse(run(tg.send_html("max:9", "тревога")), "MAX не запущен")
        finally:
            mirror.unregister("vk")
        self.assertEqual(sent, [("5", "тревога")])

    def test_callback_keys(self):
        from radar import storage

        storage.register("vk:5")
        self.assertEqual(identity.cb_key("vk:5"), "vk.5")
        self.assertEqual(identity.cb_key("123"), "123")
        self.assertIsNotNone(storage.get_user("vk.5"))
        self.assertEqual(identity.parse("vk.5").key, "vk:5")

    def test_discord_command_options(self):
        event = discord.parse_interaction({
            "type": 2, "id": "1", "token": "t", "channel_id": "c",
            "user": {"id": "42", "username": "x"},
            "data": {"name": "address", "options": [
                {"name": "query", "type": 3, "value": "Тверская 1"}]}})
        self.assertEqual((event.command, event.args, event.text),
                         ("address", "Тверская 1", "/address Тверская 1"))


class DiscordPersonalTests(MetaMixin, unittest.TestCase):
    """Discord не читает текст — «да»/«нет» там кнопки, ответ виден только автору."""

    class Transport:
        def __init__(self):
            self.responses = []

        async def respond(self, event, message, *, update=False, ephemeral=False):
            self.responses.append((message, update, ephemeral))
            return True

    def interaction(self, **data):
        base = {"id": "1", "token": "t", "channel_id": "c", "user": {"id": "42"}}
        base.update(data)
        return discord.parse_interaction(base)

    def test_link_with_buttons(self):
        from radar.platforms import discordbot

        transport = self.Transport()
        code = links.new_code("100")
        run(discordbot.reply(self.interaction(type=2, data={
            "name": "link", "options": [{"name": "code", "type": 3, "value": code}]}),
            transport))
        message, update, ephemeral = transport.responses[-1]
        self.assertTrue(ephemeral)
        self.assertEqual([button.payload for button in message.keyboard[0]],
                         [discordbot.YES_ID, discordbot.NO_ID])
        run(discordbot.reply(self.interaction(type=3, data={"custom_id": discordbot.YES_ID}),
                             transport))
        message, update, ephemeral = transport.responses[-1]
        self.assertTrue(update and ephemeral)
        self.assertIn("связаны", message.text)
        self.assertEqual(run(links.owner_of("discord", "42")), "100")


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
    def _event(self, text):
        return vk.parse_update({"type": "message_new", "object": {"message": {
            "from_id": 5, "peer_id": 5, "text": text}}})

    def test_code_links_after_yes(self):
        code = links.new_code("100")
        self.assertIn("«да»", run(vkbot.answer(self._event(code))))
        self.assertIn("связаны", run(vkbot.answer(self._event("да"))))
        self.assertEqual(run(links.owner_of("vk", "5")), "100")

    def test_status_and_help(self):
        with mock.patch.object(textbot, "status_text", lambda lang="ru": "✅ ok"):
            text = run(vkbot.answer(self._event("/status")))
        self.assertIn("✅ ok", text)
        self.assertIn("не заменяет официальные каналы оповещения", text)
        self.assertIn("/address", run(vkbot.answer(self._event("что это"))))

    def test_geo_is_location(self):
        event = vk.parse_update({"type": "message_new", "object": {"message": {
            "from_id": 5, "peer_id": 5, "text": "",
            "geo": {"type": "point", "coordinates": {"latitude": 55.7, "longitude": 37.6}}}}})
        self.assertEqual((event.kind, event.latitude, event.longitude),
                         (EventKind.LOCATION, 55.7, 37.6))

    def test_flags_off_by_default(self):
        self.assertFalse(features.BY_KEY["platform_vk"].default)


if __name__ == "__main__":
    unittest.main()
