#!/usr/bin/env python3
"""Интеграционные тесты SQLAlchemy-репозитория на временном SQLite-файле."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


HAS_DB = _installed("sqlalchemy") and _installed("aiosqlite")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if HAS_DB:
    from support.core.attachments import Attachment  # noqa: E402
    from support.core.export import render_dialogue  # noqa: E402
    from support.db.engine import Database  # noqa: E402
    from support.db.repo import SupportRepository, ticket_number  # noqa: E402

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


@unittest.skipUnless(HAS_DB, "SQLAlchemy/aiosqlite не установлены")
class RepositoryCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(
            f"sqlite+aiosqlite:///{os.path.join(self.directory.name, 'support.db')}"
        )
        await self.database.create_schema()
        self.repo = SupportRepository(self.database, sla_minutes=60)
        self.author = await self.repo.get_or_create_user(100, "client")
        self.other = await self.repo.get_or_create_user(200, "other")
        self.moderator = await self.repo.get_or_create_user(300, "mod")
        await self.repo.get_or_create_user(900, "root", superadmin_id=900)
        await self.repo.set_role(900, 300, "moderator")

    async def asyncTearDown(self):
        await self.database.close()
        self.directory.cleanup()

    async def test_number_access_and_wrong_year(self):
        ticket = await self.repo.create_ticket(100, now=NOW)
        self.assertEqual(ticket_number(ticket), "#2026-1")
        self.assertIsNotNone(await self.repo.get_ticket("#2026-1", 100))
        self.assertIsNotNone(await self.repo.get_ticket("#2026-1", 300))
        self.assertIsNone(await self.repo.get_ticket("#2026-1", 200))
        self.assertIsNone(await self.repo.get_ticket("#2025-1", 100))
        self.assertIsNone(await self.repo.set_active("#2026-1", 200))
        self.assertIsNotNone(await self.repo.set_active("#2026-1", 100))
        self.assertEqual((await self.repo.active_ticket(100)).id, ticket.id)

    async def test_status_first_response_close_rating_stats(self):
        ticket = await self.repo.create_ticket(100, now=NOW)
        await self.repo.add_message(ticket.id, 100, "Не проходит оплата", now=NOW)
        self.assertEqual(ticket.status, "open")
        self.assertEqual((await self.repo.get_ticket(ticket.id, 100)).category, "оплата")
        answered = await self.repo.add_message(
            ticket.id, 300, "Проверяем", now=NOW + timedelta(minutes=20)
        )
        self.assertEqual(answered[0].status, "answered")
        self.assertEqual(answered[0].first_response_at, NOW + timedelta(minutes=20))
        self.assertEqual(answered[0].assignee_id, self.moderator.id)
        await self.repo.add_message(ticket.id, 100, "Всё ещё не работает")
        self.assertEqual((await self.repo.get_ticket(ticket.id, 100)).status, "open")
        closed = await self.repo.close_ticket(ticket.id, 100, NOW + timedelta(minutes=30))
        self.assertEqual(closed.status, "closed")
        self.assertFalse(await self.repo.rate_ticket(ticket.id, 300, 1))
        self.assertFalse(await self.repo.rate_ticket(ticket.id, 200, 1))
        self.assertTrue(await self.repo.rate_ticket(ticket.id, 100, 1))
        report = await self.repo.statistics(300)
        self.assertEqual(report["positive"], 1)
        self.assertEqual(report["satisfaction"], 100.0)
        self.assertEqual(report["sla_on_time"], 1)
        self.assertEqual(report["by_category"]["оплата"], [1, 0])
        self.assertIsNone(await self.repo.statistics(200))

    async def test_statistics_use_stored_sla_deadline_not_current_setting(self):
        ticket = await self.repo.create_ticket(100, now=NOW)
        await self.repo.add_message(ticket.id, 300, "Ответ", now=NOW + timedelta(minutes=20))
        self.repo.sla_minutes = 1
        report = await self.repo.statistics(300)
        self.assertEqual(report["sla_on_time"], 1)

    async def test_sla_escalates_only_once(self):
        ticket = await self.repo.create_ticket(100, now=NOW)
        self.assertEqual(await self.repo.escalate_overdue(NOW + timedelta(minutes=59)), [])
        overdue = await self.repo.escalate_overdue(NOW + timedelta(minutes=61))
        self.assertEqual([row.id for row in overdue], [ticket.id])
        self.assertEqual(overdue[0].priority, "high")
        self.assertEqual(await self.repo.escalate_overdue(NOW + timedelta(minutes=62)), [])
        data = await self.repo.export_data(ticket.id, 100)
        self.assertIn("SLA", data["messages"][-1]["body"])

    async def test_one_topic_one_ticket_and_author_access(self):
        ticket = await self.repo.create_ticket(100, group_id=-100500, thread_id=77, now=NOW)
        self.assertEqual((await self.repo.by_topic(-100500, 77, 100)).id, ticket.id)
        self.assertEqual((await self.repo.by_topic(-100500, 77, 300)).id, ticket.id)
        self.assertIsNone(await self.repo.by_topic(-100500, 77, 200))
        self.assertIsNotNone(await self.repo.by_topic_any(-100500, 77))

    async def test_attachment_and_export(self):
        ticket = await self.repo.create_ticket(100, now=NOW)
        item = Attachment("telegram-file", "document", "screen.png", "caption")
        await self.repo.add_message(
            ticket.id, 100, "[document: screen.png]", "attachment", item, NOW,
        )
        await self.repo.add_message(ticket.id, 300, "Ответ оператора", now=NOW + timedelta(minutes=2))
        await self.repo.close_ticket(ticket.id, 300, NOW + timedelta(minutes=3))
        data = await self.repo.export_data("#2026-1", 100)
        self.assertEqual(data["messages"][0]["attachment_file_id"], "telegram-file")
        text = render_dialogue(data)
        self.assertIn("@client", text)
        self.assertIn("@mod", text)
        self.assertIn("тикет закрыт", text)
        self.assertIsNone(await self.repo.export_data(ticket.id, 200))

    async def test_faq_editing_and_role_permissions(self):
        self.assertFalse(await self.repo.set_faq(100, "ключ", "ответ"))
        self.assertTrue(await self.repo.set_faq(300, "Ключ", "Новый ответ"))
        self.assertEqual(await self.repo.faq_entries(), {"ключ": "Новый ответ"})
        self.assertFalse(await self.repo.delete_faq(200, "ключ"))
        self.assertTrue(await self.repo.delete_faq(300, "Ключ"))
        self.assertFalse(await self.repo.set_role(300, 100, "moderator"))
        self.assertTrue(await self.repo.set_role(900, 100, "admin"))

    async def test_delete_does_not_reuse_sqlite_id(self):
        first = await self.repo.create_ticket(100, now=NOW)
        self.assertFalse(await self.repo.delete_ticket(first.id, 300))
        self.assertTrue(await self.repo.delete_ticket(first.id, 900))
        second = await self.repo.create_ticket(100, now=NOW)
        self.assertEqual(second.id, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
