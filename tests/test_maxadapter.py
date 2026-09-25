#!/usr/bin/env python3
"""Адаптер MAX: всё, что можно проверить без живого токена (с 4.9.9.4).

Сам API не проверен ни одним запросом — токен выдают только после
верификации юрлица. Поэтому здесь проверяется то, что от сети не зависит:
разбор задокументированных событий, сборка кнопок в пределах платформы,
разметка и ответы встроенного ответчика. Если MAX когда-нибудь ответит
не тем, эти тесты покажут, что именно мы понимали неправильно.
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar.platforms import maxbot  # noqa: E402
from radar.platforms.base import Button, EventKind, OutboundMessage  # noqa: E402
from radar.platforms.max import MaxTransport  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def transport() -> MaxTransport:
    return MaxTransport(token="test-token", base_url="https://example.invalid")


class ParseTests(unittest.TestCase):
    """События разбираются по документированной схеме dev.max.ru."""

    def test_message_created(self):
        event = transport().parse_update({
            "update_type": "message_created",
            "timestamp": 1_700_000_000,
            "message": {
                "sender": {"user_id": 77, "username": "ivan"},
                "recipient": {"chat_id": -100},
                "body": {"mid": "mid-1", "text": "Привет"},
            },
        })
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.MESSAGE)
        self.assertEqual(event.chat_id, "-100")
        self.assertEqual(event.text, "Привет")
        self.assertEqual(event.message_id, "mid-1")
        self.assertEqual(event.username, "ivan")
        self.assertTrue(event.identity.key.endswith("77"))

    def test_command_split(self):
        event = transport().parse_update({
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 1}, "recipient": {"chat_id": 1},
                "body": {"text": "/start код-42"},
            },
        })
        self.assertEqual(event.kind, EventKind.COMMAND)
        self.assertEqual(event.command, "start")
        self.assertEqual(event.args, "код-42")

    def test_callback_keeps_callback_id(self):
        """Без callback_id нечем погасить «часики» у кнопки."""
        event = transport().parse_update({
            "update_type": "message_callback",
            "callback": {"callback_id": "cb-9", "payload": "menu:main",
                         "user": {"user_id": 5}},
            "message": {"recipient": {"chat_id": 5},
                        "body": {"mid": "m", "text": ""}},
        })
        self.assertEqual(event.kind, EventKind.CALLBACK)
        self.assertEqual(event.payload, "menu:main")
        self.assertEqual(event.args, "cb-9")

    def test_bot_started_is_joined(self):
        event = transport().parse_update({
            "update_type": "bot_started",
            "chat_id": 12, "user": {"user_id": 12},
        })
        self.assertEqual(event.kind, EventKind.JOINED)

    def test_location_attachment(self):
        event = transport().parse_update({
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 3}, "recipient": {"chat_id": 3},
                "body": {"text": "", "attachments": [
                    {"type": "location", "latitude": 51.53, "longitude": 46.03}]},
            },
        })
        self.assertEqual(event.kind, EventKind.LOCATION)
        self.assertAlmostEqual(event.latitude, 51.53)

    def test_garbage_ignored(self):
        adapter = transport()
        self.assertIsNone(adapter.parse_update({}))
        self.assertIsNone(adapter.parse_update("не словарь"))
        self.assertIsNone(adapter.parse_update({"update_type": "unknown"}))


class KeyboardTests(unittest.TestCase):
    """Пределы платформы: лишняя кнопка ломает всё сообщение."""

    def test_long_row_wraps(self):
        row = [Button(text=f"к{i}", payload=str(i)) for i in range(10)]
        result = transport().to_keyboard([row])
        self.assertEqual([len(line) for line in result], [7, 3])

    def test_link_rows_are_narrower(self):
        row = [Button(text=f"с{i}", url="https://example.com") for i in range(5)]
        result = transport().to_keyboard([row])
        self.assertEqual([len(line) for line in result], [3, 2])
        self.assertEqual(result[0][0]["type"], "link")

    def test_callback_payload_defaults_to_text(self):
        result = transport().to_keyboard([[Button(text="Меню")]])
        self.assertEqual(result[0][0]["payload"], "Меню")

    def test_hard_limits_respected(self):
        rows = [[Button(text="x", payload="p")] for _ in range(40)]
        result = transport().to_keyboard(rows)
        self.assertLessEqual(len(result), 30)


class RenderTests(unittest.TestCase):
    def test_known_tags_kept_unknown_dropped(self):
        adapter = transport()
        rendered = adapter.render("<b>Опасность</b> <marquee>бегущая</marquee>")
        self.assertIn("<b>Опасность</b>", rendered)
        self.assertNotIn("marquee", rendered)

    def test_plain_strips_everything(self):
        self.assertEqual(MaxTransport.plain("<b>Вода</b> &amp; свет"),
                         "Вода & свет")

    def test_after_refusal_plain_only(self):
        adapter = transport()
        adapter._html_ok = False
        self.assertEqual(adapter.render("<b>Вода</b>"), "Вода")


class ResponderTests(unittest.TestCase):
    """Встроенный ответчик: молчание хуже честного «здесь пока только ответы»."""

    def _event(self, kind, command="", text=""):
        from radar.identity import MAX, make

        from radar.platforms.base import InboundEvent

        return InboundEvent(platform=MAX, identity=make(MAX, 1), chat_id="1",
                            kind=kind, command=command, text=text)

    def test_start_explains_where_alerts_live(self):
        answer = maxbot.answer_for(self._event(EventKind.COMMAND, "start"))
        self.assertIn("Радар", answer.text)
        self.assertIn("Telegram", answer.text)
        self.assertIn("не заменяет официальные каналы", answer.text)

    def test_commands_and_places_go_to_textbot(self):
        """С 5.7 MAX — полноценный вход: команды, текст и геопозиция уходят
        общему ответчику, приветствие остаётся своим."""
        from unittest import mock

        from radar.platforms import textbot

        seen = []

        async def fake_answer(platform, external_id, text="", *, location=None):
            seen.append((platform, external_id, text, location))
            return "ответ & <тег>"

        class Transport:
            def __init__(self):
                self.sent = []

            async def send(self, chat_id, message):
                self.sent.append(message.text)
                return True

        transport = Transport()
        event = self._event(EventKind.COMMAND, "address")
        event.args = "Тверская 1"
        place = self._event(EventKind.LOCATION)
        place.latitude, place.longitude = 55.7, 37.6
        with mock.patch.object(textbot, "answer", fake_answer):
            run(maxbot.reply(event, transport))
            run(maxbot.reply(place, transport))
        self.assertEqual(seen[0], ("max", "1", "/address Тверская 1", None))
        self.assertEqual(seen[1][3], (55.7, 37.6))
        self.assertEqual(transport.sent[0], "ответ &amp; &lt;тег&gt;", "MAX получает HTML")

    def test_any_message_gets_help(self):
        answer = maxbot.answer_for(self._event(EventKind.MESSAGE, text="привет"))
        self.assertTrue(answer.text)

    def test_location_answer_is_honest(self):
        answer = maxbot.answer_for(self._event(EventKind.LOCATION))
        self.assertIn("Telegram", answer.text)

    def test_button_appears_only_with_username(self):
        self.assertEqual(maxbot.telegram_button(""), [])
        keyboard = maxbot.telegram_button("radar_bot")
        self.assertEqual(keyboard[0][0].url, "https://t.me/radar_bot")


class SendTests(unittest.TestCase):
    """Отправка: разметка не должна стоить сообщения."""

    def test_falls_back_to_plain_text_on_400(self):
        adapter = transport()
        calls: list[dict] = []

        async def fake_request(method, path, *, params=None, payload=None):
            # Копия: повтор правит тот же словарь, и ссылка показала бы
            # второе тело вместо первого.
            calls.append({"payload": dict(payload or {})})
            return (400, {}) if len(calls) == 1 else (200, {})

        adapter._request = fake_request
        ok = run(adapter.send("1", OutboundMessage(text="<b>Вода</b>")))

        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertIn("format", calls[0]["payload"])
        self.assertNotIn("format", calls[1]["payload"])
        self.assertEqual(calls[1]["payload"]["text"], "Вода")
        self.assertFalse(adapter._html_ok, "после отказа разметку не шлём")

    def test_silent_message_sets_notify_false(self):
        adapter = transport()
        seen: dict = {}

        async def fake_request(method, path, *, params=None, payload=None):
            seen.update(payload or {})
            return 200, {}

        adapter._request = fake_request
        run(adapter.send("1", OutboundMessage(text="тихо", silent=True)))
        self.assertFalse(seen["notify"])

    def test_not_configured_sends_nothing(self):
        adapter = MaxTransport(token="", base_url="https://example.invalid")
        self.assertFalse(run(adapter.send("1", OutboundMessage(text="x"))))

    def test_commands_go_to_me_commands_first(self):
        """Официальные SDK MAX (Go, TypeScript) шлют PATCH /me/commands;
        PATCH /me у них устаревший и остаётся запасным на 404 (5.6.2)."""
        adapter = transport()
        paths: list[str] = []

        async def fake_request(method, path, *, params=None, payload=None):
            paths.append(f"{method} {path}")
            return (404, {}) if path == "me/commands" and len(paths) == 1 else (200, {})

        adapter._request = fake_request
        run(adapter.set_commands([("start", "начать")]))
        self.assertEqual(paths, ["PATCH me/commands", "PATCH me"])
        paths.clear()

        async def ok_request(method, path, *, params=None, payload=None):
            paths.append(f"{method} {path}")
            return 200, {}

        adapter._request = ok_request
        run(adapter.set_commands([("start", "начать")]))
        self.assertEqual(paths, ["PATCH me/commands"])

    def test_default_base_is_platform_api2(self):
        from radar import config

        self.assertEqual(config.MAX_API_URL, "https://platform-api2.max.ru")


class MarkerTests(unittest.TestCase):
    """Маркер берётся из ответа, а не считается самостоятельно."""

    def test_marker_from_response(self):
        adapter = transport()
        seen: list[dict] = []
        answered: list[str] = []

        async def fake_request(method, path, *, params=None, payload=None):
            if path == "me":
                return 200, {"name": "Радар"}
            seen.append(dict(params or {}))
            if len(seen) == 1:
                return 200, {"marker": 42, "updates": [{
                    "update_type": "message_created",
                    "message": {"sender": {"user_id": 1},
                                "recipient": {"chat_id": 1},
                                "body": {"text": "/help"}}}]}
            adapter._running = False
            return 200, {"marker": 43, "updates": []}

        async def handler(event, _transport):
            answered.append(event.command)

        adapter._request = fake_request
        run(adapter.start(handler))

        self.assertEqual(answered, ["help"])
        self.assertIsNone(seen[0].get("marker"))
        self.assertEqual(seen[1]["marker"], 42)


if __name__ == "__main__":
    unittest.main()
