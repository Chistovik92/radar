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
