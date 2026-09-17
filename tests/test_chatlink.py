#!/usr/bin/env python3
"""Ссылка на группу (с 4.9.8.12).

Главное здесь — то, чего делать нельзя. `exportChatInviteLink` ОТЗЫВАЕТ
прежнюю постоянную ссылку: все, кому владелец её раздал, остаются
с нерабочей. Разница с `createChatInviteLink` в одном вызове, а цена
ошибки — сломанные приглашения у живых людей, причём заметят это
не сразу.
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

from radar import chatlink  # noqa: E402


class FakeChat:
    def __init__(self, username: str = "", invite_link: str = "",
                 title: str = "Группа") -> None:
        self.username = username
        self.invite_link = invite_link
        self.title = title


class FakeBot:
    """Считает вызовы: важно не только что вернули, но и чего не трогали."""

    def __init__(self, chat: FakeChat | None = None, fail: bool = False) -> None:
        self.chat = chat or FakeChat()
        self.fail = fail
        self.created = 0
        self.exported = 0

    async def get_chat(self, chat_id):
        if self.fail:
            raise RuntimeError("чат недоступен")
        return self.chat

    async def create_chat_invite_link(self, chat_id, name=""):
        self.created += 1
        return type("Link", (), {"invite_link": "https://t.me/+created"})()

    async def export_chat_invite_link(self, chat_id):
        # Вызова быть не должно — считаем, чтобы тест это доказал.
        self.exported += 1
        return "https://t.me/+exported"


class Choice(unittest.TestCase):
    def setUp(self) -> None:
        chatlink._cache.clear()

    def test_public_username_wins(self):
        bot = FakeBot(FakeChat(username="mychat"))
        ok, link = asyncio.run(chatlink.link_for(-100, bot))
        self.assertTrue(ok)
        self.assertEqual(link, "https://t.me/mychat")
        self.assertEqual(bot.created, 0)

    def test_existing_owner_link_is_reused(self):
        # Ссылка владельца уже разослана людям — подменять её нельзя.
        bot = FakeBot(FakeChat(invite_link="https://t.me/+owner"))
        ok, link = asyncio.run(chatlink.link_for(-100, bot))
        self.assertTrue(ok)
        self.assertEqual(link, "https://t.me/+owner")
        self.assertEqual(bot.created, 0)
        self.assertEqual(bot.exported, 0)

    def test_own_link_created_only_as_last_resort(self):
        bot = FakeBot(FakeChat())
        ok, link = asyncio.run(chatlink.link_for(-100, bot))
        self.assertTrue(ok)
        self.assertEqual(link, "https://t.me/+created")
        self.assertEqual(bot.created, 1)
        self.assertEqual(bot.exported, 0)

    def test_unreachable_chat_explains_itself(self):
        bot = FakeBot(fail=True)
        ok, reason = asyncio.run(chatlink.link_for(-100, bot))
        self.assertFalse(ok)
        self.assertIn("недоступен", reason)

    def test_result_is_cached(self):
        bot = FakeBot(FakeChat(username="mychat"))
        asyncio.run(chatlink.link_for(-100, bot))
        asyncio.run(chatlink.link_for(-100, bot))
        self.assertEqual(chatlink._cache[-100], "https://t.me/mychat")

    def test_forget_clears_cache(self):
        bot = FakeBot(FakeChat(username="mychat"))
        asyncio.run(chatlink.link_for(-100, bot))
        chatlink.forget(-100)
        self.assertNotIn(-100, chatlink._cache)


class NeverRevokes(unittest.TestCase):
    def test_export_is_not_used_anywhere(self):
        # Инвариант на уровне исходника: метод, отзывающий чужую ссылку,
        # не должен появиться здесь и позже, по невнимательности.
        with open(os.path.join(ROOT, "radar", "chatlink.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("export_chat_invite_link(", source)
        self.assertIn("create_chat_invite_link(", source)


class Membership(unittest.TestCase):
    """Уже сидящих в группе бот не трогает."""

    def setUp(self) -> None:
        with open(os.path.join(ROOT, "radar", "handlers", "group.py"),
                  encoding="utf-8") as handle:
            self.source = handle.read()

    def test_chat_registers_itself(self):
        self.assertIn("@router.my_chat_member()", self.source)
        self.assertIn("repo.chat_save", self.source)

    def test_leaving_forgets_the_chat(self):
        self.assertIn("repo.chat_forget", self.source)
        self.assertIn("chatlink.forget", self.source)

    def test_greeting_only_on_join_event(self):
        # Приветствие висит на событии вступления, а не на любом
        # сообщении: значит давним участникам оно не достанется.
        self.assertIn("@router.message(F.new_chat_members)", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
