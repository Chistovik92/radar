"""Погода картинкой.

Рисуется через Pillow, если он доступен. Библиотека объявлена необязательной
намеренно: она заметно утяжеляет образ, а текстовая сводка остаётся полноценной
заменой. Если Pillow нет, функция честно возвращает None, и бот отправляет
текст — без ошибок и без молчания.

Отдельная причина держать текст основным: картинка не прогрузится при
ограничениях мобильного интернета, а это ровно тот сценарий, ради которого
система и существует.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import io
import logging
from typing import Any

log = logging.getLogger("radar.weather_image")

WIDTH = 900
HEIGHT = 560
MARGIN = 40

BACKGROUND = (24, 28, 38)
PANEL = (33, 39, 52)
TEXT = (236, 240, 247)
MUTED = (146, 156, 175)
ACCENT = (94, 168, 255)
WARM = (255, 176, 92)
COLD = (120, 190, 255)


def available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    # Шрифты в образе не гарантированы: перебираем известные пути,
    # в крайнем случае берём встроенный.
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _temperature_color(value: float) -> tuple[int, int, int]:
    if value >= 20:
        return WARM
    if value <= 0:
        return COLD
    return ACCENT


def render(weather: Any, title: str = "") -> bytes | None:
    """Возвращает PNG или None, если рисовать нечем."""
    if not available():
        return None
    if not getattr(weather, "ok", False):
        return None

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    try:
        image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        draw = ImageDraw.Draw(image)

        big = _font(96, bold=True)
        head = _font(30, bold=True)
        normal = _font(24)
        small = _font(20)

        # Заголовок: название локации без разметки
        clean_title = _strip_tags(title) or "Погода"
        draw.text((MARGIN, MARGIN - 10), clean_title[:48], font=head, fill=TEXT)

        # Текущая температура
        temperature = weather.temp if weather.temp is not None else 0.0
        draw.text(
            (MARGIN, MARGIN + 40),
            f"{round(temperature):+d}°".replace("+", ""),
            font=big,
            fill=_temperature_color(temperature),
        )

        from .weather import describe as describe_code

        name, _icon = describe_code(weather.code, weather.is_day)
        draw.text((MARGIN + 230, MARGIN + 70), name.capitalize(), font=normal, fill=TEXT)

        details = []
        if weather.feels is not None and weather.temp is not None:
            if abs(weather.feels - weather.temp) >= 1:
                details.append(f"ощущается {round(weather.feels):+d}°".replace("+", ""))
        if weather.wind is not None:
            details.append(f"ветер {weather.wind:.0f} м/с")
        if weather.humidity is not None:
            details.append(f"влажность {weather.humidity}%")
        if details:
            draw.text(
                (MARGIN + 230, MARGIN + 108),
                " · ".join(details), font=small, fill=MUTED,
            )

        # График по часам
        hours = list(weather.hourly)[:8]
        if hours:
            _draw_hourly(draw, hours, top=MARGIN + 180)

        # Прогноз по дням
        days = list(weather.daily)[:3]
        if days:
            _draw_daily(draw, days, top=HEIGHT - 130, font=normal, small=small)

        if weather.sunrise and weather.sunset:
            draw.text(
                (MARGIN, HEIGHT - 40),
                f"Восход {weather.sunrise}    Закат {weather.sunset}",
                font=small, fill=MUTED,
            )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001
        log.warning("Не удалось нарисовать погоду", exc_info=True)
        return None


def _draw_hourly(draw, hours, top: int) -> None:
    from PIL import ImageDraw  # noqa: F401

    left = MARGIN
    right = WIDTH - MARGIN
    height = 150
    step = (right - left) / max(1, len(hours) - 1) if len(hours) > 1 else 0

    values = [item.temp for item in hours]
    low, high = min(values), max(values)
    span = max(1.0, high - low)

    draw.rounded_rectangle(
        [left - 15, top - 20, right + 15, top + height + 45], 14, fill=PANEL
    )

    points = []
    for index, item in enumerate(hours):
        x = left + step * index
        y = top + height - (item.temp - low) / span * height
        points.append((x, y))

    if len(points) > 1:
        draw.line(points, fill=ACCENT, width=3, joint="curve")

    label = _font(18)
    for (x, y), item in zip(points, hours):
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=_temperature_color(item.temp))
        draw.text(
            (x - 18, y - 32),
            f"{round(item.temp):+d}°".replace("+", ""),
            font=label, fill=TEXT,
        )
        draw.text((x - 16, top + height + 14), item.label, font=label, fill=MUTED)
        if item.probability >= 20:
            draw.text(
                (x - 16, top + height + 34),
                f"{item.probability}%", font=_font(15), fill=COLD,
            )


def _draw_daily(draw, days, top: int, font, small) -> None:
    left = MARGIN
    column = (WIDTH - 2 * MARGIN) / max(1, len(days))
    for index, day in enumerate(days):
        x = left + column * index
        draw.text((x, top), day.label, font=small, fill=MUTED)
        draw.text(
            (x, top + 26),
            f"{round(day.high):+d}° … {round(day.low):+d}°".replace("+", ""),
            font=font, fill=TEXT,
        )


def _strip_tags(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text or "").strip()
