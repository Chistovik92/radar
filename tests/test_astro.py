#!/usr/bin/env python3
"""Фаза луны, роза ветров и выбор неба по времени суток."""

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import astro, weather_image  # noqa: E402


def at(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestMoon(unittest.TestCase):
    """Сверка с настоящими новолуниями и полнолуниями."""

    def test_known_new_moon(self):
        # Новолуние 13 августа 2026
        moon = astro.moon(at(2026, 8, 13))
        self.assertLess(moon.illumination, 0.03)

    def test_known_full_moon(self):
        # Полнолуние 28 августа 2026
        moon = astro.moon(at(2026, 8, 28))
        self.assertGreater(moon.illumination, 0.97)

    def test_quarter_is_half_lit(self):
        moon = astro.moon(at(2026, 8, 20))
        self.assertGreater(moon.illumination, 0.35)
        self.assertLess(moon.illumination, 0.75)

    def test_waxing_then_waning(self):
        self.assertTrue(astro.moon(at(2026, 8, 20)).waxing)
        self.assertFalse(astro.moon(at(2026, 9, 5)).waxing)

    def test_cycle_length(self):
        """Через синодический месяц фаза повторяется."""
        first = astro.moon(at(2026, 1, 10))
        later = astro.moon(datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
                           .fromtimestamp(
                               at(2026, 1, 10).timestamp() + astro.SYNODIC * 86400,
                               tz=timezone.utc))
        self.assertAlmostEqual(first.phase, later.phase, places=2)

    def test_naive_datetime_accepted(self):
        moon = astro.moon(datetime(2026, 8, 28, 12))
        self.assertGreater(moon.illumination, 0.9)

    def test_phase_in_range(self):
        for day in range(1, 30):
            moon = astro.moon(at(2026, 6, day))
            self.assertGreaterEqual(moon.phase, 0.0)
            self.assertLessEqual(moon.phase, 1.0)
            self.assertTrue(moon.name)


class TestWind(unittest.TestCase):
    def test_cardinal_directions(self):
        self.assertEqual(astro.wind_name(0), "северный")
        self.assertEqual(astro.wind_name(90), "восточный")
        self.assertEqual(astro.wind_name(180), "южный")
        self.assertEqual(astro.wind_name(270), "западный")

    def test_wraps_around(self):
        self.assertEqual(astro.wind_sector(350), astro.wind_sector(0))
        self.assertEqual(astro.wind_sector(360), 0)
        self.assertEqual(astro.wind_sector(-90), astro.wind_sector(270))

    def test_short_labels(self):
        self.assertEqual(astro.wind_short(225), "ЮЗ")

    def test_missing_direction(self):
        self.assertIsNone(astro.wind_sector(None))
        self.assertEqual(astro.wind_name(None), "")

    def test_beaufort(self):
        self.assertEqual(astro.beaufort(0.5), "штиль")
        self.assertEqual(astro.beaufort(5), "умеренный")
        self.assertEqual(astro.beaufort(25), "штормовой")
        self.assertEqual(astro.beaufort(None), "")


class FakeWeather:
    def __init__(self, local_time="", sunrise="", sunset="", is_day=True):
        self.local_time = local_time
        self.sunrise = sunrise
        self.sunset = sunset
        self.is_day = is_day


class TestSky(unittest.TestCase):
    """Небо выбирается по времени локации, а не по часам сервера."""

    def sky(self, now):
        return weather_image.sky_for(
            FakeWeather(local_time=now, sunrise="05:47", sunset="20:11")
        )

    def test_day(self):
        self.assertEqual(self.sky("14:00"), "day")

    def test_night(self):
        self.assertEqual(self.sky("01:30"), "night")
        self.assertEqual(self.sky("23:50"), "night")

    def test_dawn_window(self):
        self.assertEqual(self.sky("05:50"), "dawn")
        self.assertEqual(self.sky("05:00"), "dawn")

    def test_dusk_window(self):
        self.assertEqual(self.sky("20:05"), "dusk")
        self.assertEqual(self.sky("20:55"), "dusk")

    def test_falls_back_to_is_day(self):
        """Без времени и восхода опираемся на признак сервиса."""
        self.assertEqual(weather_image.sky_for(FakeWeather(is_day=True)), "day")
        self.assertEqual(weather_image.sky_for(FakeWeather(is_day=False)), "night")

    def test_broken_time_does_not_crash(self):
        self.assertIn(
            weather_image.sky_for(FakeWeather(local_time="не время",
                                              sunrise="05:47", sunset="20:11")),
            ("day", "night"),
        )

    def test_every_sky_has_palette(self):
        for name in weather_image.SKIES:
            colors = weather_image.palette_for(name)
            self.assertIn("text", colors)
            self.assertIn("panel_ratio", colors)

    def test_day_palette_is_dark_text(self):
        """На светлом небе подписи должны быть тёмными, иначе не прочесть."""
        light = weather_image.palette_for("day")["text"]
        dark = weather_image.palette_for("night")["text"]
        self.assertLess(sum(light), sum(dark))


class TestIcons(unittest.TestCase):
    """Значки рисуются примитивами: эмодзи в DejaVu нет, и они выводились
    пустыми квадратами — именно так «📍» превращалось в прямоугольник."""

    def canvas(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("Pillow не установлен")
        image = Image.new("RGB", (200, 200), (20, 24, 50))
        return image, ImageDraw.Draw(image)

    def test_every_code_draws_something(self):
        """Ни один код погоды не должен оставлять пустое место."""
        for code in (0, 1, 2, 3, 45, 61, 63, 71, 75, 95, 999, None):
            with self.subTest(code=code):
                image, draw = self.canvas()
                before = list(image.getdata())
                weather_image.weather_icon(
                    draw, 100, 100, 80, code, True, (20, 24, 50)
                )
                self.assertNotEqual(list(image.getdata()), before)

    def test_night_icon_differs_from_day(self):
        first, draw = self.canvas()
        weather_image.weather_icon(draw, 100, 100, 80, 0, True, (20, 24, 50))
        second, draw2 = self.canvas()
        weather_image.weather_icon(draw2, 100, 100, 80, 0, False, (20, 24, 50))
        self.assertNotEqual(list(first.getdata()), list(second.getdata()))

    def test_pin_drawn(self):
        image, draw = self.canvas()
        before = list(image.getdata())
        weather_image._pin(draw, 10, 10, 26, (255, 255, 255), (20, 24, 50))
        self.assertNotEqual(list(image.getdata()), before)

    def test_background_at_follows_gradient(self):
        top, bottom = (0, 0, 0), (100, 100, 100)
        self.assertEqual(weather_image.background_at(0, top, bottom), top)
        low = weather_image.background_at(weather_image.HEIGHT, top, bottom)
        self.assertEqual(low, bottom)


if __name__ == "__main__":
    unittest.main(verbosity=2)
