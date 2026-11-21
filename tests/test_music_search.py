#!/usr/bin/env python3
"""Офлайн-проверки движка внешнего музыкального каталога (6.0.0).

Сеть и yt-dlp здесь не вызываются: проверяются выбор аудиодорожки, отсев
премиум-превью, оценка YouTube-кандидатов, пагинация и merge кэша метаданных.
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

from radar import musicsearch as ms  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class AudioSelection(unittest.TestCase):
    def test_prefers_compatible_high_bitrate(self):
        formats = [
            {"format_id": "139", "ext": "m4a", "abr": 48, "url": "https://cdn/48",
             "protocol": "https", "vcodec": "none"},
            {"format_id": "140", "ext": "m4a", "abr": 128, "url": "https://cdn/128",
             "protocol": "https", "vcodec": "none"},
            {"format_id": "251", "ext": "webm", "abr": 160, "url": "https://cdn/160",
             "protocol": "https", "vcodec": "none"},
        ]
        self.assertEqual(ms._pick_best_audio(formats)["format_id"], "140")

    def test_uses_other_codec_when_it_is_much_better(self):
        formats = [
            {"ext": "m4a", "abr": 48, "url": "https://cdn/48", "protocol": "https"},
            {"ext": "webm", "abr": 160, "url": "https://cdn/160", "protocol": "https"},
        ]
        self.assertEqual(ms._pick_best_audio(formats)["ext"], "webm")

    def test_rejects_video_drm_preview_and_bad_protocols(self):
        rejected = [
            {"ext": "mp4", "url": "https://cdn/video", "protocol": "https", "vcodec": "avc1"},
            {"ext": "m4a", "url": "https://cdn/drm", "protocol": "https", "has_drm": True},
            {"ext": "m4a", "url": "https://cdn/preview", "protocol": "https",
             "format_id": "hls-preview"},
            {"ext": "mhtml", "url": "https://cdn/story", "protocol": "https"},
            {"ext": "m4a", "url": "file:///etc/passwd", "protocol": "file"},
            {"ext": "m4a", "protocol": "https"},
            None,
        ]
        self.assertIsNone(ms._pick_best_audio(rejected))

    def test_hls_is_allowed_for_soundcloud_but_can_be_disabled(self):
        hls = {"ext": "mp3", "abr": 128, "url": "https://cdn/list.m3u8",
               "protocol": "m3u8_native", "format_id": "hls_mp3_1_0"}
        self.assertIs(ms._pick_best_audio([hls]), hls)
        self.assertIsNone(ms._pick_best_audio([hls], allow_hls=False))


class CandidatesAndText(unittest.TestCase):
    def test_candidate_score_uses_words_duration_and_version_penalty(self):
        original = {"title": "Queen — Bohemian Rhapsody", "duration": 355}
        remix = {"title": "Queen — Bohemian Rhapsody slowed remix", "duration": 355}
        other = {"title": "Unrelated", "duration": 100}
        query = "Queen Bohemian Rhapsody"
        self.assertGreater(ms.score_candidate(query, original, 354),
                           ms.score_candidate(query, remix, 354))
        self.assertGreater(ms.score_candidate(query, remix, 354),
                           ms.score_candidate(query, other, 354))

    def test_explicit_remix_request_is_not_penalized(self):
        candidate = {"title": "Artist — Song remix", "duration": 200}
        plain = ms.score_candidate("Artist Song", candidate, 200)
        wanted = ms.score_candidate("Artist Song remix", candidate, 200)
        self.assertGreater(wanted, plain)

    def test_progress_bar_is_bounded_and_html_safe(self):
        self.assertIn("100%", ms.format_progress_bar(20, 10))
        self.assertIn("0.0 MB", ms.format_progress_bar(0, 0))
        reporter = ms.TelegramProgressReporter(lambda text: None, title="<Rock> & Roll")
        self.assertIn("&lt;Rock&gt; &amp; Roll", reporter.render(1, 2))

    def test_track_display_name(self):
        self.assertEqual(ms.track_display_name(" - Queen- ", " — Song— "), "Queen — Song")
        self.assertEqual(ms.track_display_name("Song", "song"), "Song")
        self.assertEqual(ms.track_display_name("", ""), "")

    def test_content_range(self):
        self.assertEqual(ms.parse_content_range("bytes 0-1023/4096"), (0, 1023, 4096))
        self.assertEqual(ms.parse_content_range("bytes 5-9/*"), (5, 9, 0))
        self.assertEqual(ms.parse_content_range("broken"), (0, 0, 0))


class PremiumFilter(unittest.TestCase):
    def test_playable_transcoding(self):
        self.assertTrue(ms._is_playable_transcoding({
            "format": {"protocol": "hls"}, "url": "https://cdn/full"}))
        for value in (
            {"format": {"protocol": "ctr-hls"}, "url": "https://cdn/x"},
            {"format": {"protocol": "hls"}, "url": "https://cdn/encrypted-hls/x"},
            {"format": {"protocol": "hls"}, "url": "https://cdn/preview/x"},
            {"format": {"protocol": "hls"}, "url": "https://cdn/x", "snipped": True},
            {},
        ):
            self.assertFalse(ms._is_playable_transcoding(value))

    def test_premium_states(self):
        self.assertFalse(ms.is_premium_track(None))
        self.assertFalse(ms.is_premium_track({"policy": "ALLOW", "streamable": True}))
        for state in (
            {"policy": "SNIP"}, {"streamable": False}, {"state": "processing"},
            {"monetization_model": "SUB_HIGH_TIER"},
            {"media": {"transcodings": [{"format": {"protocol": "cbc-hls"},
                                         "url": "https://cdn/encrypted-hls/x"}]}},
        ):
            self.assertTrue(ms.is_premium_track(state))


class CacheMerge(unittest.TestCase):
    def test_merge_is_non_destructive_and_keeps_unknown_records(self):
        stored = {"old": {"title": "Old", "plays": 2}, "same": {"title": "Old", "artist": "A"}}
        incoming = {"same": {"title": "New"}, "new": {"title": "N"}}
        merged = ms.merge_cached_records(stored, incoming)
        self.assertEqual(set(merged), {"old", "same", "new"})
        self.assertEqual(merged["same"], {"title": "New", "artist": "A"})
        self.assertEqual(stored["same"], {"title": "Old", "artist": "A"})
        self.assertIsNot(merged["old"], stored["old"])

    def test_invalid_cache_records_are_ignored(self):
        self.assertEqual(ms.merge_cached_records(None, {"x": "bad", "y": {"title": "Y"}}),
                         {"y": {"title": "Y"}})


class MetaCache(unittest.TestCase):
    def setUp(self):
        from radar import storage

        self.values = {}

        async def get(key, default=None):
            return self.values.get(key, default)

        async def set_value(key, value):
            self.values[key] = value

        self.patches = [
            mock.patch.object(storage, "meta_get", get),
            mock.patch.object(storage, "meta_set", set_value),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def test_catalog_merge_preserves_unknown_and_nonempty_metadata(self):
        self.values["music_catalog"] = {
            "known": {"title": "Old", "artist": "Artist", "url": "https://old"},
            "untouched": {"title": "Keep"},
        }
        saved = run(ms.catalog_merge([
            {"id": "known", "title": "New", "artist": "", "cover": "https://cover"},
            {"id": "new", "title": "Track", "duration": 123},
            {"title": "without id"},
        ]))
        self.assertEqual(saved["known"]["title"], "New")
        self.assertEqual(saved["known"]["artist"], "Artist")
        self.assertEqual(saved["known"]["url"], "https://old")
        self.assertEqual(saved["known"]["cover"], "https://cover")
        self.assertIn("untouched", saved)
        self.assertEqual(run(ms.catalog_get("new"))["duration"], 123)
        self.assertEqual(run(ms.catalog_get("missing")), {})

    def test_file_id_cache_set_get_and_forget(self):
        self.assertEqual(run(ms.file_id_get("42")), "")
        run(ms.file_id_set("42", "telegram-file"))
        self.assertEqual(run(ms.file_id_get("42")), "telegram-file")
        run(ms.file_id_set("42", "   "))
        self.assertEqual(run(ms.file_id_get("42")), "telegram-file")
        run(ms.file_id_forget("42"))
        self.assertEqual(run(ms.file_id_get("42")), "")
        self.assertNotIn("42", self.values["music_files"])

    def test_file_id_set_preserves_legacy_dict_records(self):
        self.values["music_files"] = {
            "old": {"file_id": "document-id", "kind": "document"},
            "plain": "audio-id",
        }
        run(ms.file_id_set("new", "new-id"))
        self.assertEqual(self.values["music_files"]["old"],
                         {"file_id": "document-id", "kind": "document"})
        self.assertEqual(self.values["music_files"]["plain"], "audio-id")
        self.assertEqual(run(ms.file_id_get("old")), "document-id")
        run(ms.file_id_set("old", "updated-id"))
        self.assertEqual(self.values["music_files"]["old"],
                         {"file_id": "updated-id", "kind": "document"})


class ClientOffline(unittest.TestCase):
    def setUp(self):
        ms._search_cache.clear()

    def test_search_filters_and_fills_from_youtube(self):
        client = ms.MusicSearchClient(search_limit=2)
        sc_entries = [
            {"id": "soundcloud:tracks:10", "title": "Full", "uploader": "Artist",
             "duration": 200, "webpage_url": "https://soundcloud.com/a/full"},
            {"id": "11", "title": "preview", "duration": 30},
        ]

        async def sc(query, total):
            return sc_entries

        async def yt(query, limit):
            return [{"id": "abc", "title": "Second", "uploader": "YT Artist",
                     "duration": 180}]

        client._sc_search_entries = sc
        client._yt_search_entries = yt
        client._drop_premium = lambda entries: _return(entries)
        result = run(client.search_track("Artist Full"))
        self.assertEqual([item["id"] for item in result["items"]], ["10", "yt_abc"])
        self.assertEqual(result["items"][0]["query_str"], "Artist - Full")
        self.assertEqual(result["paginationInfo"]["lastPage"], 1)

    def test_mixed_pagination_has_no_duplicates_or_false_next_page(self):
        client = ms.MusicSearchClient(search_limit=2)

        async def sc(query, total):
            return [{"id": "sc1", "title": "SC", "duration": 200}]

        async def yt(query, limit):
            return [{"id": str(number), "title": f"YT {number}", "duration": 180}
                    for number in range(1, 5)]

        client._sc_search_entries = sc
        client._yt_search_entries = yt
        client._drop_premium = lambda entries: _return(entries)
        first = run(client.search_track("mix", page=1))
        second = run(client.search_track("mix", page=2))
        third = run(client.search_track("mix", page=3))
        self.assertEqual([item["id"] for item in first["items"]], ["sc1", "yt_1"])
        self.assertEqual([item["id"] for item in second["items"]], ["yt_2", "yt_3"])
        self.assertEqual([item["id"] for item in third["items"]], ["yt_4"])
        self.assertEqual(third["paginationInfo"]["lastPage"], 3)

    def test_exact_full_page_without_extra_item_has_no_next(self):
        client = ms.MusicSearchClient(search_limit=2)

        async def sc(query, total):
            return [{"id": "sc1", "title": "SC", "duration": 200}]

        async def yt(query, limit):
            return [{"id": "yt1", "title": "YT", "duration": 180}]

        client._sc_search_entries = sc
        client._yt_search_entries = yt
        client._drop_premium = lambda entries: _return(entries)
        result = run(client.search_track("short"))
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["paginationInfo"]["lastPage"], 1)

    def test_direct_network_error_falls_back_to_ytdlp(self):
        client = ms.MusicSearchClient()

        async def info(track_id):
            return {"download": "https://cdn/audio", "direct": True, "ext": "m4a"}

        async def network(*args, **kwargs):
            raise TimeoutError("network timeout")

        async def fallback(track_info, progress_cb):
            return ms.AudioBuffer(b"audio", "m4a")

        client.get_track_info = info
        client._stream_to_buffer = network
        client._download_with_ytdlp = fallback
        result = run(client.download_track("sc1"))
        self.assertEqual(result.getvalue(), b"audio")

    def test_cancellation_is_not_replaced_by_download_fallback(self):
        client = ms.MusicSearchClient()

        async def info(track_id):
            return {"download": "https://cdn/audio", "direct": True}

        async def cancelled(*args, **kwargs):
            raise asyncio.CancelledError()

        client.get_track_info = info
        client._stream_to_buffer = cancelled
        with self.assertRaises(asyncio.CancelledError):
            run(client.download_track("sc1"))

    def test_search_rejects_empty_query_and_bad_page(self):
        client = ms.MusicSearchClient()
        self.assertEqual(run(client.search_track("   "))["items"], [])
        with self.assertRaises(ValueError):
            run(client.search_track("x", page=0))

    def test_stored_metadata_is_injected_not_mongodb(self):
        async def metadata(track_id):
            return {"id": track_id, "title": "Cached"}

        client = ms.MusicSearchClient(metadata=metadata)
        self.assertEqual(run(client._stored_meta("42"))["title"], "Cached")

        async def broken(track_id):
            raise RuntimeError("database unavailable")

        client = ms.MusicSearchClient(metadata=broken)
        self.assertEqual(run(client._stored_meta("42")), {})

    def test_ytdlp_options_use_existing_cookie_setting(self):
        with mock.patch.dict(os.environ, {"YTDLP_COOKIES": "", "MEDIA_COOKIES": __file__,
                                          "YTDLP_PLAYER_CLIENT": "ios, web",
                                          "YTDLP_PROXY": "socks5://proxy",
                                          "YTDLP_JS_RUNTIMES": "node:/usr/bin/node,deno"}, clear=False):
            opts = ms.ytdl_env_opts()
        self.assertEqual(opts["cookiefile"], __file__)
        self.assertEqual(opts["proxy"], "socks5://proxy")
        self.assertEqual(opts["extractor_args"]["youtube"]["player_client"], ["ios", "web"])
        self.assertEqual(opts["js_runtimes"]["node"], {"path": "/usr/bin/node"})
        self.assertEqual(opts["js_runtimes"]["deno"], {})


async def _return(value):
    return value


if __name__ == "__main__":
    unittest.main()
