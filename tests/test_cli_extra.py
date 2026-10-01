#!/usr/bin/env python3
"""Консоль: проверка ссылок, cookies, история, события, музыка, облако,
чаты и короткие ссылки (с 5.9.10) — и итог паритета.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace as NS
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import (chatlink, cli, cookies, features, music, rclonerc, shortener,  # noqa: E402
                   storage)
from radar.db import repo  # noqa: E402
from test_cli_ops import Store  # noqa: E402


def run(argv, in_bot=False):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        if in_bot:
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()
            cli.attach(loop)
            try:
                code = cli.main(["--local", "--lang", "en"] + argv)
            finally:
                cli.attach(None)
                loop.call_soon_threadsafe(loop.stop)
                thread.join(2)
                loop.close()
        else:
            code = cli.main(["--local", "--lang", "en"] + argv)
    return code, out.getvalue(), err.getvalue()


def done(value):
    async def coro(*a, **k):
        return value
    return coro


class Check(unittest.TestCase):
    def test_address_analysis_without_network(self):
        with Store():
            code, out, _ = run(["check", "https://example.com/page", "--no-net", "--json"])
        self.assertEqual(code, cli.OK)
        data = json.loads(out)
        self.assertIn("score", data)
        self.assertNotIn("<b>", data["report"])                  # разметка Telegram убрана

    def test_lookalike_scores_higher_than_plain(self):
        with Store():
            plain = json.loads(run(["check", "https://example.com/", "--no-net", "--json"])[1])
            fake = json.loads(run(["check", "http://paypa1-secure-login.xyz/verify?acc=1",
                                   "--no-net", "--json"])[1])
        self.assertGreater(fake["score"], plain["score"])


class Cookies(unittest.TestCase):
    def test_status(self):
        with Store(), mock.patch.object(cookies, "describe", lambda: "Cookies не подключены."), \
                mock.patch.object(cookies, "connected", lambda: False):
            code, out, _ = run(["cookies", "status", "--json"])
        self.assertEqual(code, cli.OK)
        self.assertFalse(json.loads(out)["connected"])

    def test_set_validates_through_the_shared_store(self):
        stored = []
        with tempfile.TemporaryDirectory() as tmp, Store():
            path = os.path.join(tmp, "c.txt")
            with open(path, "wb") as handle:
                handle.write(b"# Netscape HTTP Cookie File\n")
            with mock.patch.object(cookies, "store", lambda data: (stored.append(data) or True, "")):
                self.assertEqual(run(["cookies", "set", path])[0], cli.OK)
            with mock.patch.object(cookies, "store", lambda data: (False, "файл пуст")):
                code, _o, err = run(["cookies", "set", path])
            self.assertEqual(code, cli.FAILED)
            self.assertIn("файл пуст", err)
            self.assertEqual(run(["cookies", "set"])[0], cli.FAILED)
            self.assertEqual(run(["cookies", "set", os.path.join(tmp, "missing")])[0], cli.FAILED)
        self.assertEqual(stored, [b"# Netscape HTTP Cookie File\n"])


class History(unittest.TestCase):
    def test_history_and_events(self):
        from datetime import datetime

        event = NS(created_at=datetime(2026, 10, 1, 12, 30), categories=["bpla"], summary=" Тревога ")
        with Store(), mock.patch.object(repo, "history", done([event])), \
                mock.patch.object(repo, "event_stats", done({"events": 4, "deliveries": 9})):
            code, out, _ = run(["history", "7", "--json"])
            rows = json.loads(out)
            self.assertEqual((code, rows[0]["summary"], rows[0]["categories"]), (cli.OK, "Тревога", ["bpla"]))
            code, out, _ = run(["events", "--days", "3", "--json"])
            self.assertEqual(json.loads(out), {"events": 4, "deliveries": 9})

    def test_empty_history_says_so(self):
        with Store(), mock.patch.object(repo, "history", done([])):
            code, out, _ = run(["history", "7"])
        self.assertEqual(code, cli.OK)
        self.assertIn("Nothing was sent", out)


class Music(unittest.TestCase):
    def people(self):
        track = {"id": "t1", "name": "Song", "size": 2048}
        return {"1": {"username": "bob", "music": {"tracks": [track]}}, "2": {"username": "x"}}

    def test_usage_and_list(self):
        people = self.people()
        with Store(people), mock.patch.object(music, "tracks_of",
                                               lambda user: (user.get("music") or {}).get("tracks", [])), \
                mock.patch.object(music, "playlists_of", lambda user: []), \
                mock.patch.object(music, "cache_size", lambda: 1024):
            code, out, _ = run(["music", "usage", "--json"])
            data = json.loads(out)
            self.assertEqual((data["tracks"], data["bytes"], data["cache_bytes"]), (1, 2048, 1024))
            self.assertEqual([p["uid"] for p in data["people"]], ["1"])
            code, out, _ = run(["music", "list", "1", "--json"])
            self.assertEqual(json.loads(out)[0]["name"], "Song")
            self.assertEqual(run(["music", "list", "404"])[0], cli.FAILED)
            self.assertEqual(run(["music", "list"])[0], cli.FAILED)


class Cloud(unittest.TestCase):
    def test_list_add_forget(self):
        created, forgotten = [], []

        async def create(name, kind, values):
            created.append((name, kind, values))
            return (name != "bad"), "не вышло"

        async def forget(name):
            forgotten.append(name)
            return True, ""

        with Store(), mock.patch.object(rclonerc, "remotes", done((True, ["yandex", "s3"]))), \
                mock.patch.object(rclonerc, "create", create), mock.patch.object(rclonerc, "forget", forget), \
                mock.patch.object(rclonerc, "check", done((True, "готово"))):
            code, out, _ = run(["cloud", "list", "--json"])
            self.assertEqual(json.loads(out), ["yandex", "s3"])
            self.assertEqual(run(["cloud", "add", "yd", "webdav", "--set", "url=https://x",
                                  "--set", "user=u"])[0], cli.OK)
            self.assertEqual(created[0], ("yd", "webdav", {"url": "https://x", "user": "u"}))
            self.assertEqual(run(["cloud", "add", "bad", "webdav"])[0], cli.FAILED)
            self.assertEqual(run(["cloud", "add", "x"])[0], cli.FAILED)
            self.assertEqual(run(["cloud", "forget", "yd"])[0], cli.NEEDS_YES)
            self.assertEqual(forgotten, [])
            self.assertEqual(run(["cloud", "forget", "yd", "--yes"])[0], cli.OK)
            self.assertEqual(run(["cloud", "check"])[0], cli.OK)

    def test_list_failure_is_reported(self):
        with Store(), mock.patch.object(rclonerc, "remotes", done((False, "rclone недоступен"))):
            code, _o, err = run(["cloud", "list"])
        self.assertEqual(code, cli.FAILED)
        self.assertIn("rclone", err)


class Chats(unittest.TestCase):
    def test_invite_link(self):
        saved = []

        async def set_invite(chat, link):
            saved.append((chat, link))
            return chat != 404

        with Store(), mock.patch.object(repo, "chat_set_invite", set_invite), \
                mock.patch.object(chatlink, "refresh_published", done(1)), \
                mock.patch.object(chatlink, "forget", lambda chat: None):
            self.assertEqual(run(["chats", "invite", "-100", "https://t.me/+abc"])[0], cli.OK)
            self.assertEqual(run(["chats", "invite", "-100"])[0], cli.OK)                  # снять
            self.assertEqual(run(["chats", "invite", "-100", "http://evil.example"])[0], cli.FAILED)
            self.assertEqual(run(["chats", "invite", "404", "https://t.me/+abc"])[0], cli.FAILED)
        self.assertEqual(saved[:2], [(-100, "https://t.me/+abc"), (-100, "")])

    def test_warns_counter_and_reset(self):
        resets = []

        async def reset(chat, user):
            resets.append((chat, user))

        with Store(), mock.patch.object(repo, "warn_count", done(2)), \
                mock.patch.object(repo, "warn_reset", reset):
            code, out, _ = run(["chats", "warns", "-100", "55", "--json"])
            self.assertEqual(json.loads(out)["warnings"], 2)
            self.assertEqual(run(["chats", "warns", "-100", "55", "--reset"])[0], cli.OK)
            self.assertEqual(run(["chats", "warns", "-100"])[0], cli.FAILED)
        self.assertEqual(resets, [(-100, 55)])

    def announce(self, argv, enabled=True, in_bot=True, row=True):
        sent = []

        async def send_message(chat, text):
            sent.append((chat, text))

        from radar import tg

        was = features.enabled("chat_post")
        features.set_local("chat_post", enabled)
        try:
            with Store(), mock.patch.object(repo, "chat_get",
                                            done({"title": "Дом"} if row else None)), \
                    mock.patch.object(tg, "bot", NS(send_message=send_message)):
                result = run(argv, in_bot=in_bot)
        finally:
            features.set_local("chat_post", was)
        return result, sent

    def test_announce_previews_without_yes(self):
        (code, out, err), sent = self.announce(["chats", "announce", "-100", "Всем привет"])
        self.assertEqual(code, cli.NEEDS_YES)
        self.assertEqual(sent, [])
        self.assertIn("Всем привет", out)                    # текст показан, как в панели

    def test_announce_sends_with_yes_inside_bot(self):
        (code, out, _), sent = self.announce(["chats", "announce", "-100", "Всем", "привет", "--yes"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(sent, [(-100, "Всем привет")])

    def test_announce_guards(self):
        (code, _o, err), sent = self.announce(["chats", "announce", "-100", "x", "--yes"], enabled=False)
        self.assertEqual((code, sent), (cli.FAILED, []))
        (code, _o, err), sent = self.announce(["chats", "announce", "-100", "x", "--yes"], in_bot=False)
        self.assertEqual((code, sent), (cli.FAILED, []))
        self.assertIn("bot", err)
        (code, _o, _e), sent = self.announce(["chats", "announce", "-100", "x", "--yes"], row=False)
        self.assertEqual((code, sent), (cli.FAILED, []))
        (code, _o, _e), sent = self.announce(["chats", "announce", "-100", "--yes"])
        self.assertEqual((code, sent), (cli.FAILED, []))                 # пустой текст


class Shorts(unittest.TestCase):
    def test_add_uses_the_shared_code_and_url(self):
        saved = []

        async def save(code, url, by):
            saved.append((code, url, by))

        with Store(), mock.patch.object(shortener, "enabled", lambda: True), \
                mock.patch.object(repo, "save_short_link", save):
            code, out, _ = run(["links", "add", "https://example.org/a", "--json"])
            data = json.loads(out)
            self.assertEqual(code, cli.OK)
            self.assertEqual(data["code"], shortener.code_for("https://example.org/a"))
            self.assertEqual(saved[0][1], "https://example.org/a")
            self.assertEqual(run(["links", "add", "notaurl"])[0], cli.FAILED)
        with Store(), mock.patch.object(shortener, "enabled", lambda: False):
            self.assertEqual(run(["links", "add", "https://example.org/a"])[0], cli.FAILED)


class Parity(unittest.TestCase):
    def test_nothing_is_left_pending(self):
        import lint_cli_parity

        table = {**lint_cli_parity.BOT, **lint_cli_parity.PANEL}
        pending = [k for k, v in table.items() if v.startswith("pending:")]
        self.assertEqual(pending, [])

    def test_exclusions_have_reasons(self):
        import lint_cli_parity

        for key, value in {**lint_cli_parity.BOT, **lint_cli_parity.PANEL}.items():
            if value.startswith("na:"):
                with self.subTest(key=key):
                    self.assertGreater(len(value), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
