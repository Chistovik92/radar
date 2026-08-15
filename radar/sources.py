"""Сбор сообщений из источников: публичные Telegram-каналы и RSS-ленты СМИ."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from . import config

log = logging.getLogger("radar.sources")

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\u00a0]+")

@dataclass(frozen=True)
class Item:
    """Одно сообщение источника."""

    source: str
    text: str
    kind: str = "tg"  # tg | rss
    link: str = ""    # прямая ссылка на публикацию

    @property
    def key(self) -> str:
        return hashlib.sha1(self.text.encode("utf-8")).hexdigest()


class SeenStore:
    """FIFO-хранилище хэшей уже обработанных сообщений."""

    def __init__(self, maxlen: int = 2000) -> None:
        self._order: deque[str] = deque(maxlen=maxlen)
        self._items: set[str] = set()

    def add(self, key: str) -> bool:
        """True, если сообщение встречено впервые."""
        if key in self._items:
            return False
        if self._order.maxlen and len(self._order) == self._order.maxlen:
            self._items.discard(self._order[0])
        self._order.append(key)
        self._items.add(key)
        return True

    def __len__(self) -> int:
        return len(self._items)


def clean(text: str) -> str:
    text = _TAGS.sub(" ", text)
    text = _SPACES.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


async def fetch_channel(
    session: aiohttp.ClientSession, channel: str, limit: int
) -> list[Item]:
    """Читает веб-превью публичного канала https://t.me/s/<channel>."""
    url = f"https://t.me/s/{channel}"
    try:
        async with session.get(url) as response:
            if response.status != 200:
                log.debug("Канал @%s: HTTP %s", channel, response.status)
                return []
            page = await response.text()
    except Exception as exc:  # noqa: BLE001
        log.debug("Канал @%s недоступен: %s", channel, exc)
        return []

    soup = BeautifulSoup(page, "html.parser")
    blocks = soup.find_all("div", class_="tgme_widget_message_text")
    items: list[Item] = []
    for block in blocks[-limit:]:
        text = clean(block.get_text(separator="\n"))
        if len(text) >= 20:
            items.append(Item(source=channel, text=text, kind="tg"))
    return items


async def fetch_rss(session: aiohttp.ClientSession, url: str, limit: int) -> list[Item]:
    """Читает RSS/Atom-ленту СМИ или официального сайта."""
    try:
        async with session.get(url) as response:
            if response.status != 200:
                log.debug("RSS %s: HTTP %s", url, response.status)
                return []
            body = await response.text()
    except Exception as exc:  # noqa: BLE001
        log.debug("RSS %s недоступен: %s", url, exc)
        return []

    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError as exc:
        log.debug("RSS %s: не разобран (%s)", url, exc)
        return []

    label = urlparse(url).netloc or url
    entries = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    items: list[Item] = []
    for entry in entries[:limit]:
        title = _child_text(entry, "title")
        body_text = _child_text(entry, "description") or _child_text(entry, "summary")
        text = clean(f"{title}\n{body_text}")
        if len(text) >= 20:
            items.append(Item(source=label, text=text, kind="rss", link=_entry_link(entry)))
    return items


def _entry_link(entry: ET.Element) -> str:
    """Ссылка на публикацию: RSS кладёт её в текст, Atom — в атрибут href."""
    node = entry.find("link")
    if node is not None:
        if node.text and node.text.strip():
            return node.text.strip()
        href = node.get("href")
        if href:
            return href.strip()
    for candidate in entry.findall("{http://www.w3.org/2005/Atom}link"):
        rel = candidate.get("rel") or "alternate"
        if rel == "alternate" and candidate.get("href"):
            return candidate.get("href").strip()
    guid = entry.find("guid")
    if guid is not None and guid.text and guid.text.strip().startswith("http"):
        return guid.text.strip()
    return ""


def _child_text(entry: ET.Element, tag: str) -> str:
    for candidate in (tag, f"{{http://www.w3.org/2005/Atom}}{tag}"):
        node = entry.find(candidate)
        if node is not None and node.text:
            return node.text
    return ""


async def collect(
    session: aiohttp.ClientSession,
    channels: list[str],
    feeds: list[str],
    seen: SeenStore,
    limit: int = config.MSG_PER_SOURCE,
    *,
    warmup: bool = False,
) -> list[Item]:
    """Обходит все источники и возвращает только новые сообщения.

    При warmup=True сообщения помечаются прочитанными, но не возвращаются —
    так первый запуск не рассылает всю ленту разом.
    """
    fresh: list[Item] = []

    for channel in list(channels):
        for item in await fetch_channel(session, channel, limit):
            if seen.add(item.key) and not warmup:
                fresh.append(item)

    for url in list(feeds):
        for item in await fetch_rss(session, url, limit):
            if seen.add(item.key) and not warmup:
                fresh.append(item)

    return fresh


# --------------------------------------------------------------------------
#  ВКонтакте
# --------------------------------------------------------------------------

VK_API = "https://api.vk.com/method"
VK_VERSION = "5.199"

# Коды ошибок VK, при которых нужно притормозить, а не считать источник мёртвым
VK_RATE_CODES = {6, 9, 29}


async def fetch_vk(
    session: aiohttp.ClientSession, group: str, token: str, limit: int = 10
) -> list[Item]:
    """Стена открытого сообщества через wall.get.

    Особенности VK, из-за которых нельзя просто смотреть на код ответа:

    * ошибки приходят с HTTP 200 и телом `{"error": {...}}`, а не с 429;
    * код 6 — слишком много запросов в секунду, код 9 — флуд-контроль;
      это временные состояния, источник исключать нельзя;
    * пустой массив без ошибки не означает «новостей нет»: так же выглядит
      закрытая или удалённая стена.
    """
    identifier = group.strip().lstrip("@")
    params = {
        "domain": identifier,
        "count": str(limit),
        "filter": "owner",
        "access_token": token,
        "v": VK_VERSION,
    }
    if identifier.lstrip("-").isdigit():
        params.pop("domain")
        params["owner_id"] = identifier if identifier.startswith("-") else f"-{identifier}"

    try:
        async with session.get(f"{VK_API}/wall.get", params=params) as response:
            if response.status != 200:
                log.warning("VK %s: HTTP %s", identifier, response.status)
                return []
            payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("VK %s недоступен: %s", identifier, exc)
        return []

    error = payload.get("error")
    if error:
        code = int(error.get("error_code") or 0)
        message = str(error.get("error_msg") or "")
        if code in VK_RATE_CODES:
            log.info("VK %s: ограничение частоты (код %d) — пропускаю цикл",
                     identifier, code)
        else:
            log.warning("VK %s: ошибка %d — %s", identifier, code, message)
        return []

    response_body = payload.get("response") or {}
    posts = response_body.get("items") or []
    if not posts:
        # Пустая выдача без ошибки: стена закрыта, пуста или сообщество удалено
        log.info("VK %s: записей нет — проверьте, открыта ли стена", identifier)
        return []

    items: list[Item] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        text = clean(str(post.get("text") or ""))
        if len(text) < 20:
            continue
        owner = post.get("owner_id")
        post_id = post.get("id")
        link = f"https://vk.com/wall{owner}_{post_id}" if owner and post_id else ""
        items.append(Item(source=f"vk/{identifier}", text=text, kind="vk", link=link))
    return items
