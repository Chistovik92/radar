#!/usr/bin/env python3
"""Панель: облака и объявления в чаты (с 4.9.9.1).

Сеть здесь не поднимается, поэтому проверяется всё, что решается до неё:
какие поля уйдут в конфиг rclone, что считается ссылкой приглашения
и как собирается экран подтверждения объявления. Ровно эти места и стоит
проверять: ошибка в них означает либо мусор в чужом конфиге, либо кнопку,
ведущую в никуда, либо объявление не в ту группу.
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import chatlink, chatpost, rclonerc  # noqa: E402
from radar.web import panel  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class RemoteNameTests(unittest.TestCase):
    """Имя уходит в строку «имя:путь» — двоеточие в нём её ломает."""

    def test_plain_names_accepted(self):
        for good in ("music", "yandex-1", "s3_cold"):
            self.assertTrue(rclonerc.valid_name(good), good)

    def test_broken_names_rejected(self):
        for bad in ("a:b", "with space", "", "a/b", "x" * 33, "имя"):
            self.assertFalse(rclonerc.valid_name(bad), bad)


class ParamsTests(unittest.TestCase):
    """В конфиг rclone уходит только то, что перечислено у вида."""

    def test_required_checked(self):
        params, reason = rclonerc.clean_params("webdav", {"url": "https://x"})
        self.assertEqual(params, {})
        self.assertIn("Логин", reason)

    def test_optional_skipped_when_empty(self):
        params, reason = rclonerc.clean_params(
            "webdav", {"url": "https://x", "user": "u", "pass": "p"})
        self.assertEqual(reason, "")
        self.assertNotIn("vendor", params)

    def test_unknown_fields_dropped(self):
        """Поле, которого нет у вида, не должно попасть в чужой конфиг."""
        params, reason = rclonerc.clean_params(
            "webdav",
            {"url": "https://x", "user": "u", "pass": "p",
             "secret_access_key": "чужое", "exec": "rm -rf /"},
        )
        self.assertEqual(reason, "")
        self.assertEqual(set(params), {"url", "user", "pass"})

    def test_unknown_kind_refused(self):
        params, reason = rclonerc.clean_params("нечто", {"x": "y"})
        self.assertEqual(params, {})
        self.assertIn("Неизвестный", reason)

    def test_every_kind_has_fields(self):
        for kind in rclonerc.KINDS:
            self.assertTrue(kind.fields, kind.key)
            self.assertTrue(kind.note, kind.key)


class InviteLinkTests(unittest.TestCase):
    """Ссылку задаёт суперадминистратор, но опечатка — не злой умысел."""

    def test_telegram_links_accepted(self):
        for good in ("https://t.me/joinchat/AAAA",
                     "https://t.me/+abcdef",
                     "https://t.me/mychat",
                     "https://telegram.me/mychat"):
            self.assertTrue(chatlink.valid_invite(good), good)

    def test_other_links_rejected(self):
        for bad in ("", "t.me/mychat", "https://example.com/t.me/x",
                    "javascript:alert(1)", "https://t.me/ a",
                    "https://t.me/" + "x" * 300):
            self.assertFalse(chatlink.valid_invite(bad), bad)

    def test_manual_link_wins_over_lookup(self):
        """Ручную ссылку задают там, где автоматика не годится, —
        значит, она должна идти первой, а не запасной."""
        async def manual(_chat_id):
            return "https://t.me/+secret"

        def explode(*_args, **_kwargs):
            raise AssertionError("к Telegram ходить не требовалось")

        with mock.patch.object(chatlink, "manual_link", manual):
            ok, value = run(chatlink.link_for(-100, bot=explode))

        self.assertTrue(ok)
        self.assertEqual(value, "https://t.me/+secret")

    def test_invalid_stored_link_ignored(self):
        """Битая запись в базе не должна стать кнопкой."""
        async def row(_chat_id):
            return {"chat_id": -100, "invite": "javascript:alert(1)"}

        with mock.patch("radar.db.repo.chat_get", row):
            self.assertEqual(run(chatlink.manual_link(-100)), "")


class AnnounceScreenTests(unittest.TestCase):
    """Экран подтверждения: показать ровно то, что уйдёт."""

    def setUp(self) -> None:
        self.draft = chatpost.Draft(chat_id=-1001, title="Двор",
                                    text="<b>Воду</b> дадут в 18:00")

    def test_preview_shows_text_and_target(self):
        page = panel._announce_preview("tok", self.draft)
        self.assertIn("<b>Воду</b> дадут в 18:00", page)
        self.assertIn("Двор", page)

    def test_preview_carries_chat_and_token(self):
        page = panel._announce_preview("tok", self.draft)
        self.assertIn('value="-1001"', page)
        self.assertIn('value="tok"', page)
        self.assertIn("/chats/send", page)
        self.assertIn("/chats/drop", page)

    def test_newlines_become_breaks(self):
        page = panel._announce_preview("tok", self.draft)
        self.assertNotIn(chr(10) + "Получатель", page)
        self.assertIn("<br>", page)

    def test_announce_form_lists_chats(self):
        form = panel._announce_form("tok", [
            {"chat_id": -1001, "title": "Двор"},
            {"chat_id": -1002, "title": ""},
        ])
        self.assertIn('value="-1001"', form)
        self.assertIn("Двор", form)
        # Чат без названия должен быть выбираем, а не пуст в списке.
        self.assertIn("-1002</option>", form)

    def test_announce_form_escapes_title(self):
        form = panel._announce_form("tok", [
            {"chat_id": -1, "title": '<script>alert(1)</script>'},
        ])
        self.assertNotIn("<script>alert(1)</script>", form)
        self.assertIn("&lt;script&gt;", form)


class RoutesTests(unittest.TestCase):
    """Новые адреса должны быть подключены, а не просто написаны."""

    def test_new_routes_registered(self):
        source = panel.__file__
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        for route in ("/cloud", "/cloud/add", "/cloud/forget",
                      "/chats/invite", "/chats/announce",
                      "/chats/send", "/chats/drop"):
            self.assertIn(f'"{route}"', text, route)


if __name__ == "__main__":
    unittest.main()
