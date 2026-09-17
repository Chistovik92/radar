#!/usr/bin/env python3
"""Облачное хранилище музыки: без сети (с 4.9.9).

Сеть в офлайн-тестах не поднимается, поэтому проверяется всё, что решает
модуль ДО запроса и ПОСЛЕ ответа: имя файла, адрес, разбор ответа о месте
и поведение кэша. Ровно этого хватает, чтобы ошибка в пути или в разборе
квоты не уехала на сервер.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import cloudstore, features, music  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class NameTests(unittest.TestCase):
    """Имя уходит в URL, поэтому проверяется до сети, а не после."""

    def test_plain_name_accepted(self):
        self.assertTrue(cloudstore.valid_name("a1b2c3d4.mp3"))
        self.assertTrue(cloudstore.valid_name("a1b2c3d4"))

    def test_traversal_rejected(self):
        for bad in ("../../etc/passwd", "a/b.mp3", "..", "a b.mp3",
                    "a%2fb.mp3", "", "a.mp3?x=1"):
            self.assertFalse(cloudstore.valid_name(bad), bad)

    def test_url_built_from_base(self):
        with mock.patch.object(cloudstore, "base_url",
                               return_value="http://rclone:8080/music"):
            self.assertEqual(cloudstore.url_for("ab12.opus"),
                             "http://rclone:8080/music/ab12.opus")

    def test_no_url_without_base(self):
        with mock.patch.object(cloudstore, "base_url", return_value=""):
            self.assertEqual(cloudstore.url_for("ab12.opus"), "")


class QuotaTests(unittest.TestCase):
    """Разбор PROPFIND: облака отвечают по-разному, и «не сказал» — не ноль."""

    def test_both_values_parsed(self):
        body = (b'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">'
                b"<d:response><d:propstat><d:prop>"
                b"<d:quota-available-bytes>500</d:quota-available-bytes>"
                b"<d:quota-used-bytes>1500</d:quota-used-bytes>"
                b"</d:prop></d:propstat></d:response></d:multistatus>")
        self.assertEqual(cloudstore.parse_quota(body), (1500, 500))

    def test_missing_values_are_unknown(self):
        used, available = cloudstore.parse_quota(b"<d:multistatus/>")
        self.assertEqual((used, available), (-1, -1))

    def test_negative_available_is_unknown(self):
        """Отрицательное по стандарту означает «не ограничено»
        или «неизвестно» — показывать как объём нельзя."""
        body = (b"<d:quota-available-bytes>-3</d:quota-available-bytes>"
                b"<d:quota-used-bytes>10</d:quota-used-bytes>")
        self.assertEqual(cloudstore.parse_quota(body), (10, -1))


class EnabledTests(unittest.TestCase):
    def tearDown(self) -> None:
        features.apply({})

    def test_flag_without_address_is_off(self):
        features.set_local("music_cloud", True)
        with mock.patch.object(cloudstore, "base_url", return_value=""):
            self.assertFalse(cloudstore.enabled())

    def test_address_without_flag_is_off(self):
        features.set_local("music_cloud", False)
        with mock.patch.object(cloudstore, "base_url",
                               return_value="http://rclone:8080"):
            self.assertFalse(cloudstore.enabled())

    def test_both_on(self):
        features.set_local("music_cloud", True)
        with mock.patch.object(cloudstore, "base_url",
                               return_value="http://rclone:8080"):
            self.assertTrue(cloudstore.enabled())


class CacheTests(unittest.TestCase):
    """Кэш можно потерять целиком без последствий, но не дать ему расти."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="radar-music-")
        self.patched = mock.patch.multiple(
            music,
            DIRECTORY=self.tmp,
            CACHE_DIRECTORY=os.path.join(self.tmp, "cache"),
        )
        self.patched.start()
        os.makedirs(music.CACHE_DIRECTORY, exist_ok=True)

    def tearDown(self) -> None:
        self.patched.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, size: int, age: float = 0.0) -> str:
        path = os.path.join(music.CACHE_DIRECTORY, name)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        if age:
            stamp = os.path.getatime(path) - age
            os.utime(path, (stamp, stamp))
        return path

    def test_size_counted(self):
        self._write("a.mp3", 1000)
        self._write("b.mp3", 2000)
        self.assertEqual(music.cache_size(), 3000)

    def test_within_budget_untouched(self):
        self._write("a.mp3", 1000)
        self.assertEqual(music.trim_cache(budget_mb=1), 0)
        self.assertEqual(music.cache_size(), 1000)

    def test_oldest_removed_first(self):
        fresh = self._write("fresh.mp3", 700 * 1024)
        stale = self._write("stale.mp3", 700 * 1024, age=3600)

        music.trim_cache(budget_mb=1)

        self.assertTrue(os.path.isfile(fresh))
        self.assertFalse(os.path.isfile(stale))

    def test_missing_directory_is_not_an_error(self):
        shutil.rmtree(music.CACHE_DIRECTORY, ignore_errors=True)
        self.assertEqual(music.cache_size(), 0)
        self.assertEqual(music.trim_cache(), 0)


class StoreTests(unittest.TestCase):
    """Отказ облака не должен означать потерю трека."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="radar-music-")
        self.patched = mock.patch.multiple(
            music,
            DIRECTORY=self.tmp,
            CACHE_DIRECTORY=os.path.join(self.tmp, "cache"),
        )
        self.patched.start()

    def tearDown(self) -> None:
        self.patched.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_local_when_cloud_off(self):
        with mock.patch.object(cloudstore, "enabled", return_value=False):
            where, note = run(music.store("ab12", ".mp3", b"data"))
        self.assertEqual((where, note), ("local", ""))
        self.assertTrue(os.path.isfile(music.local_path("ab12", ".mp3")))

    def test_cloud_failure_keeps_file_and_explains(self):
        async def refuse(_name, _payload):
            return False, "Хранилище не отвечает."

        with mock.patch.object(cloudstore, "enabled", return_value=True), \
                mock.patch.object(cloudstore, "put", refuse):
            where, note = run(music.store("ab12", ".mp3", b"data"))

        self.assertEqual(where, "local")
        self.assertIn("не отвечает", note)
        self.assertTrue(os.path.isfile(music.local_path("ab12", ".mp3")))

    def test_cloud_success_moves_file_to_cache(self):
        async def accept(_name, _payload):
            return True, ""

        with mock.patch.object(cloudstore, "enabled", return_value=True), \
                mock.patch.object(cloudstore, "put", accept):
            where, note = run(music.store("ab12", ".mp3", b"data"))

        self.assertEqual((where, note), ("cloud", ""))
        self.assertFalse(os.path.isfile(music.local_path("ab12", ".mp3")))
        self.assertTrue(os.path.isfile(music.cache_path("ab12", ".mp3")))

    def test_ensure_local_prefers_disk(self):
        os.makedirs(self.tmp, exist_ok=True)
        with open(music.local_path("ab12", ".mp3"), "wb") as handle:
            handle.write(b"data")

        async def explode(_name):
            raise AssertionError("в облако ходить не требовалось")

        with mock.patch.object(cloudstore, "enabled", return_value=True), \
                mock.patch.object(cloudstore, "fetch", explode):
            path, reason = run(music.ensure_local({"id": "ab12", "ext": ".mp3"}))

        self.assertEqual(reason, "")
        self.assertTrue(path.endswith("ab12.mp3"))

    def test_ensure_local_downloads_once(self):
        calls = []

        async def give(name):
            calls.append(name)
            return True, b"payload"

        with mock.patch.object(cloudstore, "enabled", return_value=True), \
                mock.patch.object(cloudstore, "fetch", give):
            first, _ = run(music.ensure_local({"id": "ab12", "ext": ".mp3"}))
            second, _ = run(music.ensure_local({"id": "ab12", "ext": ".mp3"}))

        self.assertEqual(first, second)
        self.assertEqual(calls, ["ab12.mp3"], "второй раз скачивать не нужно")

    def test_ensure_local_explains_loss(self):
        async def missing(_name):
            return False, "Файла нет в хранилище."

        with mock.patch.object(cloudstore, "enabled", return_value=True), \
                mock.patch.object(cloudstore, "fetch", missing):
            path, reason = run(music.ensure_local({"id": "ab12", "ext": ".mp3"}))

        self.assertEqual(path, "")
        self.assertIn("хранилище", reason)


if __name__ == "__main__":
    unittest.main()
