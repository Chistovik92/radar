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
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import images, media  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
