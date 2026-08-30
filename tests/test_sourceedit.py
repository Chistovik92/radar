#!/usr/bin/env python3
"""Правка источников и защита форм панели.

Модуль `sourceedit` появился в 4.8.4.5, когда добавление и удаление
источников понадобилось веб-панели. Дублировать разбор было нельзя:
правила «что считается каналом» разъехались бы между ботом и панелью,
и человек получил бы источник, который бот принимает, а панель считает
ошибкой. Здесь закреплено, что правила одни.

Отдельно проверяется скрытый токен формы. Пока панель только читала,
POST-запросов не было и защищать было нечего; с появлением правки чужая
страница могла бы отправить форму от имени вошедшего администратора.
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

from radar import sourceedit, storage  # noqa: E402
from radar.web import auth  # noqa: E402


class SourcesCase(unittest.TestCase):
    """Своё пустое хранилище: тесты не должны зависеть от базы машины."""

    def setUp(self) -> None:
        self.saved = {key: storage.DB.get(key) for key in
                      ("channels", "rss", "vk", "pending")}
        storage.DB["channels"] = []
        storage.DB["rss"] = []
        storage.DB["vk"] = []
        storage.DB["pending"] = []

    def tearDown(self) -> None:
        for key, value in self.saved.items():
            if value is None:
                storage.DB.pop(key, None)
            else:
                storage.DB[key] = value


class Channels(SourcesCase):
    def test_plain_username(self) -> None:
        added, skipped = sourceedit.add(sourceedit.TELEGRAM, "saratov_news")
        self.assertEqual(added, ["saratov_news"])
        self.assertEqual(skipped, [])

    def test_at_sign_and_links_normalized(self) -> None:
        for raw in ("@saratov_news", "https://t.me/saratov_news",
                    "t.me/saratov_news", "telegram.me/saratov_news/"):
            with self.subTest(raw=raw):
                storage.DB["channels"] = []
                added, _ = sourceedit.add(sourceedit.TELEGRAM, raw)
                self.assertEqual(added, ["saratov_news"])

    def test_several_at_once(self) -> None:
        added, _ = sourceedit.add(sourceedit.TELEGRAM, "first_one, second_one\nthird_one")
        self.assertEqual(added, ["first_one", "second_one", "third_one"])

    def test_duplicate_is_skipped_not_added_twice(self) -> None:
        sourceedit.add(sourceedit.TELEGRAM, "saratov_news")
        added, skipped = sourceedit.add(sourceedit.TELEGRAM, "saratov_news")
        self.assertEqual(added, [])
        self.assertEqual(skipped, ["saratov_news"])
        self.assertEqual(storage.channels(), ["saratov_news"])

    def test_garbage_reported_back(self) -> None:
        # Молчать про пропущенное нельзя: человек увидит «добавлено 0»
        # и не поймёт, ошибся он или источник уже был.
        added, skipped = sourceedit.add(sourceedit.TELEGRAM, "аб, x, ...")
        self.assertEqual(added, [])
        self.assertEqual(len(skipped), 3)

    def test_too_short_rejected(self) -> None:
        added, _ = sourceedit.add(sourceedit.TELEGRAM, "abc")
        self.assertEqual(added, [])


class Feeds(SourcesCase):
    def test_https_accepted(self) -> None:
        added, _ = sourceedit.add(sourceedit.RSS, "https://example.ru/rss")
        self.assertEqual(added, ["https://example.ru/rss"])

    def test_without_scheme_rejected(self) -> None:
        # Без схемы адрес не откроется, а узнать об этом из ошибки раз
        # в три минуты в журнале — худший способ.
        added, skipped = sourceedit.add(sourceedit.RSS, "example.ru/rss")
        self.assertEqual(added, [])
        self.assertEqual(skipped, ["example.ru/rss"])

    def test_javascript_scheme_rejected(self) -> None:
        added, _ = sourceedit.add(sourceedit.RSS, "javascript:alert(1)")
        self.assertEqual(added, [])


class VkGroups(SourcesCase):
    def test_link_normalized(self) -> None:
        added, _ = sourceedit.add(sourceedit.VK, "https://vk.com/saratov")
        self.assertEqual(added, ["saratov"])

    def test_mobile_link_normalized(self) -> None:
        added, _ = sourceedit.add(sourceedit.VK, "m.vk.com/club123?w=wall")
        self.assertEqual(added, ["club123"])


class Removal(SourcesCase):
    def test_removes_existing(self) -> None:
        sourceedit.add(sourceedit.TELEGRAM, "saratov_news")
        self.assertTrue(sourceedit.remove(sourceedit.TELEGRAM, "saratov_news"))
        self.assertEqual(storage.channels(), [])

    def test_absent_reported(self) -> None:
        self.assertFalse(sourceedit.remove(sourceedit.TELEGRAM, "нет_такого"))

    def test_unknown_kind_is_not_an_error(self) -> None:
        # Вид приходит из формы, то есть от постороннего. Падать нельзя.
        self.assertFalse(sourceedit.remove("выдумка", "что угодно"))
        self.assertEqual(sourceedit.add("выдумка", "что угодно"), ([], []))

    def test_counts_match_listing(self) -> None:
        sourceedit.add(sourceedit.TELEGRAM, "first_one, second_one")
        sourceedit.add(sourceedit.RSS, "https://example.ru/rss")
        self.assertEqual(sourceedit.counts()[sourceedit.TELEGRAM], 2)
        self.assertEqual(len(sourceedit.listing(sourceedit.RSS)), 1)

    def test_listing_is_a_copy(self) -> None:
        # Иначе вызывающий смог бы править список источников мимо проверок.
        sourceedit.add(sourceedit.TELEGRAM, "saratov_news")
        sourceedit.listing(sourceedit.TELEGRAM).append("подделка")
        self.assertEqual(storage.channels(), ["saratov_news"])


class FormToken(unittest.TestCase):
    def session(self, token: str = "секретный-токен") -> auth.Session:
        return auth.Session(token=token, user_key="telegram:1", role="superadmin")

    def test_token_matches_itself(self) -> None:
        item = self.session()
        self.assertTrue(auth.csrf_valid(item, auth.csrf_token(item)))

    def test_token_differs_between_sessions(self) -> None:
        first = auth.csrf_token(self.session("первый"))
        second = auth.csrf_token(self.session("второй"))
        self.assertNotEqual(first, second)

    def test_foreign_token_rejected(self) -> None:
        mine = self.session("мой")
        self.assertFalse(auth.csrf_valid(mine, auth.csrf_token(self.session("чужой"))))

    def test_empty_rejected(self) -> None:
        item = self.session()
        self.assertFalse(auth.csrf_valid(item, ""))
        self.assertFalse(auth.csrf_valid(None, auth.csrf_token(item)))

    def test_token_does_not_leak_session(self) -> None:
        # Токен формы попадает в HTML; из него не должен восстанавливаться
        # токен сессии, иначе скрытое поле стало бы вторым паролем.
        item = self.session()
        self.assertNotIn(item.token, auth.csrf_token(item))


if __name__ == "__main__":
    unittest.main()
