#!/usr/bin/env python3
"""Соцмеханика музыкального каталога 6.0.0 — без сети и Telegram."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()


class _Observer:
    def __call__(self, *args, **kwargs):
        return lambda func: func

    def middleware(self, func):
        return func


stubcheck.Router.message = property(lambda self: _Observer())
stubcheck.Router.callback_query = property(lambda self: _Observer())

from radar import music, music_social as social, storage  # noqa: E402
from radar.handlers import music_search as search_handler  # noqa: E402
from radar.handlers import music_social as social_handler  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Base(unittest.TestCase):
    def setUp(self):
        self.meta = {
            "music_catalog": {
                "a": {"title": "Alpha", "artist": "One"},
                "b": {"title": "Beta", "artist": "Two"},
                "c": {"title": "Gamma", "artist": "Three"},
            }
        }

        async def get(key, default=None):
            value = self.meta.get(key, default)
            return value

        async def set_value(key, value):
            self.meta[key] = value

        self.patches = [
            mock.patch.object(storage, "meta_get", get),
            mock.patch.object(storage, "meta_set", set_value),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()


class Personal(Base):
    def test_saved_toggle_and_limit(self):
        user = {}
        self.assertTrue(music.toggle_saved(user, "a"))
        self.assertEqual(music.saved_tracks(user), ["a"])
        self.assertFalse(music.toggle_saved(user, "a"))
        self.assertEqual(music.saved_tracks(user), [])
        with mock.patch.object(music, "MAX_SAVED", 1):
            music.toggle_saved(user, "a")
            self.assertIsNone(music.toggle_saved(user, "b"))

    def test_history_recent_ttl_and_clear(self):
        user = {}
        now = int(time.time())
        social.record_history(user, "a", now=now - social.HISTORY_TTL - 1)
        social.record_history(user, "b", now=now)
        social.record_history(user, "a", now=now + 1)
        self.assertEqual([item["track_id"] for item in social.history_of(user, now=now + 1)],
                         ["a", "b"])
        self.assertTrue(social.remove_history(user, "b"))
        self.assertFalse(social.remove_history(user, "missing"))
        social.clear_history(user)
        self.assertEqual(social.history_of(user), [])

    def test_recent_queries_unique_and_bounded(self):
        user = {}
        for query in ["one", "two", "one", "three", "four", "five", "six"]:
            social.remember_query(user, query)
        self.assertEqual(social.recent_queries(user),
                         ["six", "five", "four", "three", "one"])

    def test_profile_visibility_and_about(self):
        user = {}
        social.set_profile(user, about="  Люблю <b>джаз</b>  ", hidden=True)
        self.assertEqual(social.profile(user)["about"], "Люблю <b>джаз</b>")
        self.assertTrue(social.profile(user)["hidden"])
        self.assertEqual(social.profile(user)["played"], 2 - 2)


class Reactions(Base):
    def test_like_dislike_are_mutually_exclusive(self):
        self.assertEqual(run(social.toggle_like("a", 1)), (True, 1, 0))
        self.assertEqual(run(social.toggle_dislike("a", 1)), (True, 0, 1))
        self.assertEqual(run(social.toggle_dislike("a", 1)), (False, 0, 0))
        self.assertEqual(run(social.reaction_counts("a")), (0, 0))

    def test_views_top_and_random(self):
        run(social.register_view("a"))
        run(social.register_view("a"))
        run(social.register_view("b"))
        top = run(social.top_tracks(limit=2))
        self.assertEqual([item["id"] for item in top], ["a", "b"])
        self.assertEqual(top[0]["views"], 2)
        self.assertIn(run(social.random_track())["id"], {"a", "b", "c"})


class Playlists(Base):
    def test_create_view_like_and_delete(self):
        created = run(social.create_public_playlist(42, "  Дорога  "))
        self.assertIsNotNone(created)
        playlist_id = created["id"]
        self.assertEqual(created["name"], "Дорога")
        self.assertTrue(created["is_public"])
        self.assertTrue(run(social.toggle_public_track(playlist_id, 42, "a")))
        viewed = run(social.public_playlist_view(playlist_id, 7))
        self.assertEqual(viewed["tracks"], ["a"])
        self.assertEqual(viewed["views"], 1)
        self.assertTrue(run(social.toggle_playlist_like(playlist_id, 7)))
        self.assertEqual(viewed["id"], playlist_id)
        self.assertFalse(run(social.delete_public_playlist(playlist_id, 7)))
        self.assertTrue(run(social.delete_public_playlist(playlist_id, 42)))
        self.assertIsNone(run(social.public_playlist_view(playlist_id, 42)))

    def test_only_owner_can_change_and_private_is_not_listed(self):
        created = run(social.create_public_playlist(1, "Private", is_public=False))
        playlist_id = created["id"]
        self.assertIsNone(run(social.toggle_public_track(playlist_id, 2, "a")))
        self.assertIsNone(run(social.public_playlist_view(playlist_id, 2)))
        self.assertIsNotNone(run(social.public_playlist_view(playlist_id, 1)))
        self.assertEqual(run(social.top_playlists()), [])

    def test_limits_and_top_order(self):
        first = run(social.create_public_playlist(1, "First"))
        second = run(social.create_public_playlist(2, "Second"))
        run(social.toggle_playlist_like(first["id"], 3))
        run(social.public_playlist_view(second["id"], 4))
        self.assertEqual(run(social.top_playlists())[0]["id"], first["id"])
        with mock.patch.object(social, "MAX_PLAYLIST_TRACKS", 1):
            self.assertTrue(run(social.toggle_public_track(first["id"], 1, "a")))
            self.assertIsNone(run(social.toggle_public_track(first["id"], 1, "b")))


class Handlers(Base):
    def test_social_feature_off_blocks_callback_and_clears_fsm(self):
        call = mock.Mock(data="mss:list")
        call.answer = mock.AsyncMock()
        state = mock.Mock()
        state.clear = mock.AsyncMock()
        next_handler = mock.AsyncMock()
        with mock.patch.object(social_handler.features, "enabled", return_value=False):
            result = run(social_handler._feature_guard(next_handler, call, {"state": state}))
        self.assertIsNone(result)
        next_handler.assert_not_awaited()
        state.clear.assert_awaited_once()
        call.answer.assert_awaited_once()

    def test_social_exit_cancels_pending_form(self):
        call = mock.Mock(data="mss:profile")
        state = mock.Mock()
        state.clear = mock.AsyncMock()
        next_handler = mock.AsyncMock(return_value="ok")
        with mock.patch.object(social_handler.features, "enabled", return_value=True):
            result = run(social_handler._feature_guard(next_handler, call, {"state": state}))
        self.assertEqual(result, "ok")
        state.clear.assert_awaited_once()
        next_handler.assert_awaited_once()

    def test_inline_unregistered_gets_empty_answer(self):
        query = mock.Mock(query="track:a")
        query.from_user.id = 7
        query.answer = mock.AsyncMock()
        with (mock.patch.object(search_handler, "_enabled", return_value=True),
              mock.patch.object(search_handler.storage, "get_user", return_value=None)):
            run(search_handler.inline_search(query))
        self.assertEqual(query.answer.await_args.args[0], [])

    def test_inline_track_payload_returns_exact_track(self):
        query = mock.Mock(query="track:a")
        query.from_user.id = 7
        query.answer = mock.AsyncMock()

        async def catalog(track_id):
            return {"title": "Alpha", "artist": "One"} if track_id == "a" else {}

        async def no_file(track_id):
            return ""

        with (mock.patch.object(search_handler, "_enabled", return_value=True),
              mock.patch.object(search_handler.storage, "get_user", return_value={"id": "7"}),
              mock.patch.object(search_handler.musicsearch, "catalog_get", catalog),
              mock.patch.object(search_handler.musicsearch, "file_id_get", no_file),
              mock.patch.object(search_handler, "InlineQueryResultArticle", lambda **kw: kw),
              mock.patch.object(search_handler, "InputTextMessageContent", lambda **kw: kw)):
            run(search_handler.inline_search(query))
        results = query.answer.await_args.args[0]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "a")
        self.assertEqual(results[0]["reply_markup"].inline_keyboard[0][0].callback_data,
                         "msc:play:a")

    def test_share_track_keyboard_uses_exact_id_payload(self):
        async def state(track_id, uid):
            return {"likes": 0, "dislikes": 0, "views": 0, "liked": 0, "disliked": 0}

        with (mock.patch.object(social, "reaction_state", state),
              mock.patch.object(search_handler.music, "saved_tracks", return_value=[]),
              mock.patch.object(search_handler.music, "find_by_source", return_value=None),
              mock.patch.object(search_handler.music, "playlists_of", return_value=[]),
              mock.patch.object(search_handler.subscription, "active", return_value=False)):
            markup = run(search_handler.track_kb("a", {}))
        # Без подписки и «слушать следующий» раскладка: «слушать», реакции,
        # [сохранить, в плейлист], «поделиться», «назад». Кнопка «поделиться» —
        # отдельной строкой (индекс 3 после добавленной строки «▶️ Слушать»).
        self.assertEqual(markup.inline_keyboard[3][0].switch_inline_query, "track:a")

    def test_webm_is_sent_as_document_with_real_extension(self):
        call = mock.Mock(message=None)
        call.from_user.id = 7
        call.answer = mock.AsyncMock()
        progress = mock.Mock()
        progress.edit_text = mock.AsyncMock()
        progress.delete = mock.AsyncMock()
        call.bot.send_message = mock.AsyncMock(return_value=progress)
        call.bot.send_audio = mock.AsyncMock()
        call.bot.send_document = mock.AsyncMock(return_value=mock.Mock(audio=None))

        async def catalog(track_id):
            return {"title": "Alpha", "artist": "One", "duration": 120}

        async def no_file(track_id):
            return ""

        async def no_save(*args):
            return None

        client = mock.Mock()
        client.download_track = mock.AsyncMock(
            return_value=search_handler.musicsearch.AudioBuffer(b"webm", "webm")
        )
        with (mock.patch.object(search_handler, "_enabled", return_value=True),
              mock.patch.object(search_handler.musicsearch, "catalog_get", catalog),
              mock.patch.object(search_handler.musicsearch, "file_id_get", no_file),
              mock.patch.object(search_handler.musicsearch, "MusicSearchClient", return_value=client),
              mock.patch.object(search_handler, "BufferedInputFile",
                                lambda data, filename: {"filename": filename}),
              mock.patch.object(search_handler.storage, "save", no_save),
              mock.patch.object(social, "register_view", no_save)):
            run(search_handler.send_track(call, {}, "a"))
        call.bot.send_audio.assert_not_awaited()
        payload = call.bot.send_document.await_args.args[1]
        self.assertEqual(payload["filename"], "One — Alpha.webm")

    def test_inline_playlist_without_message_sends_new_message(self):
        call = mock.Mock(data="mss:pl:abc", message=None)
        call.from_user.id = 7
        call.answer = mock.AsyncMock()
        call.bot.send_message = mock.AsyncMock()

        async def view(playlist_id, uid):
            return {"id": "abc", "name": "List", "founder_id": "7", "tracks": ["a"],
                    "likes": 0, "views": 0}

        async def catalog(track_id):
            return {"title": "Alpha", "artist": "One"}

        with (mock.patch.object(social_handler.social, "public_playlist_view", view),
              mock.patch.object(social_handler.musicsearch, "catalog_get", catalog),
              mock.patch.object(social_handler, "safe_edit", mock.AsyncMock()) as edit):
            run(social_handler.playlist(call))
        edit.assert_not_awaited()
        call.bot.send_message.assert_awaited_once()
        markup = call.bot.send_message.await_args.kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "msc:play:a")

    def test_playlist_like_rerenders_track_buttons(self):
        call = mock.Mock(data="mss:pllike:abc")
        call.from_user.id = 7
        call.answer = mock.AsyncMock()

        async def toggle(playlist_id, uid):
            return True

        async def view(playlist_id, uid, count_view=False):
            return {"id": "abc", "name": "List", "founder_id": "7", "tracks": ["a"],
                    "likes": 1, "views": 2}

        async def catalog(track_id):
            return {"title": "Alpha", "artist": "One"}

        render = mock.AsyncMock()
        with (mock.patch.object(social_handler.social, "toggle_playlist_like", toggle),
              mock.patch.object(social_handler.social, "public_playlist_view", view),
              mock.patch.object(social_handler.musicsearch, "catalog_get", catalog),
              mock.patch.object(social_handler, "_edit_or_send", render)):
            run(social_handler.playlist_like(call))
        markup = render.await_args.args[2]
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "msc:play:a")
        self.assertIn("Alpha", render.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
