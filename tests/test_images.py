#!/usr/bin/env python3
"""Скачивание картинок и текст описания.

Главное, что здесь проверяется, — защита диска. Сервер может объявить
один размер, а прислать другой; ссылка может вести на бесконечный поток.
Забитый диск на одноплатнике останавливает не картинки, а оповещения:
базе становится некуда писать.
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

from radar import images  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeContent:
    def __init__(self, pieces):
        self._pieces = pieces

    async def iter_chunked(self, _size):
        for piece in self._pieces:
            yield piece


class FakeResponse:
    def __init__(self, *, status=200, headers=None, pieces=(b"data" * 10,)):
        self.status = status
        self.headers = headers if headers is not None else {"Content-Type": "image/jpeg"}
        self.content = FakeContent(pieces)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class FakeSession:
    def __init__(self, response=None, boom=None):
        self._response = response
        self._boom = boom

    def get(self, _url):
        if self._boom:
            raise self._boom
        return self._response


class TestRecognition(unittest.TestCase):
    def test_common_extensions(self):
        for ext in images.EXTENSIONS:
            with self.subTest(ext=ext):
                self.assertTrue(images.looks_like_image(f"https://site.ru/pic{ext}"))

    def test_uppercase_extension(self):
        self.assertTrue(images.looks_like_image("https://site.ru/PIC.JPG"))

    def test_query_string_ignored(self):
        """«?logo=x.png» не делает страницу картинкой."""
        self.assertFalse(images.looks_like_image("https://site.ru/page?logo=x.png"))

    def test_extension_in_query_only(self):
        self.assertTrue(images.looks_like_image("https://site.ru/pic.jpg?size=big"))

    def test_video_is_not_an_image(self):
        for url in ("https://youtu.be/abc", "https://site.ru/clip.mp4",
                    "https://site.ru/", "не ссылка", ""):
            with self.subTest(url=url):
                self.assertFalse(images.looks_like_image(url))

    def test_non_http_rejected(self):
        self.assertFalse(images.looks_like_image("ftp://site.ru/pic.jpg"))
        self.assertFalse(images.looks_like_image("file:///etc/pic.png"))


class TestFilename(unittest.TestCase):
    def test_taken_from_path(self):
        self.assertEqual(images.filename_from("https://site.ru/a/photo.jpg"), "photo.jpg")

    def test_percent_decoded(self):
        name = images.filename_from("https://site.ru/%D1%84%D043.jpg")
        self.assertTrue(name.endswith(".jpg"))

    def test_dangerous_characters_removed(self):
        name = images.filename_from("https://site.ru/../../etc/passwd.png")
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)

    def test_fallback_when_no_name(self):
        self.assertEqual(images.filename_from("https://site.ru/"), "image.jpg")

    def test_length_capped(self):
        long_name = "x" * 300 + ".jpg"
        self.assertLessEqual(len(images.filename_from(f"https://s.ru/{long_name}")), 80)


class TestPhotoOrDocument(unittest.TestCase):
    """Крупная картинка уходит документом, а не отвергается."""

    def test_small_goes_as_photo(self):
        self.assertTrue(images.as_photo(2 * 1024 * 1024))

    def test_large_goes_as_document(self):
        self.assertFalse(images.as_photo(20 * 1024 * 1024))

    def test_boundary_is_telegram_limit(self):
        self.assertTrue(images.as_photo(images.PHOTO_LIMIT_MB * 1024 * 1024))
        self.assertFalse(images.as_photo(images.PHOTO_LIMIT_MB * 1024 * 1024 + 1))


class TestFetch(unittest.TestCase):
    def test_successful_download(self):
        session = FakeSession(FakeResponse(pieces=(b"abc", b"def")))
        data, complaint = run(images.fetch(session, "https://s.ru/p.jpg", 50))
        self.assertEqual(data, b"abcdef")
        self.assertEqual(complaint, "")

    def test_declared_size_rejected_before_download(self):
        """Заявленный размер отсекает заведомо крупное до загрузки."""
        session = FakeSession(FakeResponse(headers={
            "Content-Type": "image/png",
            "Content-Length": str(80 * 1024 * 1024),
        }))
        data, complaint = run(images.fetch(session, "https://s.ru/p.png", 50))
        self.assertEqual(data, b"")
        self.assertIn("предел отправки", complaint)

    def test_actual_size_stops_a_liar(self):
        """Сервер объявил мало, а шлёт много — обрываем по факту."""
        piece = b"x" * (1024 * 1024)
        session = FakeSession(FakeResponse(
            headers={"Content-Type": "image/jpeg", "Content-Length": "10"},
            pieces=[piece] * 8,
        ))
        data, complaint = run(images.fetch(session, "https://s.ru/p.jpg", 5))
        self.assertEqual(data, b"")
        self.assertIn("МБ", complaint)

    def test_endless_stream_stopped(self):
        """Без предела по факту бесконечный поток забил бы диск."""
        def endless():
            while True:
                yield b"y" * (256 * 1024)

        session = FakeSession(FakeResponse(pieces=endless()))
        data, complaint = run(images.fetch(session, "https://s.ru/p.jpg", 2))
        self.assertEqual(data, b"")
        self.assertTrue(complaint)

    def test_non_image_content_type(self):
        session = FakeSession(FakeResponse(headers={"Content-Type": "text/html"}))
        data, complaint = run(images.fetch(session, "https://s.ru/p.jpg", 50))
        self.assertEqual(data, b"")
        self.assertIn("не картинка", complaint)

    def test_missing_content_type_allowed(self):
        """Не все серверы его присылают — это не повод отказывать."""
        session = FakeSession(FakeResponse(headers={}))
        data, _ = run(images.fetch(session, "https://s.ru/p.jpg", 50))
        self.assertTrue(data)

    def test_http_error(self):
        session = FakeSession(FakeResponse(status=404))
        data, complaint = run(images.fetch(session, "https://s.ru/p.jpg", 50))
        self.assertEqual(data, b"")
        self.assertIn("404", complaint)

    def test_empty_body(self):
        session = FakeSession(FakeResponse(pieces=()))
        data, complaint = run(images.fetch(session, "https://s.ru/p.jpg", 50))
        self.assertEqual(data, b"")
        self.assertIn("пусто", complaint)

    def test_network_failure_explained_plainly(self):
        """Сетевой сбой и битая ссылка для человека — одно событие."""
        session = FakeSession(boom=OSError("сеть недоступна"))
        data, complaint = run(images.fetch(session, "https://s.ru/p.jpg", 50))
        self.assertEqual(data, b"")
        self.assertIn("Не удалось скачать", complaint)


class TestDescription(unittest.TestCase):
    def test_description_found(self):
        self.assertEqual(images.description_of({"description": " текст "}), "текст")

    def test_alternative_keys(self):
        self.assertEqual(images.description_of({"summary": "сводка"}), "сводка")

    def test_absent(self):
        for info in ({}, {"description": ""}, {"description": None}, None or {}):
            with self.subTest(info=info):
                self.assertEqual(images.description_of(info), "")

    def test_message_when_no_description(self):
        self.assertIn("нет описания", images.format_description({}))

    def test_title_included(self):
        text = images.format_description({"title": "Заголовок", "description": "Тело"})
        self.assertIn("Заголовок", text)
        self.assertIn("Тело", text)

    def test_long_text_trimmed_with_notice(self):
        """Telegram обрежет молча — режем сами и говорим об этом."""
        text = images.format_description({"description": "я" * 9000})
        self.assertLess(len(text), 4096)
        self.assertIn("обрезано", text)

    def test_html_escaped(self):
        text = images.format_description({"description": "<script>ой</script>"})
        self.assertNotIn("<script>", text)


class MirrorTest(unittest.TestCase):
    """Публичные зеркала записей: адрес и разбор ответа (с 4.9.4.6)."""

    def test_mirror_for_instagram(self):
        url = "https://www.instagram.com/p/Cx123AbCdEf/"
        self.assertEqual(images.mirror_for(url),
                         "https://ddinstagram.com/p/Cx123AbCdEf")

    def test_mirror_for_x(self):
        url = "https://x.com/user/status/1234567890"
        self.assertEqual(images.mirror_for(url),
                         "https://api.fxtwitter.com/user/status/1234567890")

    def test_mirror_for_twitter(self):
        url = "https://twitter.com/user/status/42"
        self.assertEqual(images.mirror_for(url),
                         "https://api.fxtwitter.com/user/status/42")

    def test_mirror_for_unknown(self):
        for url in ("https://youtube.com/watch?v=1", "https://vk.com/wall-1_2",
                    "https://x.com", "not a url"):
            with self.subTest(url=url):
                self.assertEqual(images.mirror_for(url), "")

    def test_from_fxtwitter(self):
        payload = (
            '{"media":{"photos":['
            '{"url":"https:\\/\\/pbs.twimg.com\\/media\\/Abc123?format=jpg&name=large"},'
            '{"url":"https:\\/\\/pbs.twimg.com\\/media\\/Def456?format=jpg&name=large"}'
            ']}}'
        )
        found = images.from_fxtwitter(payload)
        self.assertEqual(len(found), 2)
        self.assertTrue(found[0].startswith("https://pbs.twimg.com/media/"))
        # Экранированные слэши развернулись
        self.assertNotIn("\\/", found[0])

    def test_from_fxtwitter_empty(self):
        self.assertEqual(images.from_fxtwitter(""), [])
        self.assertEqual(images.from_fxtwitter('{"media":{}}'), [])


class YoutubeClientsTest(unittest.TestCase):
    """Каскад клиентов YouTube: проба и загрузка идут одним путём."""

    def test_build_options_has_clients(self):
        from radar import media as core_media

        options = core_media.build_options("/tmp/x.%(ext)s", "best")
        self.assertIn("extractor_args", options)
        clients = options["extractor_args"]["youtube"]["player_client"]
        self.assertIn("ios", clients)

    def test_build_options_default_clients(self):
        """None — умолчания yt-dlp: второй шаг каскада после осечки."""
        from radar import media as core_media

        options = core_media.build_options("/tmp/x.%(ext)s", "best", clients=None)
        self.assertNotIn("extractor_args", options)

    def test_probe_options_match_build(self):
        from radar import media as core_media

        probe = core_media.probe_options()
        build = core_media.build_options("/tmp/x.%(ext)s", "best")
        self.assertEqual(
            probe["extractor_args"]["youtube"]["player_client"],
            build["extractor_args"]["youtube"]["player_client"],
        )

    def test_probe_options_default_matches_build_default(self):
        from radar import media as core_media

        probe = core_media.probe_options(clients=None)
        build = core_media.build_options("/tmp/x.%(ext)s", "best", clients=None)
        self.assertNotIn("extractor_args", probe)
        self.assertNotIn("extractor_args", build)

    def test_worth_client_retry(self):
        from radar import media as core_media

        self.assertTrue(core_media.worth_client_retry(
            "Video unavailable in your country"))
        self.assertTrue(core_media.worth_client_retry(
            "Sign in to confirm you're not a bot"))
        self.assertTrue(core_media.worth_client_retry("This video is private"))
        self.assertFalse(core_media.worth_client_retry("unsupported url"))
        self.assertFalse(core_media.worth_client_retry("connection reset"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
