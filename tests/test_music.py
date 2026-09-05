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
        self.assertEqual(music.read_tags(b"no tags here"),
                         {"artist": "", "title": "", "genre": ""})

    def test_reads_tpe1_tit2(self):
        # Минимальный ID3v2: заголовок + кадр TPE1 с латиницей (encoding 0)
        def frame(name: bytes, text: str) -> bytes:
            body = b"\x00" + text.encode("latin-1") + b"\x00"
            size = len(body).to_bytes(4, "big")
            return name + size + b"\x00\x00" + body

        data = (b"ID3\x03\x00\x00\x00\x00\x00\x0f"
                + frame(b"TPE1", "Artist X")
                + frame(b"TIT2", "Song Y")
                + frame(b"TCON", "Rock"))
        tags = music.read_tags(data)
        self.assertEqual(tags["artist"], "Artist X")
        self.assertEqual(tags["title"], "Song Y")
        self.assertEqual(tags["genre"], "Rock")


class TestSimilar(unittest.TestCase):
    """Подбор похожего по тегам — без сети, только своё."""

    def _filled(self) -> dict:
        user = {}
        music.add_track(user, "a", name="A", ext=".mp3", size=1,
                        artist="Кино", title="Группа крови", genre="Rock")
        music.add_track(user, "b", name="B", ext=".mp3", size=1,
                        artist="Кино", title="Звезда", genre="Rock")
        music.add_track(user, "c", name="C", ext=".mp3", size=1,
                        artist="Наутилус", title="Скованные", genre="Rock")
        music.add_track(user, "d", name="D", ext=".mp3", size=1,
                        artist="Моцарт", title="Реквием", genre="Classic")
        return user

    def test_same_artist_first(self):
        user = self._filled()
        found = music.similar(user, "a")
        self.assertTrue(found)
        # Тот же артист — выше, чем просто жанр
        self.assertEqual(found[0]["id"], "b")

    def test_genre_matches_too(self):
        user = self._filled()
        found = music.similar(user, "a")
        ids = [t["id"] for t in found]
        self.assertIn("c", ids)      # жанр Rock
        self.assertNotIn("d", ids)   # Classic — мимо

    def test_no_tags_no_similar(self):
        user = {}
        music.add_track(user, "a", name="A", ext=".mp3", size=1)
        music.add_track(user, "b", name="B", ext=".mp3", size=1)
        self.assertEqual(music.similar(user, "a"), [])

    def test_limit(self):
        user = self._filled()
        found = music.similar(user, "a", limit=1)
        self.assertEqual(len(found), 1)

    def test_missing_base(self):
        self.assertEqual(music.similar({}, "nope"), [])


class TestShuffle(unittest.TestCase):
    def test_shuffle_keeps_all_tracks(self):
        user = {}
        for tid, artist in (("a", "X"), ("b", "Y"), ("c", "Z"), ("d", "Q")):
            music.add_track(user, tid, name=tid, ext=".mp3", size=1,
                            artist=artist)
        music.create_playlist(user, "Дорога")
        for tid in ("a", "b", "c", "d"):
            music.toggle_in_playlist(user, "Дорога", tid)

        order = music.shuffle_playlist(user, "Дорога")
        self.assertEqual(len(order), 4)
        # Состав не теряется: те же треки, возможно в другом порядке
        self.assertEqual({t["id"] for t in order}, {"a", "b", "c", "d"})
        # Новый порядок записан в плейлист
        stored = music.playlist_tracks(user, "Дорога")
        self.assertEqual([t["id"] for t in stored],
                         [t["id"] for t in order])

    def test_shuffle_empty(self):
        self.assertEqual(music.shuffle_playlist({}, "Нет"), [])

    def test_seed_reproducible(self):
        user = {}
        for tid in ("a", "b", "c", "d", "e"):
            music.add_track(user, tid, name=tid, ext=".mp3", size=1)
        music.create_playlist(user, "P")
        for tid in ("a", "b", "c", "d", "e"):
            music.toggle_in_playlist(user, "P", tid)

        first = [t["id"] for t in music.shuffle_playlist(user, "P", seed="x")]
        second = [t["id"] for t in music.shuffle_playlist(user, "P", seed="x")]
        self.assertEqual(first, second)


class TestCompress(unittest.TestCase):
    """Пережатие: битрейт честен к исходнику и не жаден."""

    def test_bitrate_capped_at_music(self):
        """FLAC 900 kbps → музыкальный потолок 96: выше незачем."""
        # 10 МБ на 90 секунд ≈ 888 kbps
        size = 10 * 1024 * 1024
        self.assertEqual(music.compress_bitrate_k(size, 90),
                         music.MUSIC_BITRATE_K)

    def test_bitrate_not_above_source(self):
        """Тихий mp3 ~64 kbps не разгоняется до потолка."""
        size = 720 * 1024          # 90 секунд при ~64,5 kbps
        self.assertLessEqual(music.compress_bitrate_k(size, 90), 66)
        self.assertGreater(music.compress_bitrate_k(size, 90),
                           music.VOICE_BITRATE_K)

    def test_bitrate_floor_is_voice(self):
        """Ниже голосового порога не опускаемся."""
        self.assertEqual(music.compress_bitrate_k(1, 1000),
                         music.VOICE_BITRATE_K)

    def test_no_duration_uses_music(self):
        self.assertEqual(music.compress_bitrate_k(0, 0),
                         music.MUSIC_BITRATE_K)

    def test_worth_compress(self):
        self.assertFalse(music.worth_compress(1024))
        self.assertTrue(music.worth_compress(music.COMPRESS_MIN_MB * 1024 * 1024))


class TestDiskReport(unittest.TestCase):
    """Сводка по дискам: точки считаются, повторы схлопываются."""

    def test_report_has_current_disk(self):
        report = music.disk_report(["."])
        self.assertIn("Диски", report)
        self.assertIn("%", report)

    def test_duplicates_collapsed(self):
        # Один и тот же диск дважды — одна строка
        one = music.disk_report(["."]).count("•")
        two = music.disk_report([".", "."]).count("•")
        self.assertEqual(one, two)

    def test_missing_path_skipped(self):
        report = music.disk_report(["Z:/нет/такого/пути", "."])
        self.assertIn("Диски", report)

    def test_warn_threshold_flag(self):
        # Порог, при котором появляется предупреждение
        self.assertGreater(music.DISK_WARN_PERCENT, 50)
        self.assertLess(music.DISK_WARN_PERCENT, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
