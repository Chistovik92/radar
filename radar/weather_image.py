"""Погода картинкой.

Рисуется через Pillow, если он доступен. Библиотека объявлена необязательной
намеренно: она заметно утяжеляет образ, а текстовая сводка остаётся
полноценной заменой. Если Pillow или шрифтов нет, функция честно возвращает
None, и бот отправляет текст — без ошибок и без молчания.

Отдельная причина держать текст основным: картинка не прогрузится при
ограничениях мобильного интернета, а это ровно тот сценарий, ради которого
система и существует.

Оформление: крупная температура слева, состояние неба и ветер под ней,
почасовая лента внизу. Фон меняется по времени суток в той точке, где
стоит локация, — не по часам сервера: человек в другом часовом поясе
должен видеть своё небо.
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

from . import astro

log = logging.getLogger("radar.weather_image")

WIDTH = 900
HEIGHT = 620
MARGIN = 44

# Фон по времени суток: (верх, низ, подпись). Градиент задаёт настроение
# без единой картинки в образе — нарисовать полосами дешевле, чем тащить
# ассеты и следить за их лицензиями.
SKIES = {
    "night": ((22, 26, 54), (44, 44, 92), "ночь"),
    "dawn":  ((72, 62, 116), (214, 130, 116), "рассвет"),
    "day":   ((58, 120, 200), (128, 186, 236), "день"),
    "dusk":  ((54, 52, 108), (196, 110, 108), "закат"),
}

# Дневное небо светлое, ночное тёмное — один набор цветов текста не подходит
# обоим: белые подписи на голубом фоне сливаются, и почасовая лента
# становится нечитаемой ровно там, где на неё и смотрят.
PALETTES = {
    "light": {
        "text": (18, 34, 62),
        "muted": (58, 84, 124),
        "warm": (198, 106, 20),
        "cold": (26, 96, 168),
        "rain": (24, 104, 180),
        "panel_mix": (255, 255, 255),
        "panel_ratio": 0.42,
    },
    "dark": {
        "text": (255, 255, 255),
        "muted": (183, 192, 214),
        "warm": (255, 186, 92),
        "cold": (140, 200, 255),
        "rain": (128, 190, 255),
        # Панель именно затемняется: на закатном градиенте низ светло-розовый,
        # и осветлённая плашка оставляла белые подписи почти нечитаемыми.
        "panel_mix": (16, 18, 38),
        "panel_ratio": 0.45,
    },
}


def palette_for(sky: str) -> dict:
    """Светлая тема только для дневного неба — остальные достаточно тёмные."""
    return PALETTES["light" if sky == "day" else "dark"]


def available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    # Шрифты в образе не гарантированы: перебираем известные пути.
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

    # Встроенный шрифт Pillow растровый и кириллицу не покрывает: сводка
    # вышла бы из квадратиков. Возвращаем None — вызывающий откатится
    # на текст, который читается всегда.
    log.warning(
        "TTF-шрифт не найден, погода картинкой недоступна — отправляю текстом. "
        "Установите fonts-dejavu-core в образ."
    )
    return None


def _temperature_color(value: float, colors: dict) -> tuple[int, int, int]:
    if value >= 20:
        return colors["warm"]
    if value <= 0:
        return colors["cold"]
    return colors["text"]


def _blend(first, second, ratio: float):
    return tuple(
        int(first[index] + (second[index] - first[index]) * ratio) for index in range(3)
    )


# --- время суток ----------------------------------------------------------

def _minutes(value: str) -> int | None:
    """«20:31» -> 1231. None, если разобрать нечем."""
    try:
        hours, minutes = value.split(":")[:2]
        return int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return None


def sky_for(weather: Any) -> str:
    """Какое небо рисовать: ночь, рассвет, день или закат.

    Считается по местному времени локации и её же восходу с закатом —
    поэтому картинка совпадает с тем, что человек видит в окно.
    Если данных о времени нет, опираемся на признак is_day от сервиса.
    """
    now = _minutes(getattr(weather, "local_time", "") or "")
    sunrise = _minutes(getattr(weather, "sunrise", "") or "")
    sunset = _minutes(getattr(weather, "sunset", "") or "")

    if now is None or sunrise is None or sunset is None:
        return "day" if getattr(weather, "is_day", True) else "night"

    # Час вокруг восхода и заката — переходное небо.
    edge = 60
    if abs(now - sunrise) <= edge:
        return "dawn"
    if abs(now - sunset) <= edge:
        return "dusk"
    if sunrise < now < sunset:
        return "day"
    return "night"


def _gradient(draw, top_color, bottom_color) -> None:
    """Вертикальная заливка построчно — без numpy и лишних зависимостей."""
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        draw.line([(0, y), (WIDTH, y)], fill=_blend(top_color, bottom_color, ratio))


# --- луна -----------------------------------------------------------------

def _draw_moon(draw, cx: int, cy: int, radius: int, moon) -> None:
    """Луна с текущей фазой.

    Терминатор рисуется эллипсом поверх диска: ширина эллипса задаётся
    освещённостью, сторона — тем, растёт луна или убывает. Приём старый
    и даёт узнаваемый серп без единой картинки в образе.
    """
    disc = (236, 238, 248)
    dark = (34, 38, 68)

    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=disc)

    if moon.illumination > 0.98:
        return                                   # полнолуние — диск целиком
    if moon.illumination < 0.02:
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=dark)
        return                                   # новолуние — диска не видно

    # Половина диска всегда в тени. Растущая луна освещена справа.
    if moon.waxing:
        draw.pieslice([cx - radius, cy - radius, cx + radius, cy + radius],
                      90, 270, fill=dark)
    else:
        draw.pieslice([cx - radius, cy - radius, cx + radius, cy + radius],
                      270, 90, fill=dark)

    # Терминатор: до четверти эллипс доедает свет, после — возвращает его
    half = max(1, int(radius * abs(1 - 2 * moon.illumination)))
    box = [cx - half, cy - radius, cx + half, cy + radius]
    draw.ellipse(box, fill=dark if moon.illumination < 0.5 else disc)


def _draw_sun(draw, cx: int, cy: int, radius: int) -> None:
    from math import cos, radians, sin

    for degree in range(0, 360, 30):
        angle = radians(degree)
        draw.line(
            [(cx + cos(angle) * (radius + 10), cy + sin(angle) * (radius + 10)),
             (cx + cos(angle) * (radius + 26), cy + sin(angle) * (radius + 26))],
            fill=(255, 226, 148), width=4,
        )
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 fill=(255, 214, 102))


# --- ветер ----------------------------------------------------------------

def _draw_wind_arrow(draw, cx: int, cy: int, size: int, degrees: float,
                     color) -> None:
    """Стрелка, показывающая, КУДА дует ветер.

    Метеорологическое направление задаёт, откуда ветер, поэтому стрелка
    поворачивается на 180 градусов: человеку понятнее, куда понесёт дым.
    """
    from math import cos, radians, sin

    angle = radians((degrees + 180) % 360)
    # Экранные координаты: ось Y направлена вниз, ноль — на север.
    dx, dy = sin(angle), -cos(angle)
    px, py = -dy, dx                             # перпендикуляр

    tip = (cx + dx * size, cy + dy * size)
    tail = (cx - dx * size, cy - dy * size)
    left = (tip[0] - dx * size * 0.9 + px * size * 0.55,
            tip[1] - dy * size * 0.9 + py * size * 0.55)
    right = (tip[0] - dx * size * 0.9 - px * size * 0.55,
             tip[1] - dy * size * 0.9 - py * size * 0.55)

    draw.line([tail, tip], fill=color, width=3)
    draw.polygon([tip, left, right], fill=color)


# --- сборка ---------------------------------------------------------------

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
        big = _font(104, bold=True)
        head = _font(30, bold=True)
        normal = _font(24)
        small = _font(20)
        tiny = _font(17)
        if None in (big, head, normal, small, tiny):
            return None

        sky = sky_for(weather)
        top_color, bottom_color, sky_name = SKIES[sky]
        colors = palette_for(sky)
        text, muted = colors["text"], colors["muted"]

        image = Image.new("RGB", (WIDTH, HEIGHT), top_color)
        draw = ImageDraw.Draw(image)
        _gradient(draw, top_color, bottom_color)

        # Заголовок: название локации без разметки
        clean_title = _strip_tags(title) or "Погода"
        draw.text((MARGIN, MARGIN - 12), clean_title[:46], font=head, fill=text)

        stamp = getattr(weather, "local_time", "") or ""
        if stamp:
            draw.text((MARGIN, MARGIN + 28), f"{stamp} · {sky_name}",
                      font=tiny, fill=muted)

        # Крупная температура
        temperature = weather.temp if weather.temp is not None else 0.0
        draw.text((MARGIN - 6, MARGIN + 62), f"{round(temperature):d}°",
                  font=big, fill=_temperature_color(temperature, colors))

        cursor = MARGIN + 190
        if weather.feels is not None:
            draw.text((MARGIN, cursor), f"ощущается как {round(weather.feels):d}°",
                      font=normal, fill=muted)
            cursor += 38

        name, _icon = _describe(weather)
        if name:
            draw.text((MARGIN, cursor), name.capitalize(), font=normal, fill=text)
            cursor += 40

        # Ветер: стрелка, скорость, откуда дует, словесная оценка силы
        if weather.wind is not None:
            arrow_x = MARGIN + 14
            _draw_wind_arrow(draw, arrow_x, cursor + 13, 14,
                             float(weather.wind_dir or 0), text)
            parts = [f"{weather.wind:.0f} м/с"]
            direction = astro.wind_name(weather.wind_dir)
            if direction:
                parts.append(direction)
            force = astro.beaufort(weather.wind)
            if force:
                parts.append(force)
            draw.text((arrow_x + 30, cursor), ", ".join(parts), font=small, fill=text)
            cursor += 32
            if weather.gusts is not None and weather.gusts > (weather.wind or 0) + 2:
                draw.text((arrow_x + 30, cursor),
                          f"порывы до {weather.gusts:.0f} м/с", font=tiny, fill=muted)
                cursor += 28

        details = []
        if weather.humidity is not None:
            details.append(f"влажность {weather.humidity}%")
        if weather.pressure is not None:
            details.append(f"{weather.pressure * 0.75006:.0f} мм рт. ст.")
        if details:
            draw.text((MARGIN, cursor), " · ".join(details), font=tiny, fill=muted)

        # Светило: ночью и в сумерках — луна с фазой, днём — солнце
        if sky == "day":
            _draw_sun(draw, WIDTH - 160, 186, 58)
        else:
            moon = astro.moon()
            _draw_moon(draw, WIDTH - 160, 186, 62, moon)
            _centered(draw, f"{moon.name}, {moon.illumination * 100:.0f}%",
                      WIDTH - 160, 262, tiny, muted)

        if weather.sunrise and weather.sunset:
            _centered(draw, f"↑ {weather.sunrise}   ↓ {weather.sunset}",
                      WIDTH - 160, 296, small, text)

        panel = _blend(bottom_color, colors["panel_mix"], colors["panel_ratio"])
        _draw_hourly(draw, weather.hourly[:8], HEIGHT - 150, normal, small,
                     panel, colors)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001
        log.exception("Не удалось нарисовать погоду — отправлю текстом")
        return None


def _centered(draw, text: str, cx: int, y: int, font, fill) -> None:
    width = draw.textlength(text, font=font)
    draw.text((cx - width / 2, y), text, font=font, fill=fill)


def _describe(weather: Any) -> tuple[str, str]:
    from .weather import describe

    return describe(getattr(weather, "code", None), getattr(weather, "is_day", True))


def _draw_hourly(draw, hours, top: int, font, small, panel, colors) -> None:
    """Почасовая лента: время, температура, вероятность осадков."""
    if not hours:
        return

    draw.rounded_rectangle(
        [MARGIN - 16, top - 22, WIDTH - MARGIN + 16, HEIGHT - MARGIN + 10],
        radius=26, fill=panel,
    )

    step = (WIDTH - 2 * MARGIN) / len(hours)
    for index, item in enumerate(hours):
        x = int(MARGIN + step * index + step / 2)
        _centered(draw, "сейчас" if index == 0 else item.label, x, top, small,
                  colors["muted"])
        _centered(draw, f"{round(item.temp):d}°", x, top + 30, font,
                  _temperature_color(item.temp, colors))
        if item.probability >= 20:
            _centered(draw, f"{item.probability}%", x, top + 66, small,
                      colors["rain"])


def _strip_tags(text: str) -> str:
    result = []
    inside = False
    for char in text:
        if char == "<":
            inside = True
        elif char == ">":
            inside = False
        elif not inside:
            result.append(char)
    return "".join(result).strip()
