"""Чистые утилиты: разметка, нормализация адресов, геометрия, кластеризация.

Модуль намеренно не импортирует внешние пакеты — его можно тестировать
без установленного aiogram/aiohttp/google-genai.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
import math
import re
from typing import Any, Iterable, Sequence

TG_LIMIT = 3800

# --------------------------------------------------------------------------
#  Разметка Telegram (HTML)
# --------------------------------------------------------------------------

_CODE_BLOCK = re.compile(r"```(?:[\w+-]*)\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_HEADER = re.compile(r"(?m)^\s{0,3}#{1,6}\s*(.+)$")
_TAG = re.compile(r"<[^>]+>")

def esc(text: Any) -> str:
    """Экранирует текст для Telegram-HTML."""
    return html.escape(str(text), quote=False)


def esc_attr(value: Any) -> str:
    """Экранирует значение HTML-атрибута.

    Отличается от esc() тем, что экранирует кавычки: незакрытая кавычка
    в URL разрывает атрибут href, и Telegram отвергает всё сообщение.
    """
    return html.escape(str(value), quote=True)


def md_to_html(text: str) -> str:
    """Переводит Markdown-ответ модели в безопасный Telegram-HTML."""
    stash: list[str] = []

    def keep(match: re.Match, tag: str) -> str:
        stash.append(f"<{tag}>{html.escape(match.group(1))}</{tag}>")
        return f"\x00{len(stash) - 1}\x00"

    text = _CODE_BLOCK.sub(lambda m: keep(m, "pre"), text)
    text = _INLINE_CODE.sub(lambda m: keep(m, "code"), text)
    text = html.escape(text, quote=False)
    text = _HEADER.sub(r"<b>\1</b>", text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def strip_tags(text: str) -> str:
    return html.unescape(_TAG.sub("", text))


def split_text(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Режет длинное сообщение по строкам, не превышая лимит Telegram."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(buf) + len(line) > limit:
            parts.append(buf)
            buf = line
        else:
            buf += line
    if buf:
        parts.append(buf)
    return parts


# --------------------------------------------------------------------------
#  Нормализация адресов
# --------------------------------------------------------------------------

STREET_TYPES = {
    "улица", "ул", "проспект", "пр", "прт", "проспк", "переулок", "пер",
    "бульвар", "бр", "шоссе", "ш", "площадь", "пл", "проезд", "тупик",
    "набережная", "наб", "аллея", "тракт", "микрорайон", "мкр", "квартал",
    "поселок", "посёлок", "пос", "деревня", "дер", "село", "линия", "въезд",
    "спуск", "взвоз",
}

CITY_TYPES = {"город", "г", "гор", "поселок", "посёлок", "пгт", "село", "деревня"}

_WORD = re.compile(r"[а-яёa-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower().replace("ё", "е"))


def normalize_street(name: str) -> str:
    """«ул. им. Чапаева В.И.» → «чапаева»; «проспект 50 лет Октября» → «50 лет октября»."""
    words = [w for w in _words(name) if w not in STREET_TYPES]
    words = [w for w in words if w not in {"им", "имени"}]
    # одиночные инициалы (в, и, а) отбрасываем
    words = [w for w in words if len(w) > 1 or w.isdigit()]
    return " ".join(words).strip()


def normalize_city(name: str) -> str:
    words = [w for w in _words(name) if w not in CITY_TYPES]
    return " ".join(words).strip()


def normalize_house(house: str) -> str:
    """«д. 12/1 корп. 2» → «12/1»; «14А» → «14а»."""
    raw = (house or "").lower().replace("ё", "е").replace("\\", "/")
    match = re.search(r"\d+\s*[а-я]?(?:\s*/\s*\d+\s*[а-я]?)?", raw)
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(0))


def same_city(a: str, b: str) -> bool:
    na, nb = normalize_city(a), normalize_city(b)
    if not na or not nb:
        return True  # недостаточно данных — не отсекаем
    return na == nb or na in nb or nb in na


def street_matches(loc_street: str, news_street: str) -> bool:
    a, b = normalize_street(loc_street), normalize_street(news_street)
    if not a or not b:
        return False
    if a == b:
        return True
    aw, bw = set(a.split()), set(b.split())
    if aw <= bw or bw <= aw:
        return True
    common = aw & bw
    return bool(common) and min(len(aw), len(bw)) > 0 and len(common) / min(len(aw), len(bw)) >= 1.0


def house_in_range(loc_house: str, houses: Sequence[str]) -> bool:
    """Пустой список домов = вся улица. Поддерживает диапазоны «12-18»."""
    if not houses:
        return True
    target = normalize_house(loc_house)
    if not target:
        return True
    target_num = re.match(r"\d+", target)
    for item in houses:
        raw = (item or "").lower().replace("ё", "е")
        rng = re.match(r"\s*(\d+)\s*[-–—]\s*(\d+)\s*$", raw)
        if rng and target_num:
            low, high = sorted((int(rng.group(1)), int(rng.group(2))))
            if low <= int(target_num.group(0)) <= high:
                return True
            continue
        if normalize_house(item) == target:
            return True
    return False


def district_matches(loc_district: str, news_district: str) -> bool:
    a = " ".join(w for w in _words(loc_district) if w != "район")
    b = " ".join(w for w in _words(news_district) if w != "район")
    return bool(a) and bool(b) and (a == b or a in b or b in a)


# --------------------------------------------------------------------------
#  Геометрия и кластеризация локаций
# --------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между точками в метрах."""
    radius = 6371008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def cluster_locations(
    locations: Iterable[dict[str, Any]], radius_m: float = 1000.0
) -> list[list[dict[str, Any]]]:
    """Объединяет локации, отстоящие друг от друга не более чем на radius_m.

    Связность транзитивная (union-find): A—B и B—C дают один кластер.
    Локации без координат образуют отдельные кластеры.
    """
    locs = list(locations)
    count = len(locs)
    if count == 0:
        return []

    parent = list(range(count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    def coords(loc: dict[str, Any]) -> tuple[float, float] | None:
        lat, lon = loc.get("lat"), loc.get("lon")
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if lat == 0.0 and lon == 0.0:
            return None
        return lat, lon

    for i in range(count):
        ci = coords(locs[i])
        if ci is None:
            continue
        for j in range(i + 1, count):
            cj = coords(locs[j])
            if cj is None:
                continue
            if haversine_m(ci[0], ci[1], cj[0], cj[1]) <= radius_m:
                union(i, j)

    buckets: dict[int, list[dict[str, Any]]] = {}
    for index, loc in enumerate(locs):
        buckets.setdefault(find(index), []).append(loc)
    return [buckets[key] for key in sorted(buckets)]


def cluster_center(cluster: Sequence[dict[str, Any]]) -> tuple[float, float]:
    points = [
        (float(loc["lat"]), float(loc["lon"]))
        for loc in cluster
        if loc.get("lat") or loc.get("lon")
    ]
    if not points:
        return 0.0, 0.0
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )
