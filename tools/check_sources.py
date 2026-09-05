#!/usr/bin/env python3
"""Проверка источников из терминала.

    python3 tools/check_sources.py                      # источники из data/db.json
    python3 tools/check_sources.py --file sources.json  # из файла выгрузки
    python3 tools/check_sources.py --preset kazan,samara
    python3 tools/check_sources.py --all-presets
    python3 tools/check_sources.py --json report.json

Сама логика проверки живёт в `radar/sourcecheck.py` — тот же код использует
бот по кнопке «Проверить доступность». Дублировать её здесь незачем:
разойдутся при первом же исправлении.
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
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import aiohttp  # noqa: F401
    from bs4 import BeautifulSoup  # noqa: F401
except ImportError as exc:
    sys.exit(f"Нужны aiohttp и beautifulsoup4: pip install aiohttp beautifulsoup4 ({exc})")

from radar import presets, sourcecheck  # noqa: E402


def load_sources(args) -> tuple[list[str], list[str]]:
    if args.preset or args.all_presets:
        keys = (
            [item.key for item in presets.ALL]
            if args.all_presets
            else [key.strip() for key in args.preset.split(",") if key.strip()]
        )
        channels: list[str] = []
        feeds: list[str] = []
        for key in keys:
            preset = presets.BY_KEY.get(key) or presets.for_city(key)
            if preset is None:
                sys.exit(f"Неизвестный пресет «{key}». Доступные: {', '.join(presets.BY_KEY)}")
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

    async def progress(done: int, count: int, current: str) -> None:
        print(f"  [{done:>3}/{count}] {current}", flush=True)

    report = await sourcecheck.check_all(
        channels, feeds, pause=args.delay, progress=progress if args.verbose else None
    )

    print()
    for item in report.statuses:
        note = f" — {item.note}" if item.note else ""
        print(f"  {item.icon} {item.title:<44}{item.age:>14}{note}")

    print("\n" + "=" * 72)
    print(
        f"Живых: {len(report.alive)}, затихших: {len(report.stale)}, "
        f"недоступных: {len(report.dead)} из {report.total}"
    )

    if report.dead:
        print("\nНедоступны — стоит убрать или заменить:")
        for item in report.dead:
            print(f"  ✗ {item.title} — {item.note}")
    if report.stale:
        print(f"\nМолчат более {sourcecheck.STALE_DAYS} дней:")
        for item in report.stale:
            print(f"  ! {item.title} — {item.age}")

    if args.json:
        payload = []
        for item in report.statuses:
            row = asdict(item)
            row["last_post"] = item.last_post.isoformat() if item.last_post else None
            payload.append(row)
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nОтчёт: {args.json}")

    return 1 if report.dead else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка источников «Радара»")
    parser.add_argument("--file", help="файл выгрузки или db.json")
    parser.add_argument("--preset", help="пресеты городов через запятую")
    parser.add_argument("--all-presets", action="store_true", help="проверить все пресеты")
    parser.add_argument("--json", help="сохранить отчёт в файл")
    parser.add_argument("--delay", type=float, default=sourcecheck.POLITE_PAUSE,
                        help="пауза между запросами, с")
    parser.add_argument("--verbose", "-v", action="store_true", help="показывать ход проверки")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nПрервано.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
