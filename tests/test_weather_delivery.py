#!/usr/bin/env python3
"""Выдача погоды: картинка или текст — одинаково на всех путях.

Ошибка, ради которой написаны тесты: выбор вида погоды жил только
в фоновой рассылке, а кнопка «Обновить погоду» слала текст всегда.
Настройка была, показывала «картинка», и не работала.
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import features, weather, weather_image  # noqa: E402


def sample() -> weather.Weather:
    """Настоящая структура, а не заглушка: текстовый запасной путь
    обязан отрабатывать на тех же данных, что приходят из сети."""
    return weather.Weather(ok=True, temp=21.0, code=1, is_day=True)


def run(coro):
    return asyncio.run(coro)


class TestDeliver(unittest.TestCase):
    """Выбор формата не должен зависеть от того, откуда пришёл запрос."""

    def setUp(self):
        self.sent_html = []
        self.sent_photo = []
        features.set_local("weather_image", True)

    def _deliver(self, user, picture=b"PNG"):
        with mock.patch.object(weather_image, "render", return_value=picture), \
             mock.patch("radar.tg.send_html", side_effect=self._html), \
             mock.patch("radar.tg.bot") as fake_bot:
            fake_bot.send_photo = self._photo
            run(weather.deliver(1, sample(), "Чапаева, 12", None, user))

    async def _html(self, *args, **kwargs):
        self.sent_html.append(args)
        return True

    async def _photo(self, *args, **kwargs):
        self.sent_photo.append(kwargs)
        return True

    def test_picture_when_chosen(self):
        self._deliver({"weather_format": "image"})
        self.assertEqual(len(self.sent_photo), 1)
        self.assertEqual(self.sent_html, [])

    def test_text_when_chosen(self):
        self._deliver({"weather_format": "text"})
        self.assertEqual(self.sent_photo, [])
        self.assertEqual(len(self.sent_html), 1)

    def test_default_is_picture_when_flag_on(self):
        """Пустая настройка — не повод игнорировать включённый флаг."""
        self._deliver({})
        self.assertEqual(len(self.sent_photo), 1)

    def test_flag_off_forces_text(self):
        features.set_local("weather_image", False)
        self._deliver({"weather_format": "image"})
        self.assertEqual(self.sent_photo, [])
        self.assertEqual(len(self.sent_html), 1)

    def test_render_failure_falls_back_to_text(self):
        """Нет Pillow или шрифта — сводка всё равно должна дойти."""
        self._deliver({"weather_format": "image"}, picture=None)
        self.assertEqual(self.sent_photo, [])
        self.assertEqual(len(self.sent_html), 1)

    def test_send_failure_falls_back_to_text(self):
        """Телеграм отверг картинку — молчания быть не должно."""
        async def boom(*args, **kwargs):
            raise RuntimeError("отказ")

        with mock.patch.object(weather_image, "render", return_value=b"PNG"), \
             mock.patch("radar.tg.send_html", side_effect=self._html), \
             mock.patch("radar.tg.bot") as fake_bot:
            fake_bot.send_photo = boom
            run(weather.deliver(1, sample(), "Чапаева, 12", None,
                                {"weather_format": "image"}))
        self.assertEqual(len(self.sent_html), 1)

    def test_no_user_record(self):
        self._deliver(None)
        self.assertEqual(len(self.sent_photo), 1)


class TestFontFallback(unittest.TestCase):
    def test_missing_font_returns_none(self):
        """Без TTF кириллица вышла бы квадратиками — лучше текст."""
        try:
            from PIL import ImageFont  # noqa: F401
        except ImportError:
            self.skipTest("Pillow не установлен")

        with mock.patch("PIL.ImageFont.truetype", side_effect=OSError):
            self.assertIsNone(weather_image._font(24))

    def test_render_without_font_returns_none(self):
        try:
            from PIL import ImageFont  # noqa: F401
        except ImportError:
            self.skipTest("Pillow не установлен")

        with mock.patch("PIL.ImageFont.truetype", side_effect=OSError):
            self.assertIsNone(weather_image.render(sample(), "Чапаева"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
