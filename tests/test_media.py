#!/usr/bin/env python3
"""Загрузка видео по ссылке и адаптер мессенджера MAX."""

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

from radar import media  # noqa: E402


# ==========================================================================
#  Разбор форматов
# ==========================================================================

YOUTUBE_LIKE = {
    "title": "Тестовый ролик",
    "uploader": "Канал",
    "duration": 725,
    "formats": [
        {"height": 1080, "ext": "mp4", "filesize": 180 * 1024 * 1024},
        {"height": 720, "ext": "mp4", "filesize": 90 * 1024 * 1024},
        {"height": 480, "ext": "mp4", "filesize_approx": 40 * 1024 * 1024},
        {"height": 360, "ext": "mp4", "filesize": 20 * 1024 * 1024},
        {"height": 144, "ext": "mp4", "filesize": 5 * 1024 * 1024},
        {"height": None, "ext": "m4a"},          # только звук
        {"height": 100, "ext": "mp4"},           # ниже порога
    ],
}

TIKTOK_LIKE = {"title": "Клип", "formats": [{"ext": "mp4", "url": "..."}]}


class TestCodecFamily(unittest.TestCase):
    """Имя кодека из yt-dlp приводится к семейству."""

    def test_known_codecs(self):
        cases = {
            "av01.0.05M.08": "av1",
            "vp09.00.51.08": "vp9",
            "vp9": "vp9",
            "hev1.1.6.L93": "h265",
            "hvc1.2.4.L120": "h265",
            "avc1.640028": "h264",
            "h264": "h264",
            "vp8": "vp8",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(media.codec_family(raw), expected)

    def test_absent_codec(self):
        for raw in ("", "none", "null", None):
            with self.subTest(raw=raw):
                self.assertEqual(media.codec_family(raw), "")

    def test_h264_is_safe_others_are_not(self):
        self.assertFalse(media.Format(label="x", vcodec="h264").risky_codec)
        self.assertFalse(media.Format(label="x", vcodec="").risky_codec)
        self.assertTrue(media.Format(label="x", vcodec="av1").risky_codec)
        self.assertTrue(media.Format(label="x", vcodec="vp9").risky_codec)


class TestSmallerFilePreferred(unittest.TestCase):
    """До 4.7.9 из вариантов одной высоты брался САМЫЙ БОЛЬШОЙ.

    Для системы с потолком отправки в 50 МБ это ровно наоборот: чем
    меньше файл при той же высоте, тем выше качество удастся отдать.
    """

    def info(self, *formats):
        return {"title": "Ролик", "formats": list(formats)}

    def test_smaller_of_two_wins(self):
        info = self.info(
            {"height": 1080, "ext": "mp4", "filesize": 180 * 1024 * 1024,
             "vcodec": "avc1.640028"},
            {"height": 1080, "ext": "webm", "filesize": 90 * 1024 * 1024,
             "vcodec": "av01.0.05M.08"},
        )
        best = media.parse_formats(info)[0]
        self.assertAlmostEqual(best.size_mb, 90.0, places=0)
        self.assertEqual(best.vcodec, "av1")

    def test_known_size_beats_unknown(self):
        """«~48 МБ» позволяет решить, влезет ли. Пустое место — нет."""
        info = self.info(
            {"height": 720, "ext": "mp4", "vcodec": "avc1.640028"},
            {"height": 720, "ext": "webm", "filesize": 48 * 1024 * 1024,
             "vcodec": "vp09.00.51.08"},
        )
        best = media.parse_formats(info)[0]
        self.assertAlmostEqual(best.size_mb, 48.0, places=0)

    def test_tiny_stub_rejected(self):
        """Обрезок в десятки килобайт не должен побеждать только за малость."""
        info = self.info(
            {"height": 720, "ext": "mp4", "filesize": 60 * 1024 * 1024,
             "vcodec": "avc1.640028"},
            {"height": 720, "ext": "mp4", "filesize": 40 * 1024,
             "vcodec": "avc1.640028"},
        )
        best = media.parse_formats(info)[0]
        self.assertAlmostEqual(best.size_mb, 60.0, places=0)

    def test_codec_decides_when_sizes_equal(self):
        info = self.info(
            {"height": 720, "ext": "mp4", "filesize": 50 * 1024 * 1024,
             "vcodec": "avc1.640028"},
            {"height": 720, "ext": "webm", "filesize": 50 * 1024 * 1024,
             "vcodec": "av01.0.05M.08"},
        )
        self.assertEqual(media.parse_formats(info)[0].vcodec, "av1")

    def test_risky_codec_shown_in_button(self):
        item = media.Format(label="1080p", height=1080, size_mb=42.0, vcodec="av1")
        self.assertIn("av1", item.title)
        self.assertIn("1080p", item.title)

    def test_safe_codec_not_mentioned(self):
        item = media.Format(label="720p", height=720, size_mb=30.0, vcodec="h264")
        self.assertNotIn("h264", item.title)


class TestChooseDefault(unittest.TestCase):
    """По умолчанию человек получает работающее видео."""

    def test_highest_that_fits(self):
        formats = [
            media.Format(label="1080p", height=1080, size_mb=180.0, vcodec="h264"),
            media.Format(label="720p", height=720, size_mb=45.0, vcodec="h264"),
            media.Format(label="480p", height=480, size_mb=20.0, vcodec="h264"),
        ]
        self.assertEqual(media.choose_default(formats, 50).height, 720)

    def test_playable_wins_at_equal_height(self):
        """При равной высоте — то, что точно проиграется."""
        formats = [
            media.Format(label="720p", height=720, size_mb=30.0, vcodec="av1"),
            media.Format(label="720p", height=720, size_mb=45.0, vcodec="h264"),
        ]
        self.assertEqual(media.choose_default(formats, 50).vcodec, "h264")

    def test_nothing_fits_returns_smallest(self):
        formats = [
            media.Format(label="1080p", height=1080, size_mb=300.0),
            media.Format(label="720p", height=720, size_mb=200.0),
        ]
        self.assertEqual(media.choose_default(formats, 50).height, 720)

    def test_no_formats(self):
        self.assertIsNone(media.choose_default([], 50))

    def test_unknown_sizes_fall_back(self):
        formats = [media.Format(label="Максимальное", height=0)]
        self.assertIsNotNone(media.choose_default(formats, 50))


class TestFormatParsing(unittest.TestCase):
    def test_heights_collected(self):
        formats = media.parse_formats(YOUTUBE_LIKE)
        labels = [item.label for item in formats]
        self.assertIn("1080p", labels)
        self.assertIn("360p", labels)
        self.assertNotIn("100p", labels)   # ниже порога 144

    def test_sorted_descending(self):
        heights = [item.height for item in media.parse_formats(YOUTUBE_LIKE)]
        self.assertEqual(heights, sorted(heights, reverse=True))

    def test_sizes_converted(self):
        best = media.parse_formats(YOUTUBE_LIKE)[0]
        self.assertAlmostEqual(best.size_mb, 180.0, places=0)

    def test_approx_size_used(self):
        item = next(f for f in media.parse_formats(YOUTUBE_LIKE) if f.height == 480)
        self.assertAlmostEqual(item.size_mb, 40.0, places=0)

    def test_fallback_when_no_heights(self):
        formats = media.parse_formats(TIKTOK_LIKE)
        self.assertEqual(len(formats), 1)
        self.assertEqual(formats[0].height, 0)

    def test_empty_info_safe(self):
        self.assertEqual(len(media.parse_formats({})), 1)

    def test_garbage_formats_ignored(self):
        info = {"formats": ["строка", None, 42, {"height": "много"}]}
        self.assertEqual(len(media.parse_formats(info)), 1)

    def test_limit_respected(self):
        self.assertLessEqual(len(media.parse_formats(YOUTUBE_LIKE, limit=3)), 3)

    def test_selector_for_height(self):
        item = media.Format(label="720p", height=720)
        self.assertIn("height<=720", item.selector)

    def test_selector_for_best(self):
        self.assertEqual(
            media.Format(label="Лучшее", height=0).selector, "bestvideo+bestaudio/best"
        )


class TestLimits(unittest.TestCase):
    def test_cloud_limit(self):
        self.assertEqual(media.size_limit_mb(False), 50)

    def test_local_limit(self):
        self.assertGreater(media.size_limit_mb(True), 1000)

    def test_too_big_on_cloud(self):
        oversize, reason = media.too_big(100 * 1024 * 1024, local_server=False)
        self.assertTrue(oversize)
        self.assertIn("50", reason)

    def test_fits_on_local(self):
        oversize, _ = media.too_big(100 * 1024 * 1024, local_server=True)
        self.assertFalse(oversize)

    def test_huge_file_rejected_even_locally(self):
        oversize, reason = media.too_big(3000 * 1024 * 1024, local_server=True)
        self.assertTrue(oversize)
        self.assertIn("качество ниже", reason)

    def test_default_choice_fits_limit(self):
        formats = media.parse_formats(YOUTUBE_LIKE)
        chosen = media.choose_default(formats, limit_mb=50)
        self.assertIsNotNone(chosen)
        self.assertLessEqual(chosen.size_mb, 50)


class TestProgress(unittest.TestCase):
    def test_percent(self):
        progress = media.Progress(total=1000, done=250)
        self.assertAlmostEqual(progress.percent, 25.0)

    def test_percent_without_total(self):
        self.assertEqual(media.Progress().percent, 0.0)

    def test_throttling(self):
        progress = media.Progress()
        self.assertTrue(progress.should_refresh(now=1000.0))
        self.assertFalse(progress.should_refresh(now=1001.0))
        self.assertTrue(progress.should_refresh(now=1000 + media.PROGRESS_INTERVAL + 1))

    def test_bar_endpoints(self):
        self.assertIn("0%", media.progress_bar(0))
        self.assertIn("100%", media.progress_bar(100))
        self.assertIn("100%", media.progress_bar(150))  # выход за границу

    def test_hook_downloading(self):
        progress = media.Progress()
        refresh = media.read_hook(
            {"status": "downloading", "total_bytes": 1000,
             "downloaded_bytes": 500, "_speed_str": "1 MiB/s"},
            progress,
        )
        self.assertTrue(refresh)
        self.assertEqual(progress.stage, "download")
        self.assertEqual(progress.speed, "1 MiB/s")

    def test_hook_finished_switches_stage(self):
        progress = media.Progress(total=100, done=50)
        self.assertTrue(media.read_hook({"status": "finished"}, progress))
        self.assertEqual(progress.stage, "merge")
        self.assertEqual(progress.done, progress.total)

    def test_hook_ignores_unknown(self):
        self.assertFalse(media.read_hook({"status": "чепуха"}, media.Progress()))

    def test_render_contains_bar(self):
        progress = media.Progress(total=2 * 1024 * 1024, done=1024 * 1024)
        text = progress.render()
        self.assertIn("50%", text)
        self.assertIn("МБ", text)


class TestHelpers(unittest.TestCase):
    def test_url_detection(self):
        self.assertTrue(media.looks_like_url("https://youtu.be/abc"))
        self.assertTrue(media.looks_like_url("http://vk.com/video1"))
        self.assertFalse(media.looks_like_url("просто текст"))
        self.assertFalse(media.looks_like_url("ftp://host/file"))
        self.assertFalse(media.looks_like_url(""))

    def test_filename_sanitized(self):
        self.assertNotIn("/", media.safe_filename("папка/файл"))
        self.assertNotIn(":", media.safe_filename("время: 10:00"))
        self.assertTrue(media.safe_filename(""))

    def test_filename_length_capped(self):
        self.assertLessEqual(len(media.safe_filename("а" * 300)), 60)

    def test_describe_escapes(self):
        text = media.describe({"title": "<script>", "duration": 65})
        self.assertNotIn("<script>", text)
        self.assertIn("1:05", text)

    def test_options_include_proxy(self):
        options = media.build_options("out.%(ext)s", "best", proxy="socks5://x:1080")
        self.assertEqual(options["proxy"], "socks5://x:1080")
        self.assertTrue(options["noplaylist"])

    def test_options_without_optional(self):
        options = media.build_options("out.%(ext)s", "best")
        self.assertNotIn("proxy", options)
        self.assertNotIn("cookiefile", options)

    def test_error_translation(self):
        cases = {
            "ERROR: Unsupported URL: https://x": "не поддерживается",
            "This video is private": "приватности",
            "HTTP Error 429: Too Many Requests": "ограничила",
            "ffmpeg not found": "ffmpeg",
        }
        for raw, expected in cases.items():
            self.assertIn(expected, media.friendly_error(raw))

    def test_unknown_error_has_fallback(self):
        self.assertTrue(media.friendly_error("нечто невиданное"))


# ==========================================================================
#  Адаптер MAX (реализован, но не проверен на живом сервере)
# ==========================================================================

class TestMaxTransport(unittest.TestCase):
    def setUp(self):
        from radar.platforms.max import MaxTransport

        self.transport = MaxTransport(token="test-token", base_url="https://example/api")

    def test_not_configured_without_token(self):
        from radar.platforms.max import MaxTransport

        self.assertFalse(MaxTransport(token="").configured)
        self.assertTrue(self.transport.configured)

    def test_render_strips_html(self):
        self.assertEqual(self.transport.render("<b>Текст</b>"), "Текст")
        self.assertEqual(self.transport.render("a &amp; b"), "a & b")

    def test_keyboard_conversion(self):
        from radar.platforms import Button

        keyboard = [[Button(text="Меню", payload="menu:main"),
                     Button(text="Сайт", url="https://example.ru")]]
        converted = self.transport.to_keyboard(keyboard)
        self.assertEqual(converted[0][0]["payload"], "menu:main")
        self.assertEqual(converted[0][1]["type"], "link")

    def test_empty_keyboard(self):
        self.assertEqual(self.transport.to_keyboard([]), [])

    def test_parse_flat_message(self):
        event = self.transport.parse_update(
            {"update_type": "message_created",
             "message": {"chat_id": 100, "text": "привет",
                         "from": {"user_id": 55, "name": "Иван"}}}
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.chat_id, "100")
        self.assertEqual(event.key, "max:55")
        self.assertEqual(event.kind.value, "message")

    def test_parse_nested_chat(self):
        event = self.transport.parse_update(
            {"message": {"chat": {"id": 200}, "text": "текст"}}
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.chat_id, "200")

    def test_parse_command(self):
        event = self.transport.parse_update(
            {"message": {"chat_id": 1, "text": "/start join"}}
        )
        self.assertEqual(event.kind.value, "command")
        self.assertEqual(event.command, "start")
        self.assertEqual(event.args, "join")

    def test_parse_location(self):
        event = self.transport.parse_update(
            {"message": {"chat_id": 1, "location": {"latitude": 51.5, "longitude": 46.0}}}
        )
        self.assertEqual(event.kind.value, "location")
        self.assertEqual(event.latitude, 51.5)

    def test_parse_without_chat_returns_none(self):
        self.assertIsNone(self.transport.parse_update({"update_type": "ping"}))
        self.assertIsNone(self.transport.parse_update("не словарь"))

    def test_identity_separate_from_telegram(self):
        event = self.transport.parse_update({"message": {"chat_id": 42, "text": "т"}})
        self.assertEqual(event.key, "max:42")
        self.assertNotEqual(event.key, "42")


if __name__ == "__main__":
    unittest.main(verbosity=2)
