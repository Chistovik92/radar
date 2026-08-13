#!/usr/bin/env python3
"""Проверка источников: доступен ли канал и когда там была последняя публикация.

    python3 tools/check_sources.py                      # источники из data/db.json
    python3 tools/check_sources.py --file sources.json  # из файла выгрузки
    python3 tools/check_sources.py --preset kazan,samara
    python3 tools/check_sources.py --all-presets
    python3 tools/check_sources.py --json report.json

Каналы Telegram проверяются по публичному веб-превью `t.me/s/<канал>`,
RSS — обычным запросом с разбором даты последней записи.

Зачем: списки каналов устаревают молча. Канал переименовали, ведомство
ушло в другой мессенджер, лента отдаёт 404 — бот при этом продолжает
работать и ничего не сообщает, просто получает меньше новостей.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import aiohttp
except ImportError:
    sys.exit("Нужен aiohttp:  pip install aiohttp")

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Нужен beautifulsoup4:  pip install beautifulsoup4")

from radar import presets  # noqa: E402

USER_AGENT = "RadarSourceChecker/1.0 (+https://github.com/Chistovik92/radar)"
STALE_DAYS = 14

def _age(moment: datetime | None) -> str:
    if moment is None:
        return "—"
    delta = datetime.now(timezone.utc) - moment
    days = delta.days
    if days < 0:
        return "только что"
    if days == 0:
        hours = delta.seconds // 3600
        return f"{hours} ч назад" if hours else "только что"
    if days == 1:
        return "вчера"
    return f"{days} дн назад"


async def check_channel(session: aiohttp.ClientSession, name: str) -> dict:
    result = {"kind": "tg", "ref": name, "ok": False, "note": "", "last": None, "posts": 0}
    try:
        async with session.get(f"https://t.me/s/{name}", allow_redirects=True) as response:
            if response.status == 404:
                result["note"] = "канал не найден (404)"
                return result
            if response.status != 200:
                result["note"] = f"HTTP {response.status}"
                return result
            page = await response.text()
    except Exception as exc:  # noqa: BLE001
        result["note"] = f"{type(exc).__name__}: {exc}"
        return result

    soup = BeautifulSoup(page, "html.parser")
    posts = soup.find_all("div", class_="tgme_widget_message_text")
    result["posts"] = len(posts)

    if not posts:
        if "tgme_page_context" in page or "Preview channel" in page:
            result["note"] = "канал закрытый или без публичного превью"
        else:
            result["note"] = "публикации не найдены"
        return result

    times = soup.find_all("time", attrs={"datetime": True})
    if times:
        try:
            result["last"] = datetime.fromisoformat(
                times[-1]["datetime"].replace("Z", "+00:00")
            )
        except ValueError:
            pass

    result["ok"] = True
    if result["last"] and (datetime.now(timezone.utc) - result["last"]).days > STALE_DAYS:
        result["note"] = "давно не обновлялся"

    # Косвенный признак ухода в другой мессенджер.
    tail = " ".join(post.get_text(" ") for post in posts[-5:]).lower()
    if "max.ru" in tail or "перешли в max" in tail:
        result["note"] = (result["note"] + "; " if result["note"] else "") + "упоминает MAX"
    return result


async def check_feed(session: aiohttp.ClientSession, url: str) -> dict:
    result = {"kind": "rss", "ref": url, "ok": False, "note": "", "last": None, "posts": 0}
    try:
        async with session.get(url, allow_redirects=True) as response:
            if response.status != 200:
                result["note"] = f"HTTP {response.status}"
                return result
            body = await response.text()
    except Exception as exc:  # noqa: BLE001
        result["note"] = f"{type(exc).__name__}: {exc}"
        return result

    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError as exc:
        result["note"] = f"не разобран как XML: {exc}"
        return result

    entries = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    result["posts"] = len(entries)
    if not entries:
        result["note"] = "лента пуста"
        return result

    result["ok"] = True
    for tag in ("pubDate", "{http://purl.org/dc/elements/1.1/}date",
                "{http://www.w3.org/2005/Atom}updated", "updated"):
        node = entries[0].find(tag)
        if node is not None and node.text:
            result["last"] = _parse_date(node.text)
            break

    has_link = any(
        entry.find("link") is not None
        or entry.find("{http://www.w3.org/2005/Atom}link") is not None
        for entry in entries[:3]
    )
    if not has_link:
        result["note"] = "в записях нет ссылок"
    if result["last"] and (datetime.now(timezone.utc) - result["last"]).days > STALE_DAYS:
        result["note"] = (result["note"] + "; " if result["note"] else "") + "давно не обновлялась"
    return result


def _parse_date(text: str) -> datetime | None:
    text = text.strip()
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


def load_sources(args) -> tuple[list[str], list[str]]:
    if args.preset or args.all_presets:
        keys = (
            [preset.key for preset in presets.ALL]
            if args.all_presets
            else [key.strip() for key in args.preset.split(",") if key.strip()]
        )
        channels: list[str] = []
        feeds: list[str] = []
        for key in keys:
            preset = presets.BY_KEY.get(key) or presets.for_city(key)
            if preset is None:
                sys.exit(f"Неизвестный пресет «{key}». Доступные: "
                         f"{', '.join(presets.BY_KEY)}")
            channels.extend(preset.channels)
            feeds.extend(preset.rss)
        return list(dict.fromkeys(channels)), list(dict.fromkeys(feeds))

    path = Path(args.file) if args.file else ROOT / "data" / "db.json"
    if not path.exists():
        sys.exit(f"Файл не найден: {path}. Укажите --file или --preset.")
    data = json.loads(path.read_text("utf-8"))
    return list(data.get("channels") or []), list(data.get("rss") or [])


async def run(args) -> int:
    channels, feeds = load_sources(args)
    total = len(channels) + len(feeds)
    if not total:
        sys.exit("Источников не найдено.")

    print(f"Проверяю: каналов {len(channels)}, лент {len(feeds)}\n")

    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"}
    results: list[dict] = []

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for name in channels:
            result = await check_channel(session, name)
            results.append(result)
            _print(result)
            await asyncio.sleep(args.delay)
        for url in feeds:
            result = await check_feed(session, url)
            results.append(result)
            _print(result)
            await asyncio.sleep(args.delay)

    dead = [item for item in results if not item["ok"]]
    stale = [item for item in results if item["ok"] and item["note"]]
    alive = len(results) - len(dead)

    print("\n" + "=" * 72)
    print(f"Живых: {alive}/{len(results)}, недоступных: {len(dead)}, с замечаниями: {len(stale)}")

    if dead:
        print("\nНедоступны — стоит убрать или заменить:")
        for item in dead:
            print(f"  ✗ {item['ref']} — {item['note']}")
    if stale:
        print("\nС замечаниями:")
        for item in stale:
            print(f"  ⚠️  {item['ref']} — {item['note']}")

    if args.json:
        payload = [
            {**item, "last": item["last"].isoformat() if item["last"] else None}
            for item in results
        ]
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nОтчёт: {args.json}")

    return 1 if dead else 0


def _print(result: dict) -> None:
    mark = "✓" if result["ok"] and not result["note"] else "⚠" if result["ok"] else "✗"
    ref = result["ref"]
    if len(ref) > 44:
        ref = ref[:41] + "…"
    tail = f" — {result['note']}" if result["note"] else ""
    print(f"  {mark} {ref:<46}{_age(result['last']):>14}{tail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка источников «Радара»")
    parser.add_argument("--file", help="файл выгрузки или db.json")
    parser.add_argument("--preset", help="пресеты городов через запятую")
    parser.add_argument("--all-presets", action="store_true", help="проверить все пресеты")
    parser.add_argument("--json", help="сохранить отчёт в файл")
    parser.add_argument("--delay", type=float, default=1.0, help="пауза между запросами, с")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nПрервано.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
