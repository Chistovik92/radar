"""Проверка доступности источников: Telegram-каналы, RSS-ленты, сообщества VK.

Списки источников устаревают молча: канал переименовали, издание закрылось,
ведомство ушло в другой мессенджер. Бот при этом продолжает работать
и просто получает меньше новостей — без единой строки в журнале.

Модуль используется и ботом (кнопка в панели модератора), и из терминала
(`python3 tools/check_sources.py`).

Почему проверка устроена сложнее, чем «запросить и посмотреть код ответа»:

* `t.me/s/<канал>` отвечает 200 и для несуществующего канала, и для закрытого —
  просто без постов. Судить можно только по наличию блоков сообщений.
* Часть RSS-лент отвечает 403 на запрос без User-Agent.
* Источник может отвечать 200, а последний пост быть годовой давности —
  формально жив, практически бесполезен.
* Запросы идут с паузой: три десятка обращений подряд к одному хосту
  выглядят как перебор.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from . import config

log = logging.getLogger("radar.sourcecheck")

STALE_DAYS = 14          # после скольких дней молчания считаем источник затихшим
REQUEST_TIMEOUT = 20
POLITE_PAUSE = 0.8       # секунд между запросами

ALIVE = "alive"
STALE = "stale"
DEAD = "dead"

ICONS = {ALIVE: "✓", STALE: "!", DEAD: "✗"}


@dataclass
class SourceStatus:
    kind: str                    # tg | rss | vk
    ref: str
    state: str = DEAD
    note: str = ""
    last_post: datetime | None = None
    posts: int = 0
    http_status: int = 0

    @property
    def icon(self) -> str:
        return ICONS.get(self.state, "?")

    @property
    def title(self) -> str:
        if self.kind == "tg":
            return f"@{self.ref}"
        if self.kind == "rss":
            return urlparse(self.ref).netloc or self.ref
        return self.ref

    @property
    def age(self) -> str:
        if self.last_post is None:
            return "—"
        delta = datetime.now(timezone.utc) - self.last_post
        if delta.days < 0:
            return "только что"
        if delta.days == 0:
            hours = delta.seconds // 3600
            return f"{hours} ч назад" if hours else "только что"
        if delta.days == 1:
            return "вчера"
        return f"{delta.days} дн назад"


@dataclass
class CheckReport:
    statuses: list[SourceStatus] = field(default_factory=list)
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def alive(self) -> list[SourceStatus]:
        return [item for item in self.statuses if item.state == ALIVE]

    @property
    def stale(self) -> list[SourceStatus]:
        return [item for item in self.statuses if item.state == STALE]

    @property
    def dead(self) -> list[SourceStatus]:
        return [item for item in self.statuses if item.state == DEAD]

    @property
    def total(self) -> int:
        return len(self.statuses)


def _headers() -> dict[str, str]:
    # Без User-Agent часть лент отвечает 403
    return {"User-Agent": config.USER_AGENT, "Accept-Language": "ru,en;q=0.8"}


def _is_stale(moment: datetime | None) -> bool:
    if moment is None:
        return False
    return (datetime.now(timezone.utc) - moment).days > STALE_DAYS


def _parse_date(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


# --------------------------------------------------------------------------
#  Отдельные виды источников
# --------------------------------------------------------------------------

async def check_channel(session: aiohttp.ClientSession, name: str) -> SourceStatus:
    status = SourceStatus(kind="tg", ref=name)
    try:
        async with session.get(f"https://t.me/s/{name}", allow_redirects=True) as response:
            status.http_status = response.status
            if response.status == 404:
                status.note = "канал не найден"
                return status
            if response.status != 200:
                status.note = f"HTTP {response.status}"
                return status
            page = await response.text()
    except asyncio.TimeoutError:
        status.note = "таймаут"
        return status
    except Exception as exc:  # noqa: BLE001
        status.note = f"{type(exc).__name__}"
        return status

    soup = BeautifulSoup(page, "html.parser")
    posts = soup.find_all("div", class_="tgme_widget_message_text")
    status.posts = len(posts)

    # Код 200 сам по себе ничего не значит: страница отдаётся и для закрытых
    # каналов, и для несуществующих — но без блоков сообщений.
    if not posts:
        if "tgme_page_context" in page or "Preview channel" in page:
            status.note = "закрытый канал или нет публичного превью"
        else:
            status.note = "публикации не найдены"
        return status

    times = soup.find_all("time", attrs={"datetime": True})
    if times:
        try:
            status.last_post = datetime.fromisoformat(
                times[-1]["datetime"].replace("Z", "+00:00")
            )
        except (ValueError, KeyError):
            pass

    tail = " ".join(post.get_text(" ") for post in posts[-5:]).lower()
    if "max.ru" in tail or "перешли в max" in tail:
        status.note = "упоминает переход в MAX"

    if _is_stale(status.last_post):
        status.state = STALE
        status.note = status.note or "давно не обновлялся"
    else:
        status.state = ALIVE
    return status


async def check_feed(session: aiohttp.ClientSession, url: str) -> SourceStatus:
    status = SourceStatus(kind="rss", ref=url)
    try:
        async with session.get(url, allow_redirects=True) as response:
            status.http_status = response.status
            if response.status != 200:
                status.note = f"HTTP {response.status}"
                return status
            body = await response.text()
    except asyncio.TimeoutError:
        status.note = "таймаут"
        return status
    except Exception as exc:  # noqa: BLE001
        status.note = f"{type(exc).__name__}"
        return status

    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError:
        status.note = "ответ не является XML"
        return status

    entries = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    status.posts = len(entries)
    if not entries:
        status.note = "лента пуста"
        return status

    for tag in ("pubDate", "{http://purl.org/dc/elements/1.1/}date",
                "{http://www.w3.org/2005/Atom}updated", "updated"):
        node = entries[0].find(tag)
        if node is not None and node.text:
            status.last_post = _parse_date(node.text)
            break

    if _is_stale(status.last_post):
        status.state = STALE
        status.note = "давно не обновлялась"
    else:
        status.state = ALIVE
    return status


async def check_vk(session: aiohttp.ClientSession, group: str) -> SourceStatus:
    """Заглушка до версии 4.1: полноценная проверка появится вместе с VK API."""
    status = SourceStatus(kind="vk", ref=group)
    status.note = "проверка появится в 4.1"
    status.state = ALIVE
    return status


# --------------------------------------------------------------------------
#  Общий обход
# --------------------------------------------------------------------------

async def check_all(
    channels: list[str],
    feeds: list[str],
    vk_groups: list[str] | None = None,
    *,
    pause: float = POLITE_PAUSE,
    progress=None,
) -> CheckReport:
    """Проверяет все источники по очереди.

    `progress` — необязательная корутина `progress(done, total, current)`:
    бот показывает через неё ход проверки, чтобы ожидание не было немым.
    """
    report = CheckReport()
    total = len(channels) + len(feeds) + len(vk_groups or [])
    done = 0

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout, headers=_headers()) as session:
        for name in channels:
            report.statuses.append(await check_channel(session, name))
            done += 1
            if progress:
                await progress(done, total, f"@{name}")
            await asyncio.sleep(pause)

        for url in feeds:
            report.statuses.append(await check_feed(session, url))
            done += 1
            if progress:
                await progress(done, total, urlparse(url).netloc or url)
            await asyncio.sleep(pause)

        for group in vk_groups or []:
            report.statuses.append(await check_vk(session, group))
            done += 1
            if progress:
                await progress(done, total, group)

    log.info(
        "Проверка источников: живых %d, затихших %d, недоступных %d из %d",
        len(report.alive), len(report.stale), len(report.dead), report.total,
    )
    return report


def render(report: CheckReport, limit: int = 40) -> str:
    """HTML-сводка для сообщения в боте."""
    from .textutils import esc

    lines = [
        "🔍 <b>Проверка источников</b>",
        f"Живых: <b>{len(report.alive)}</b> · "
        f"затихших: <b>{len(report.stale)}</b> · "
        f"недоступных: <b>{len(report.dead)}</b> из {report.total}",
    ]

    if report.dead:
        lines.append("")
        lines.append("✗ <b>Недоступны</b> — стоит убрать или заменить:")
        for item in report.dead[:limit]:
            lines.append(f"• {esc(item.title)} — {esc(item.note)}")

    if report.stale:
        lines.append("")
        lines.append(f"! <b>Молчат более {STALE_DAYS} дней:</b>")
        for item in report.stale[:limit]:
            lines.append(f"• {esc(item.title)} — {esc(item.age)}")

    if not report.dead and not report.stale:
        lines.append("")
        lines.append("Все источники отвечают и обновляются.")

    return "\n".join(lines)
