#!/usr/bin/env python3
"""Записи с картинками: разбор метаданных и объяснения отказов.

Проверки написаны по живым ответам площадок, снятым на сервере автора.
Оказалось, что «видео не качается» означало другое: люди присылают ссылки
на записи, где видео нет и не было — пост с фотографией в Instagram, твит
с картинкой, сообщение сообщества YouTube. yt-dlp отвечал честно, а бот
переводил это в «Не удалось обработать ссылку» и заводил в тупик.

Отдельно закреплён разбор ошибки ВКонтакте. Она пишет «signed-in» через
дефис, а проверка искала «sign in» с пробелом — запрос, требующий входа,
уходил в общий отказ, и подсказка про cookies не показывалась.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import images, media  # noqa: E402

# Обратный слэш через chr: в разметке соцсетей адреса приходят
# экранированными, и запись их литералом в тесте читается хуже.
B = chr(92)

# Ответы площадок дословно, как их видно в журнале сервера.
VK_LOGIN = "ERROR: [vk] Video only available to signed-in users"
X_NO_VIDEO = "ERROR: [twitter] 2092128873358184710: No video could be found in this tweet"
INSTAGRAM_NO_VIDEO = "ERROR: [Instagram] DcWj3aeMuKi: There is no video in this post"
YOUTUBE_POST = ("ERROR: [youtube:tab] post: This channel does not have a "
                "Ugkxz0OVeH0hVyEATObBAyAPycSRP7FwBInZ tab")
TOO_BIG = "ERROR: File is larger than max-filesize (60000000 bytes)"


class NoVideoDetection(unittest.TestCase):
    def test_tweet_with_pictures(self) -> None:
        self.assertTrue(media.looks_like_no_video(X_NO_VIDEO))

    def test_instagram_photo_post(self) -> None:
        self.assertTrue(media.looks_like_no_video(INSTAGRAM_NO_VIDEO))

    def test_youtube_community_post(self) -> None:
        self.assertTrue(media.looks_like_no_video(YOUTUBE_POST))

    def test_login_wall_is_not_a_picture_post(self) -> None:
        # Там видео может быть — его просто не показывают. Лезть за
        # картинками бессмысленно: страница входа их не отдаст.
        self.assertFalse(media.looks_like_no_video(VK_LOGIN))

    def test_size_limit_is_not_a_picture_post(self) -> None:
        self.assertFalse(media.looks_like_no_video(TOO_BIG))


class Explanations(unittest.TestCase):
    def test_vk_asks_for_cookies(self) -> None:
        # Прежняя проверка искала «sign in» с пробелом и промахивалась.
        self.assertIn("cookies", media.friendly_error(VK_LOGIN))

    def test_picture_post_explained(self) -> None:
        for answer in (X_NO_VIDEO, INSTAGRAM_NO_VIDEO, YOUTUBE_POST):
            with self.subTest(answer=answer):
                self.assertIn("картинк", media.friendly_error(answer))

    def test_size_limit_still_explained(self) -> None:
        self.assertIn("предел", media.friendly_error(TOO_BIG))

    def test_unknown_error_has_a_fallback(self) -> None:
        self.assertTrue(media.friendly_error("ERROR: нечто небывалое"))


class PageParsing(unittest.TestCase):
    def page(self, meta: str) -> str:
        return f"<html><head>{meta}</head><body>тело</body></html>"

    def test_open_graph_image(self) -> None:
        markup = self.page('<meta property="og:image" content="https://cdn.ru/a.jpg">')
        self.assertEqual(images.from_page(markup), ["https://cdn.ru/a.jpg"])

    def test_twitter_image(self) -> None:
        markup = self.page('<meta name="twitter:image" content="https://cdn.ru/b.png">')
        self.assertEqual(images.from_page(markup), ["https://cdn.ru/b.png"])

    def test_several_kept_in_order_without_duplicates(self) -> None:
        markup = self.page(
            '<meta property="og:image:secure_url" content="https://cdn.ru/1.jpg">'
            '<meta property="og:image" content="https://cdn.ru/1.jpg">'
            '<meta name="twitter:image" content="https://cdn.ru/2.jpg">'
        )
        self.assertEqual(images.from_page(markup),
                         ["https://cdn.ru/1.jpg", "https://cdn.ru/2.jpg"])

    def test_relative_link_resolved(self) -> None:
        markup = self.page('<meta property="og:image" content="/media/c.jpg">')
        self.assertEqual(images.from_page(markup, "https://example.ru/p/1"),
                         ["https://example.ru/media/c.jpg"])

    def test_non_http_scheme_dropped(self) -> None:
        # data: и javascript: в метаданных встречаются у самодельных
        # страниц; скачивать по ним нечего, а рисков достаточно.
        markup = self.page('<meta property="og:image" content="data:image/png;base64,AAA">')
        self.assertEqual(images.from_page(markup), [])

    def test_other_meta_ignored(self) -> None:
        markup = self.page(
            '<meta property="og:title" content="Заголовок">'
            '<meta name="description" content="Описание">'
        )
        self.assertEqual(images.from_page(markup), [])

    def test_empty_content_ignored(self) -> None:
        self.assertEqual(images.from_page(self.page('<meta property="og:image" content="">')), [])

    def test_empty_markup_is_not_an_error(self) -> None:
        self.assertEqual(images.from_page(""), [])
        self.assertEqual(images.from_page(None or ""), [])

    def test_login_page_yields_nothing(self) -> None:
        # Закрытая запись отдаёт страницу входа. Картинок там нет, и это
        # не поломка — бот должен честно объяснить, а не молчать.
        markup = self.page('<meta property="og:title" content="Войдите в аккаунт">')
        self.assertEqual(images.from_page(markup), [])

    def test_count_is_capped(self) -> None:
        meta = "".join(
            f'<meta property="og:image" content="https://cdn.ru/{i}.jpg">'
            for i in range(30)
        )
        self.assertEqual(len(images.from_page(self.page(meta))), images.MAX_FROM_PAGE)


class Carousel(unittest.TestCase):
    """Несколько картинок в одной записи.

    Метаданные предпросмотра отдают только первую: их задача — картинка
    для ссылки в мессенджере, а не содержимое записи. В карусели Instagram
    снимков бывает десяток, и человек, приславший ссылку на пост, ждёт
    весь пост, а не его обложку.
    """

    def page(self, body: str) -> str:
        return ('<html><head>'
                '<meta property="og:image" content="https://cdn.ru/first.jpg">'
                '</head><body>' + body + '</body></html>')

    def test_first_from_meta_then_rest_from_json(self) -> None:
        markup = self.page(
            '<script>{"display_url":"https://cdn.ru/second.jpg",'
            '"display_url":"https://cdn.ru/third.jpg"}</script>'
        )
        self.assertEqual(images.from_page(markup), [
            "https://cdn.ru/first.jpg",
            "https://cdn.ru/second.jpg",
            "https://cdn.ru/third.jpg",
        ])

    def test_escaped_slashes_and_ampersand(self) -> None:
        raw = "https:" + B + "/" + B + "/cdn.ru" + B + "/x.jpg?a=1" + B + "u0026b=2"
        markup = self.page('<script>{"display_url":"' + raw + '"}</script>')
        self.assertIn("https://cdn.ru/x.jpg?a=1&b=2", images.from_page(markup))

    def test_video_entries_dropped(self) -> None:
        # По тем же ключам площадки кладут ссылки на ролики и профиль.
        markup = self.page('<script>{"display_url":"https://cdn.ru/clip.mp4"}</script>')
        self.assertEqual(images.from_page(markup), ["https://cdn.ru/first.jpg"])

    def test_duplicates_dropped(self) -> None:
        markup = self.page('<script>{"display_url":"https://cdn.ru/first.jpg"}</script>')
        self.assertEqual(images.from_page(markup), ["https://cdn.ru/first.jpg"])

    def test_twitter_key_supported(self) -> None:
        markup = self.page('<script>{"media_url_https":"https://pbs.tw/a.jpg"}</script>')
        self.assertIn("https://pbs.tw/a.jpg", images.from_page(markup))

    def test_cap_applies_across_both_sources(self) -> None:
        body = "<script>{" + ",".join(
            '"display_url":"https://cdn.ru/%d.jpg"' % i for i in range(30)
        ) + "}</script>"
        self.assertEqual(len(images.from_page(self.page(body))), images.MAX_FROM_PAGE)

    def test_json_without_images_is_not_an_error(self) -> None:
        markup = self.page('<script>{"count":3,"display_url":""}</script>')
        self.assertEqual(images.from_page(markup), ["https://cdn.ru/first.jpg"])


class Sweeping(unittest.TestCase):
    """Уборка рабочего каталога после прерванных загрузок."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = self.directory.name

    def tearDown(self) -> None:
        self.directory.cleanup()

    def make(self, name: str, age_hours: float) -> str:
        target = os.path.join(self.path, name)
        with open(target, "wb") as handle:
            handle.write(b"x")
        stamp = time.time() - age_hours * 3600
        os.utime(target, (stamp, stamp))
        return target

    def test_old_leftovers_removed(self) -> None:
        # Ровно то, что оставляет прерванная загрузка.
        self.make("video.mp4.part", 10)
        self.make("video.f137.mp4", 10)
        self.assertEqual(media.sweep(self.path), 2)
        self.assertEqual(os.listdir(self.path), [])

    def test_fresh_files_kept(self) -> None:
        # Идущая прямо сейчас загрузка не должна быть убрана из-под себя.
        self.make("сейчас.mp4.part", 0)
        self.assertEqual(media.sweep(self.path), 0)
        self.assertEqual(len(os.listdir(self.path)), 1)

    def test_boundary_respected(self) -> None:
        self.make("свежий.part", media.SWEEP_AFTER_HOURS - 1)
        self.make("старый.part", media.SWEEP_AFTER_HOURS + 1)
        self.assertEqual(media.sweep(self.path), 1)
        self.assertEqual(os.listdir(self.path), ["свежий.part"])

    def test_missing_directory_is_not_an_error(self) -> None:
        self.assertEqual(media.sweep(os.path.join(self.path, "нет")), 0)
        self.assertEqual(media.sweep(""), 0)

    def test_subdirectories_untouched(self) -> None:
        os.mkdir(os.path.join(self.path, "вложенный"))
        self.assertEqual(media.sweep(self.path), 0)
        self.assertEqual(os.listdir(self.path), ["вложенный"])


if __name__ == "__main__":
    unittest.main()
