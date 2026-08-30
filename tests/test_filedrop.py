#!/usr/bin/env python3
"""Раздача крупных файлов по ссылке.

Telegram принимает от ботов не больше 50 МБ, а серия с Rutube весит
1190 МБ. До 4.8.5 разговор на этом заканчивался советом «выберите
качество ниже» — качества ниже может не быть — или «поднимите свой
Bot API Server», чего ради одного файла никто не сделает.

Здесь закреплено главное: файл переносится, а не копируется (копия
удвоила бы занятое место ровно тогда, когда его и так много), имя
непредсказуемо, просроченное не отдаётся даже лёжа на диске, и бюджет
места соблюдается — забитый диск останавливает оповещения, а они важнее
любого скачивания.
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import filedrop  # noqa: E402

BASE = "https://boot.example.ru"


class DropCase(unittest.TestCase):
    """Своя раздача во временном каталоге и известный внешний адрес."""

    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.saved_directory = filedrop.DIRECTORY
        filedrop.DIRECTORY = os.path.join(self.workspace.name, "drop")

        patcher = mock.patch("radar.shortener.base_url", return_value=BASE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        filedrop.DIRECTORY = self.saved_directory
        self.workspace.cleanup()

    def source(self, name: str = "видео.mp4", size: int = 1024) -> str:
        path = os.path.join(self.workspace.name, name)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        return path


class Availability(DropCase):
    def test_needs_public_address(self) -> None:
        # Без внешнего адреса ссылка вела бы в никуда — предлагать нельзя.
        with mock.patch("radar.shortener.base_url", return_value=""):
            self.assertFalse(filedrop.enabled())
            self.assertIsNone(filedrop.store(self.source(), "видео"))

    def test_enabled_with_address(self) -> None:
        self.assertTrue(filedrop.enabled())


class Storing(DropCase):
    def test_file_is_moved_not_copied(self) -> None:
        # Копия удвоила бы занятое место ровно тогда, когда файла и так
        # слишком много для отправки.
        source = self.source()
        drop = filedrop.store(source, "видео")
        self.assertIsNotNone(drop)
        self.assertFalse(os.path.exists(source))
        self.assertTrue(os.path.isfile(drop.path))

    def test_token_is_unpredictable(self) -> None:
        first = filedrop.store(self.source("a.mp4"), "a")
        second = filedrop.store(self.source("b.mp4"), "b")
        self.assertNotEqual(first.token, second.token)
        self.assertEqual(len(first.token), 32)
        self.assertTrue(filedrop.valid_token(first.token))

    def test_extension_kept(self) -> None:
        drop = filedrop.store(self.source("серия.mp4"), "Бывшие, 1 серия")
        self.assertTrue(drop.name.endswith(".mp4"))

    def test_dangerous_name_defused(self) -> None:
        drop = filedrop.store(self.source("x.mp4"), "../../etc/passwd")
        self.assertNotIn("/", drop.name)
        self.assertNotIn("..", drop.name)

    def test_missing_source_is_not_an_error(self) -> None:
        self.assertIsNone(filedrop.store("/нет/такого/файла", "имя"))
        self.assertIsNone(filedrop.store("", "имя"))

    def test_url_points_at_public_address(self) -> None:
        drop = filedrop.store(self.source(), "видео")
        self.assertTrue(filedrop.url_for(drop).startswith(f"{BASE}/d/"))
        self.assertIn(drop.token, filedrop.url_for(drop))


class Finding(DropCase):
    def test_found_by_token(self) -> None:
        drop = filedrop.store(self.source(), "видео")
        found = filedrop.find(drop.token)
        self.assertIsNotNone(found)
        self.assertEqual(found.path, drop.path)

    def test_unknown_token_is_nothing(self) -> None:
        self.assertIsNone(filedrop.find("0" * 32))

    def test_garbage_token_rejected(self) -> None:
        # Токен приходит из адреса, то есть от постороннего.
        for value in ("", "../../etc/passwd", "не токен", "z" * 32, "abc"):
            with self.subTest(value=value):
                self.assertIsNone(filedrop.find(value))
                self.assertFalse(filedrop.valid_token(value))

    def test_expired_not_served_even_while_on_disk(self) -> None:
        drop = filedrop.store(self.source(), "видео")
        stamp = time.time() - (filedrop.TTL_HOURS + 1) * 3600
        os.utime(drop.path, (stamp, stamp))
        self.assertIsNone(filedrop.find(drop.token))


class Purging(DropCase):
    def age(self, drop, hours: float) -> None:
        stamp = time.time() - hours * 3600
        os.utime(drop.path, (stamp, stamp))

    def test_expired_removed(self) -> None:
        drop = filedrop.store(self.source(), "видео")
        self.age(drop, filedrop.TTL_HOURS + 1)
        self.assertEqual(filedrop.purge(), 1)
        self.assertFalse(os.path.exists(drop.path))

    def test_fresh_kept(self) -> None:
        drop = filedrop.store(self.source(), "видео")
        self.assertEqual(filedrop.purge(), 0)
        self.assertTrue(os.path.exists(drop.path))

    def test_budget_removes_oldest_first(self) -> None:
        # Забитый диск останавливает оповещения, а они важнее скачивания.
        with mock.patch.object(filedrop, "BUDGET_MB", 0.002):
            old = filedrop.store(self.source("old.mp4", 2048), "старый")
            self.age(old, 5)
            new = filedrop.store(self.source("new.mp4", 2048), "новый")
            filedrop.purge()
            self.assertFalse(os.path.exists(old.path))
            self.assertTrue(os.path.exists(new.path))

    def test_listing_newest_first(self) -> None:
        first = filedrop.store(self.source("a.mp4"), "первый")
        self.age(first, 3)
        second = filedrop.store(self.source("b.mp4"), "второй")
        self.assertEqual([item.token for item in filedrop.listing()],
                         [second.token, first.token])

    def test_foreign_files_ignored(self) -> None:
        # В каталоге может оказаться что угодно; чужое не наше дело.
        os.makedirs(filedrop.DIRECTORY, exist_ok=True)
        stray = os.path.join(filedrop.DIRECTORY, "посторонний.txt")
        with open(stray, "wb") as handle:
            handle.write(b"x")
        self.assertEqual(filedrop.listing(), [])
        self.assertEqual(filedrop.purge(), 0)
        self.assertTrue(os.path.exists(stray))

    def test_summary_survives_empty(self) -> None:
        self.assertIn("пусто", filedrop.summary())


class PerFileLimit(DropCase):
    """Предел на один файл. Подписка его не снимает."""

    def test_oversized_refused(self) -> None:
        with mock.patch.object(filedrop, "MAX_FILE_MB", 0.001):
            source = self.source("big.mp4", 4096)
            self.assertIsNone(filedrop.store(source, "большой"))
            # Файл остаётся на месте: раздача его не приняла, и удалять
            # чужой файл она не вправе — это сделает уборка вызывающего.
            self.assertTrue(os.path.exists(source))

    def test_within_limit_accepted(self) -> None:
        with mock.patch.object(filedrop, "MAX_FILE_MB", 1):
            self.assertIsNotNone(filedrop.store(self.source(size=1024), "малый"))

    def test_predicate_matches_constant(self) -> None:
        self.assertFalse(filedrop.too_large(filedrop.MAX_FILE_MB * 1024 * 1024))
        self.assertTrue(filedrop.too_large(filedrop.MAX_FILE_MB * 1024 * 1024 + 1))


class Ownership(DropCase):
    """Кому выдана ссылка и забрали ли файл."""

    def test_owner_remembered(self) -> None:
        drop = filedrop.store(self.source(), "видео", owner="telegram:42")
        self.assertEqual(drop.owner, "telegram:42")
        self.assertEqual(filedrop.listing()[0].owner, "telegram:42")

    def test_downloads_counted(self) -> None:
        drop = filedrop.store(self.source(), "видео", owner="telegram:42")
        self.assertEqual(filedrop.listing()[0].hits, 0)
        filedrop.note_download(drop.token)
        filedrop.note_download(drop.token)
        self.assertEqual(filedrop.listing()[0].hits, 2)

    def test_garbage_token_not_counted(self) -> None:
        filedrop.note_download("не токен")
        self.assertEqual(filedrop.listing(), [])

    def test_lost_marks_do_not_break_listing(self) -> None:
        # Пометки необязательные: без них панель теряет подписи,
        # но раздача обязана работать.
        drop = filedrop.store(self.source(), "видео", owner="telegram:42")
        os.remove(os.path.join(filedrop.DIRECTORY, filedrop.INDEX_NAME))
        found = filedrop.find(drop.token)
        self.assertIsNotNone(found)
        self.assertEqual(found.owner, "")

    def test_broken_marks_do_not_break_listing(self) -> None:
        drop = filedrop.store(self.source(), "видео", owner="telegram:42")
        with open(os.path.join(filedrop.DIRECTORY, filedrop.INDEX_NAME),
                  "w", encoding="utf-8") as handle:
            handle.write("{это не json")
        self.assertIsNotNone(filedrop.find(drop.token))

    def test_index_is_not_taken_for_a_file(self) -> None:
        filedrop.store(self.source(), "видео", owner="telegram:42")
        self.assertEqual(len(filedrop.listing()), 1)


class EarlyRemoval(DropCase):
    """Досрочное отключение ссылки из панели."""

    def test_removes_file_and_marks(self) -> None:
        drop = filedrop.store(self.source(), "видео", owner="telegram:42")
        self.assertTrue(filedrop.remove(drop.token))
        self.assertFalse(os.path.exists(drop.path))
        self.assertIsNone(filedrop.find(drop.token))

    def test_unknown_token_reported(self) -> None:
        self.assertFalse(filedrop.remove("0" * 32))
        self.assertFalse(filedrop.remove("мусор"))


if __name__ == "__main__":
    unittest.main()
