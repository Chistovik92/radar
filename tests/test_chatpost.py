#!/usr/bin/env python3
"""Объявления в группы: что проверяется до отправки (с 4.9.8.14).

Сообщение уходит от имени бота и не отзывается, поэтому все проверки,
которые можно сделать заранее, сделаны заранее — и проверены здесь.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import chatpost, features, roles  # noqa: E402
from radar.handlers import chats  # noqa: E402


class ValidationTests(unittest.TestCase):
    def test_empty_rejected(self):
        ok, reason = chatpost.validate("   ")
        self.assertFalse(ok)
        self.assertIn("Пустое", reason)

    def test_too_long_rejected(self):
        ok, reason = chatpost.validate("а" * (chatpost.MAX_LENGTH + 1))
        self.assertFalse(ok)
        self.assertIn("Слишком длинно", reason)

    def test_plain_text_accepted(self):
        self.assertEqual(chatpost.validate("Завтра отключат воду"), (True, ""))

    def test_telegram_markup_accepted(self):
        text = '<b>Важно</b>: <a href="https://example.com">подробности</a>'
        self.assertEqual(chatpost.validate(text), (True, ""))

    def test_unknown_markup_rejected(self):
        """Тег, которого Telegram не знает, — это не разметка, а отказ
        на отправке: объявление не уйдёт совсем."""
        ok, reason = chatpost.validate("<marquee>бегущая строка</marquee>")
        self.assertFalse(ok)
        self.assertIn("marquee", reason)

    def test_closing_tags_counted_once(self):
        self.assertEqual(chatpost.unsupported_tags("<b>x</b><i>y</i>"), [])


class DraftTests(unittest.TestCase):
    def test_preview_shows_text_as_is(self):
        draft = chatpost.Draft(chat_id=-100, title="Двор", text="<b>Вода</b>")
        shown = chatpost.preview(draft)
        self.assertIn("<b>Вода</b>", shown)
        self.assertIn("Двор", shown)
        self.assertIn("не отзывается", shown)

    def test_forgotten_draft_expires(self):
        """Забытый черновик не должен уйти в группу через сутки."""
        draft = chatpost.Draft(chat_id=-100, title="Двор", text="текст",
                               created=time.time() - chatpost.DRAFT_TTL - 1)
        self.assertTrue(draft.expired())
        self.assertFalse(chatpost.Draft(chat_id=-100, title="Двор",
                                        text="текст").expired())


class AccessTests(unittest.TestCase):
    """Право писать в группы — только у суперадминистратора и по флагу."""

    def setUp(self) -> None:
        features.set_local("chat_post", True)

    def tearDown(self) -> None:
        features.apply({})

    def test_superadmin_allowed(self):
        self.assertTrue(chats.can_post(roles.SUPERADMIN))

    def test_admin_denied(self):
        self.assertFalse(chats.can_post(roles.ADMIN))

    def test_user_denied(self):
        self.assertFalse(chats.can_post(roles.USER))

    def test_flag_off_denies_everyone(self):
        features.set_local("chat_post", False)
        self.assertFalse(chats.can_post(roles.SUPERADMIN))


if __name__ == "__main__":
    unittest.main()
