"""Обмен списками источников: экспорт в файл и импорт обратно.

Формат намеренно простой и версионированный, чтобы файл, выгруженный сегодня,
читался будущими версиями бота. Правила совместимости:

* `schema` — номер формата. Импортёр принимает всё, что не новее известного ему,
  и честно отказывается читать файл из более новой версии.
* Неизвестные поля игнорируются, отсутствующие берутся по умолчанию —
  добавление полей в будущем не ломает старые файлы.
* Принимаются также «сырые» варианты: массив строк, файл `db.json` целиком
  или список каналов текстом — так можно перенести настройки из версий 2.x.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

FORMAT = "radar-sources"
SCHEMA = 1

CHANNEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
URL_RE = re.compile(r"^https?://", re.I)
TELEGRAM_RE = re.compile(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/", re.I)

def is_feed_url(value: str) -> bool:
    """Ссылка на ленту, а не на Telegram-канал."""
    return bool(URL_RE.match(value)) and not TELEGRAM_RE.match(value)


def normalize_channel(raw: str) -> str:
    value = re.sub(r"^(https?://)?(t\.me/|telegram\.me/)?@?", "", (raw or "").strip(), flags=re.I)
    return value.strip("/ ").split("/")[0].split("?")[0]


@dataclass
class Bundle:
    """Разобранный набор источников."""

    channels: list[str] = field(default_factory=list)
    rss: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    origin: str = ""      # версия бота, из которой выгружено
    schema: int = SCHEMA
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.channels) + len(self.rss)


class ImportError_(ValueError):
    """Файл не удалось прочитать."""


def export_bundle(
    channels: list[str], rss: list[str], pending: list[str], version: str
) -> bytes:
    """Собирает файл выгрузки."""
    payload = {
        "format": FORMAT,
        "schema": SCHEMA,
        "generator": f"radar/{version}",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {"channels": len(channels), "rss": len(rss), "pending": len(pending)},
        "channels": sorted(set(channels)),
        "rss": sorted(set(rss)),
        "pending": sorted(set(pending)),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def export_filename(version: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"radar-sources-{version}-{stamp}.json"


def _clean(values: Any, kind: str, warnings: list[str]) -> list[str]:
    result: list[str] = []
    if not isinstance(values, (list, tuple)):
        return result
    for item in values:
        if isinstance(item, dict):  # запас на будущее: {"ref": ..., "type": ...}
            item = item.get("ref") or item.get("url") or item.get("name") or ""
        text = str(item).strip()
        if not text:
            continue
        if kind == "rss":
            if is_feed_url(text):
                result.append(text)
            elif TELEGRAM_RE.match(text):
                warnings.append(
                    f"«{text[:40]}» — Telegram-канал, а не лента: перенесите в channels"
                )
            else:
                warnings.append(f"пропущена лента «{text[:40]}»: не похоже на адрес")
            continue
        channel = normalize_channel(text)
        if CHANNEL_RE.match(channel):
            result.append(channel)
        else:
            warnings.append(f"пропущен канал «{text[:40]}»: некорректный юзернейм")
    # порядок сохраняем, дубликаты убираем
    return list(dict.fromkeys(result))


def parse_bundle(raw: bytes | str) -> Bundle:
    """Читает файл выгрузки, db.json версии 2.x или простой список строк."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ImportError_("файл не в кодировке UTF-8") from exc

    text = raw.strip()
    if not text:
        raise ImportError_("файл пуст")

    warnings: list[str] = []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Не JSON — принимаем простой список каналов текстом.
        parts = [part for part in re.split(r"[,\s\n;]+", text) if part]
        # Ссылка на t.me — это канал, а не лента.
        channels = _clean([p for p in parts if not is_feed_url(p)], "channel", warnings)
        feeds = _clean([p for p in parts if is_feed_url(p)], "rss", warnings)
        if not channels and not feeds:
            raise ImportError_("не найдено ни одного источника")
        return Bundle(channels=channels, rss=feeds, warnings=warnings, origin="текстовый список")

    if isinstance(data, list):
        return Bundle(
            channels=_clean(
                [item for item in data if not is_feed_url(str(item))], "channel", warnings
            ),
            rss=_clean([item for item in data if is_feed_url(str(item))], "rss", warnings),
            warnings=warnings,
            origin="массив",
        )

    if not isinstance(data, dict):
        raise ImportError_("неподдерживаемая структура файла")

    schema = data.get("schema")
    if isinstance(schema, int) and schema > SCHEMA:
        raise ImportError_(
            f"файл формата версии {schema}, а бот понимает до {SCHEMA} — обновите бота"
        )

    if data.get("format") and data.get("format") != FORMAT:
        warnings.append(f"неизвестный формат «{data['format']}», читаю как смогу")

    channels = _clean(data.get("channels"), "channel", warnings)
    rss = _clean(data.get("rss") or data.get("feeds"), "rss", warnings)
    pending = _clean(data.get("pending"), "channel", warnings)

    if not channels and not rss:
        raise ImportError_("в файле нет ни каналов, ни лент")

    return Bundle(
        channels=channels,
        rss=rss,
        pending=pending,
        origin=str(data.get("generator") or "неизвестно"),
        schema=schema if isinstance(schema, int) else 0,
        warnings=warnings,
    )


def merge(
    bundle: Bundle,
    channels: list[str],
    rss: list[str],
    *,
    replace: bool = False,
) -> tuple[int, int]:
    """Вливает набор в текущие списки. Возвращает (добавлено каналов, лент)."""
    if replace:
        channels.clear()
        rss.clear()

    added_channels = 0
    for name in bundle.channels:
        if name not in channels:
            channels.append(name)
            added_channels += 1

    added_rss = 0
    for url in bundle.rss:
        if url not in rss:
            rss.append(url)
            added_rss += 1

    return added_channels, added_rss
