#!/usr/bin/env python3
"""Офлайн-тесты чистой логики отдельного бота поддержки."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from support.core import attachments, classify, config, export, roles, sla  # noqa: E402
from support.core.config import Settings  # noqa: E402
from support.db.repo import parse_number, subject_from, ticket_number  # noqa: E402
from support.handlers import group, operator  # noqa: E402
from support.handlers.common import new_ticket_keyboard, rating_keyboard, ticket_line  # noqa: E402


class TestTicketNumbers(unittest.TestCase):
    def test_human_number_uses_creation_year_and_database_id(self):
        ticket = SimpleNamespace(id=123, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(ticket_number(ticket), "#2026-123")
        self.assertEqual(parse_number("#2026-123"), (2026, 123))
        self.assertEqual(parse_number("2026-123"), (2026, 123))

    def test_other_formats_rejected(self):
        for value in ("", "123", "#123", "#26-1", "#2026-0x", "../2026-1"):
            self.assertIsNone(parse_number(value), value)

    def test_subject_is_single_line_and_bounded(self):
        self.assertEqual(subject_from("  две\n строки "), "две строки")
        self.assertLessEqual(len(subject_from("я" * 500)), 200)


class TestAccessRoles(unittest.TestCase):
    def test_hierarchy(self):
        self.assertTrue(roles.at_least("admin", "moderator"))
        self.assertTrue(roles.at_least("superadmin", "admin"))
        self.assertFalse(roles.at_least("user", "moderator"))

    def test_assignment_cannot_escalate_equals(self):
        self.assertTrue(roles.can_assign("admin", "user", "moderator"))
        self.assertFalse(roles.can_assign("admin", "admin", "user"))
        self.assertFalse(roles.can_assign("moderator", "user", "user"))
        self.assertTrue(roles.can_assign("superadmin", "admin", "user"))
        self.assertFalse(roles.can_assign("superadmin", "superadmin", "user"))


class TestSLA(unittest.TestCase):
    def test_deadline_and_overdue(self):
        created = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
        due = sla.deadline(created, 60)
        self.assertEqual(due, created + timedelta(hours=1))
        self.assertTrue(sla.is_overdue(due, "open", None, due))
        self.assertFalse(sla.is_overdue(due, "answered", None, due + timedelta(seconds=1)))
        self.assertFalse(sla.is_overdue(due, "open", created, due + timedelta(seconds=1)))

    def test_response_on_time(self):
        created = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
        self.assertTrue(sla.response_within_sla(created, created + timedelta(minutes=30), 60))
        self.assertFalse(sla.response_within_sla(created, created + timedelta(minutes=61), 60))
        self.assertFalse(sla.response_within_sla(created, None, 60))
        with self.assertRaises(ValueError):
            sla.deadline(created, 0)


class TestKnowledge(unittest.TestCase):
    def test_faq_deterministic_without_key(self):
        self.assertIn("пароль", classify.faq_answer("Забыл пароль").lower())
        self.assertIsNone(classify.faq_answer("совершенно незнакомый вопрос"))
        self.assertEqual(classify.classify("Не проходит платёж"), "оплата")
        self.assertEqual(classify.classify("VPN не подключается"), "VPN")
        self.assertEqual(classify.classify("другое"), "прочее")

    def test_custom_faq_overrides_default(self):
        answer = classify.faq_answer("оплата картой", {"оплата": "Свой ответ"})
        self.assertEqual(answer, "Свой ответ")

    def test_ai_not_called_when_faq_matches(self):
        class BrokenAI:
            async def ask(self, text):
                raise AssertionError("FAQ должен отвечать до AI")
        result = asyncio.run(classify.KnowledgeBase(BrokenAI()).answer("забыл пароль"))
        self.assertIsNotNone(result)

    def test_ai_failure_falls_back_to_none(self):
        class BrokenAI:
            async def ask(self, text):
                return None
        result = asyncio.run(classify.KnowledgeBase(BrokenAI()).answer("новый вопрос"))
        self.assertIsNone(result)

    def test_disabled_gemini_does_not_import_sdk(self):
        assistant = classify.GeminiAssistant(False, "", "model")
        self.assertFalse(assistant.enabled)
        self.assertIsNone(asyncio.run(assistant.ask("вопрос")))
        self.assertEqual(asyncio.run(classify.KnowledgeBase(assistant).category("оплата")), "оплата")

    def test_ai_category_has_deterministic_fallback(self):
        class BrokenAI:
            enabled = True

            async def category(self, text):
                return None

        result = asyncio.run(classify.KnowledgeBase(BrokenAI()).category("VPN не работает"))
        self.assertEqual(result, "VPN")


class TestAttachments(unittest.TestCase):
    def test_largest_photo(self):
        message = SimpleNamespace(caption="скрин", document=None, photo=[
            SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large")
        ])
        item = attachments.from_message(message)
        self.assertEqual((item.file_id, item.kind, item.caption), ("large", "photo", "скрин"))

    def test_document_name_and_export_description(self):
        message = SimpleNamespace(caption="лог", document=SimpleNamespace(
            file_id="doc", file_name="error.log"
        ), photo=None)
        item = attachments.from_message(message)
        self.assertEqual(attachments.describe(item), "[document: error.log] лог")

    def test_plain_text_is_not_attachment(self):
        message = SimpleNamespace(caption=None, document=None, photo=None)
        for name in ("video", "animation", "audio", "voice", "video_note", "sticker"):
            setattr(message, name, None)
        self.assertIsNone(attachments.from_message(message))


class TestExport(unittest.TestCase):
    def setUp(self):
        self.data = {
            "ticket": {
                "number": "#2026-123", "subject": "Нет доступа", "category": "доступ",
                "author_id": 10, "created_at": datetime(2026, 11, 21, 12, 32, tzinfo=timezone.utc),
                "closed_at": datetime(2026, 11, 21, 13, 10, tzinfo=timezone.utc),
            },
            "author": {"id": 10, "external_id": 123456, "username": "client"},
            "assignee": {"id": 20, "external_id": 999, "username": "operator"},
            "messages": [
                {"kind": "text", "body": "Не могу войти", "sender": {"id": 10, "external_id": 123456, "username": "client"}, "created_at": datetime(2026, 11, 21, 12, 32, tzinfo=timezone.utc)},
                {"kind": "attachment", "body": "[document: error.log]", "sender": {"id": 10, "external_id": 123456, "username": "client"}, "created_at": datetime(2026, 11, 21, 12, 33, tzinfo=timezone.utc)},
                {"kind": "system", "body": "тикет закрыт", "sender": None, "created_at": datetime(2026, 11, 21, 13, 10, tzinfo=timezone.utc)},
            ],
        }

    def test_human_readable_msk_dialogue(self):
        text = export.render_dialogue(self.data)
        self.assertIn("Обращение #2026-123", text)
        self.assertIn("Автор: @client (id 123456)", text)
        self.assertIn("15:32 (MSK)", text)
        self.assertIn("[15:32] 👤 @client", text)
        self.assertIn("[document: error.log]", text)
        self.assertIn("⚙️ система: тикет закрыт", text)

    def test_archive_utf8_and_atomic_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = export.save_dialogue(self.data, directory)
            self.assertTrue(path.endswith("2026-123.txt"))
            with open(path, encoding="utf-8") as handle:
                self.assertIn("Нет доступа", handle.read())
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_parallel_exports_use_unique_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with ThreadPoolExecutor(max_workers=2) as pool:
                paths = list(pool.map(lambda _: export.save_dialogue(self.data, directory), range(2)))
            self.assertEqual(paths, [os.path.join(directory, "2026-123.txt")] * 2)
            self.assertEqual(os.listdir(directory), ["2026-123.txt"])


class TestConfigurationAndKeyboards(unittest.TestCase):
    def test_required_token_and_admin(self):
        with self.assertRaises(ValueError):
            Settings(token="", admin_id=1).validate()
        with self.assertRaises(ValueError):
            Settings(token="123:token", admin_id=0).validate()
        Settings(token="123:token", admin_id=1).validate()

    def test_signed_group_id_and_separate_bot_token(self):
        with patch.dict(os.environ, {"SUPPORT_GROUP_ID": "-1001234567890"}, clear=False):
            self.assertEqual(Settings.from_env().group_id, -1001234567890)
        with patch.dict(os.environ, {"BOT_TOKEN": "123:token"}, clear=False):
            with self.assertRaises(ValueError):
                Settings(token="123:token", admin_id=1).validate()

    def test_postgres_url_normalization_and_sqlite_default(self):
        settings = Settings(token="x", admin_id=1, database_url="postgresql://u:p@host/db")
        self.assertEqual(settings.sqlalchemy_url(), "postgresql+asyncpg://u:p@host/db")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "support.db")
            local = Settings(token="x", admin_id=1, db_file=path)
            self.assertTrue(local.sqlalchemy_url().startswith("sqlite+aiosqlite:///"))

    def test_rating_buttons_and_new_ticket(self):
        ticket = SimpleNamespace(id=123)
        markup = rating_keyboard(ticket)
        self.assertEqual([b.text for b in markup.inline_keyboard[0]], ["👍", "👎"])
        self.assertEqual(markup.inline_keyboard[0][1].callback_data, "support:rate:123:-1")
        self.assertEqual(new_ticket_keyboard().inline_keyboard[0][0].callback_data, "support:new")


class TestHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_group_ignores_empty_and_unknown_commands_before_create(self):
        class NoCreateRepo:
            async def get_or_create_user(self, *args, **kwargs):
                raise AssertionError("Служебное сообщение не должно создавать пользователя/тикет")

        config = Settings(token="x", admin_id=1, group_id=-100)
        for text in ("", "   ", "/unknown", "/unknown аргумент"):
            message = SimpleNamespace(
                chat=SimpleNamespace(id=-100), from_user=SimpleNamespace(id=1),
                text=text, caption=None, document=None, photo=None,
                video=None, animation=None, audio=None, voice=None,
                video_note=None, sticker=None,
            )
            await group.topic_dialogue(message, NoCreateRepo(), config, classify.KnowledgeBase())

    async def test_draft_escapes_ai_html(self):
        class AI:
            enabled = True

            async def ask(self, text):
                return "<b>не доверяй AI</b> & проверь"

        class Repo:
            async def get_or_create_user(self, *args, **kwargs):
                return SimpleNamespace(external_id=300, role="moderator")

            async def export_data(self, *args):
                return {
                    "ticket": {"author_id": 10},
                    "messages": [{"kind": "text", "body": "вопрос", "sender": {"id": 10}}],
                }

        message = SimpleNamespace(
            from_user=SimpleNamespace(id=300, username="mod"), text="/draft #2026-1",
            answer=AsyncMock(),
        )
        await operator.draft(message, Repo(), Settings(token="x", admin_id=1), classify.KnowledgeBase(AI()))
        sent = message.answer.await_args.args[0]
        self.assertIn("&lt;b&gt;не доверяй AI&lt;/b&gt; &amp; проверь", sent)
        self.assertNotIn("<b>", sent)

    async def test_topic_close_exports_to_author_despite_telegram_errors(self):
        ticket = SimpleNamespace(
            id=1, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="closed", priority="normal", subject="тема",
        )
        data = {
            "ticket": {
                "number": "#2026-1", "subject": "тема", "category": "прочее",
                "author_id": 10, "created_at": ticket.created_at, "closed_at": ticket.created_at,
            },
            "author": {"id": 10, "external_id": 100, "username": "client"},
            "assignee": None, "messages": [],
        }

        class Repo:
            closed = False

            async def get_or_create_user(self, *args, **kwargs):
                return SimpleNamespace(external_id=300)

            async def by_topic(self, *args):
                return ticket

            async def close_ticket(self, *args):
                self.closed = True
                return ticket

            async def export_data(self, *args):
                return data

        bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=RuntimeError("Telegram unavailable")),
            send_document=AsyncMock(side_effect=RuntimeError("Telegram unavailable")),
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100), from_user=SimpleNamespace(id=300),
            message_thread_id=77, bot=bot, answer=AsyncMock(side_effect=RuntimeError("Telegram unavailable")),
        )
        repo = Repo()
        with tempfile.TemporaryDirectory() as directory:
            await group.close_topic(message, repo, Settings(token="x", admin_id=1, group_id=-100, export_dir=directory))
        self.assertTrue(repo.closed)
        self.assertEqual(bot.send_document.await_count, 2)
        self.assertEqual(bot.send_document.await_args_list[1].args[0], 100)

    async def test_ticket_subject_is_escaped(self):
        ticket = SimpleNamespace(
            id=1, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="open", priority="normal", subject="<b>subject</b>",
        )
        self.assertIn("&lt;b&gt;subject&lt;/b&gt;", ticket_line(ticket))


if __name__ == "__main__":
    unittest.main(verbosity=2)
