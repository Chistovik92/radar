#!/usr/bin/env python3
"""Ядро музыки (4.9.5.2): треки, плейлисты, лимиты, ID3.

Хранилище — запись пользователя, файлы — data/music. Проверяется
логика без бота: что легло, что убралось, что осталось после удаления.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import music  # noqa: E402


class TestLimits(unittest.TestCase):
    def test_free_limit(self):
        self.assertEqual(music.track_limit({}, None), music.FREE_TRACKS)

    def test_admin_limit(self):
        # Служебный доступ администрации — как подписка
        self.assertEqual(music.track_limit({}, "admin"),
                         music.SUBSCRIBED_TRACKS)


class TestTracks(unittest.TestCase):
    def test_add_and_list(self):
        user = {}
        music.add_track(user, "abc", name="Песня", ext=".mp3", size=100)
        tracks = music.tracks_of(user)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["name"], "Песня")

    def test_remove_cleans_playlists(self):
        user = {}
        music.add_track(user, "abc", name="A", ext=".mp3", size=1)
        music.add_track(user, "def", name="B", ext=".mp3", size=1)
        music.create_playlist(user, "Дорога")
        music.toggle_in_playlist(user, "Дорога", "abc")
        music.toggle_in_playlist(user, "Дорога", "def")

        removed = music.remove_track(user, "abc")
        self.assertTrue(removed)
        self.assertEqual(len(music.tracks_of(user)), 1)
        # Ссылка на удалённый трек из плейлиста исчезла
        kept = music.playlist_tracks(user, "Дорога")
        self.assertEqual([t["id"] for t in kept], ["def"])

    def test_remove_missing(self):
        self.assertFalse(music.remove_track({}, "nope"))


class TestPlaylists(unittest.TestCase):
    def test_create_and_toggle(self):
        user = {}
        music.add_track(user, "abc", name="A", ext=".mp3", size=1)
        self.assertTrue(music.create_playlist(user, "Дорога"))
        self.assertIs(music.toggle_in_playlist(user, "Дорога", "abc"), True)
        self.assertIs(music.toggle_in_playlist(user, "Дорога", "abc"), False)

    def test_duplicate_name_rejected(self):
        user = {}
        music.create_playlist(user, "Дорога")
        self.assertFalse(music.create_playlist(user, "Дорога"))

    def test_toggle_missing_playlist(self):
        self.assertIsNone(music.toggle_in_playlist({}, "Нет", "abc"))


class TestSafeTitle(unittest.TestCase):
    def test_strips_unsafe(self):
        self.assertNotIn("/", music.safe_title("а/б\\в"))
        self.assertEqual(music.safe_title(""), "Без названия")

    def test_caps_length(self):
        self.assertLessEqual(len(music.safe_title("х" * 500)), music.MAX_TITLE)


class TestID3(unittest.TestCase):
    def test_no_tag(self):
        self.assertEqual(music.read_tags(b"no tags here"), {"artist": "", "title": ""})

    def test_reads_tpe1_tit2(self):
        # Минимальный ID3v2: заголовок + кадр TPE1 с латиницей (encoding 0)
        def frame(name: bytes, text: str) -> bytes:
            body = b"\x00" + text.encode("latin-1") + b"\x00"
            size = len(body).to_bytes(4, "big")
            return name + size + b"\x00\x00" + body

        data = (b"ID3\x03\x00\x00\x00\x00\x00\x0f"
                + frame(b"TPE1", "Artist X")
                + frame(b"TIT2", "Song Y"))
        tags = music.read_tags(data)
        self.assertEqual(tags["artist"], "Artist X")
        self.assertEqual(tags["title"], "Song Y")


if __name__ == "__main__":
    unittest.main(verbosity=2)
