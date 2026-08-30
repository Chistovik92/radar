#!/usr/bin/env python3
"""Часовой пояс пользователя: разбор, подписи, местное время.

До 4.8.4.4 время было общим на всю систему. «Погода в 8:00» означала
восемь утра у сервера, а не у человека, и для пользователя из другого
пояса приходила ночью. Здесь закреплено главное: от одного якоря в UTC
каждый получатель получает своё местное время, а не серверное.

Отдельно проверяются подписи. По-русски отсчёт идёт от Москвы, по-английски
от Гринвича — это не украшение: «UTC+5» человеку из Саратова ничего
не сообщает, он мыслит в «МСК+2».
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
from datetime import datetime, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import timezones  # noqa: E402

# Полдень по Гринвичу — удобный якорь: ни одна разумная зона не переносит
# его на другие сутки, и проверки не спотыкаются о смену даты.
NOON = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


class Parsing(unittest.TestCase):
    def test_reads_positive(self) -> None:
        self.assertEqual(timezones.parse("+03:00"), 180)

    def test_reads_negative(self) -> None:
        self.assertEqual(timezones.parse("-05:30"), -330)

    def test_reads_zero(self) -> None:
        self.assertEqual(timezones.parse("+00:00"), 0)

    def test_empty_is_not_set(self) -> None:
        self.assertIsNone(timezones.parse(""))
        self.assertIsNone(timezones.parse(None))

    def test_rejects_garbage(self) -> None:
        # Значение приходит из callback_data, а её подделать тривиально.
        for value in ("08:00", "+3", "три часа", "+25:00", "-13:00", "+99:99"):
            with self.subTest(value=value):
                self.assertIsNone(timezones.parse(value))

    def test_round_trip(self) -> None:
        for minutes in (-720, -330, 0, 180, 345, 840):
            with self.subTest(minutes=minutes):
                self.assertEqual(timezones.parse(timezones.render(minutes)), minutes)


class Labels(unittest.TestCase):
    def test_russian_counts_from_moscow(self) -> None:
        self.assertEqual(timezones.label(180, "ru"), "МСК")
        self.assertEqual(timezones.label(240, "ru"), "МСК+1")
        self.assertEqual(timezones.label(120, "ru"), "МСК-1")
        self.assertEqual(timezones.label(0, "ru"), "МСК-3")

    def test_english_counts_from_utc(self) -> None:
        self.assertEqual(timezones.label(0, "en"), "UTC")
        self.assertEqual(timezones.label(180, "en"), "UTC+3")
        self.assertEqual(timezones.label(-300, "en"), "UTC-5")

    def test_fractional_offsets_shown_with_minutes(self) -> None:
        self.assertEqual(timezones.label(330, "en"), "UTC+5:30")
        self.assertEqual(timezones.label(345, "en"), "UTC+5:45")

    def test_unknown_language_falls_back_to_russian(self) -> None:
        self.assertEqual(timezones.label(180, ""), "МСК")


class LocalTime(unittest.TestCase):
    def test_offset_applied(self) -> None:
        local = timezones.local_now({"tz": "+05:00"}, NOON)
        self.assertEqual((local.hour, local.minute), (17, 0))

    def test_negative_offset_applied(self) -> None:
        local = timezones.local_now({"tz": "-04:00"}, NOON)
        self.assertEqual((local.hour, local.minute), (8, 0))

    def test_fractional_offset_applied(self) -> None:
        local = timezones.local_now({"tz": "+05:30"}, NOON)
        self.assertEqual((local.hour, local.minute), (17, 30))

    def test_result_is_naive(self) -> None:
        # Весь код вокруг сравнивает часы и минуты; осведомлённая о поясе
        # дата там только мешала бы.
        self.assertIsNone(timezones.local_now({"tz": "+03:00"}, NOON).tzinfo)

    def test_naive_anchor_treated_as_utc(self) -> None:
        naive = NOON.replace(tzinfo=None)
        self.assertEqual(
            timezones.local_now({"tz": "+02:00"}, naive).hour, 14)

    def test_two_users_get_different_hours(self) -> None:
        # Ровно ради этого всё и затевалось: один якорь, разное местное время.
        east = timezones.local_now({"tz": "+07:00"}, NOON)
        west = timezones.local_now({"tz": "-03:00"}, NOON)
        self.assertEqual(east.hour - west.hour, 10)

    def test_unset_falls_back_to_server(self) -> None:
        with mock.patch.object(timezones, "server_offset", return_value=180):
            self.assertEqual(timezones.local_now({}, NOON).hour, 15)
            self.assertEqual(timezones.local_now({"tz": ""}, NOON).hour, 15)

    def test_garbage_falls_back_to_server(self) -> None:
        # Поведение обязано остаться прежним, а не превратиться в UTC.
        with mock.patch.object(timezones, "server_offset", return_value=180):
            self.assertEqual(timezones.local_now({"tz": "мусор"}, NOON).hour, 15)


class Choices(unittest.TestCase):
    def test_whole_hours_cover_the_world(self) -> None:
        self.assertEqual(timezones.WHOLE_HOURS[0], -12 * 60)
        self.assertEqual(timezones.WHOLE_HOURS[-1], 14 * 60)
        self.assertIn(timezones.MOSCOW, timezones.WHOLE_HOURS)

    def test_every_choice_survives_round_trip(self) -> None:
        for minutes in timezones.WHOLE_HOURS + timezones.FRACTIONAL:
            with self.subTest(minutes=minutes):
                self.assertEqual(timezones.parse(timezones.render(minutes)), minutes)

    def test_fractional_are_not_whole_hours(self) -> None:
        for minutes in timezones.FRACTIONAL:
            with self.subTest(minutes=minutes):
                self.assertNotEqual(minutes % 60, 0)

    def test_chosen_reports_explicit_choice(self) -> None:
        self.assertTrue(timezones.chosen({"tz": "+03:00"}))
        self.assertFalse(timezones.chosen({"tz": ""}))
        self.assertFalse(timezones.chosen(None))


if __name__ == "__main__":
    unittest.main()
