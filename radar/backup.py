"""Резервные копии проекта: база, настройки, данные.

Один модуль на два контура — бот и веб-панель делают одно и то же, поэтому
логика здесь, а не продублирована в обработчиках.

Что попадает в копию: база (SQLite целиком с журналами WAL или дамп
PostgreSQL), файл `.env`, выгрузка источников, версия проекта. Журналы
не берём: они объёмные и восстановление от них не зависит.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config

log = logging.getLogger("radar.backup")

KEEP = 10
DIRECTORY = "backups"


@dataclass
class Archive:
    path: Path
    size: int
    created: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_human(self) -> str:
        value = float(self.size)
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if value < 1024 or unit == "ГБ":
                return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} ГБ"

    @property
    def when(self) -> str:
        return f"{datetime.fromtimestamp(self.created):%d.%m.%Y %H:%M}"


def directory() -> Path:
    path = Path(DIRECTORY)
    path.mkdir(parents=True, exist_ok=True)
    return path


def listing() -> list[Archive]:
    """Копии, новые сверху."""
    items: list[Archive] = []
    for path in directory().glob("radar-backup-*.tar.gz"):
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(Archive(path, stat.st_size, stat.st_mtime))
    return sorted(items, key=lambda item: item.created, reverse=True)


def find(name: str) -> Path | None:
    """Ищет копию по имени. Имя проверяется — иначе можно уйти из каталога."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    target = directory() / name
    return target if target.exists() and target.is_file() else None


def _dump_postgres(destination: Path) -> bool:
    """Дамп PostgreSQL через контейнер. Без него копия бесполезна."""
    import subprocess

    try:
        with destination.open("wb") as handle:
            result = subprocess.run(
                ["docker", "exec", "radar_db", "pg_dump", "-U", config.DB_USER,
                 config.DB_NAME],
                stdout=handle, stderr=subprocess.PIPE, timeout=300, check=False,
            )
        if result.returncode == 0:
            return True
        log.warning("pg_dump вернул %s: %s", result.returncode,
                    result.stderr.decode("utf-8", "replace")[:200])
    except Exception as exc:  # noqa: BLE001
        log.warning("Дамп PostgreSQL не выполнен: %s", exc)
    destination.unlink(missing_ok=True)
    return False


def _collect(staging: Path, reason: str) -> None:
    """Складывает во временный каталог всё, что должно попасть в копию."""
    staging.mkdir(parents=True, exist_ok=True)

    if config.is_sqlite():
        source = Path(config.DB_FILE)
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{source}{suffix}")
            if candidate.exists():
                shutil.copy2(candidate, staging / candidate.name)
    else:
        _dump_postgres(staging / "database.sql")

    env_path = Path(".env")
    if env_path.exists():
        shutil.copy2(env_path, staging / "env.backup")

    legacy = Path("data/db.json")
    if legacy.exists():
        shutil.copy2(legacy, staging / "db.json")

    manifest = staging / "manifest.txt"
    manifest.write_text(
        f"Система «Радар»\n"
        f"Версия: {config.VERSION}\n"
        f"Дата: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"База: {'SQLite' if config.is_sqlite() else 'PostgreSQL'}\n"
        f"Причина: {reason}\n",
        encoding="utf-8",
    )


def _prune() -> None:
    for extra in listing()[KEEP:]:
        try:
            extra.path.unlink()
        except OSError:
            pass


def create_sync(reason: str = "вручную") -> tuple[Path | None, str]:
    """Собирает копию. Возвращает (путь, ошибка)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = directory() / f"radar-backup-{config.VERSION}-{stamp}.tar.gz"
    staging = directory() / f".staging-{stamp}"

    try:
        _collect(staging, reason)
        with tarfile.open(archive, "w:gz") as bundle:
            for item in staging.iterdir():
                bundle.add(item, arcname=item.name)
    except Exception as exc:  # noqa: BLE001
        log.error("Копия не создана: %s", exc)
        archive.unlink(missing_ok=True)
        return None, str(exc)[:200]
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    _prune()
    log.info("Копия создана: %s (%d КБ)", archive.name, archive.stat().st_size // 1024)
    return archive, ""


async def create(reason: str = "вручную") -> tuple[Path | None, str]:
    """Асинхронная обёртка: упаковка блокирует, уводим в поток."""
    return await asyncio.to_thread(create_sync, reason)


def backup_env() -> Path | None:
    """Копия .env перед изменением ключей.

    Отдельная и дешёвая: правка ключа через бот не должна требовать полной
    копии проекта, но и потерять прежние значения нельзя.
    """
    source = Path(config.ENV_FILE if hasattr(config, "ENV_FILE") else ".env")
    if not source.exists():
        return None
    target = directory() / f"env-{datetime.now():%Y%m%d-%H%M%S}.backup"
    try:
        shutil.copy2(source, target)
        os.chmod(target, 0o600)
    except OSError as exc:
        log.warning("Копия .env не создана: %s", exc)
        return None

    # Держим последние 10 копий настроек
    old = sorted(directory().glob("env-*.backup"), key=lambda item: item.stat().st_mtime)
    for extra in old[:-10]:
        extra.unlink(missing_ok=True)
    return target


def summary() -> str:
    """Состояние копий для сообщения в боте."""
    items = listing()
    if not items:
        return (
            "💾 <b>Резервные копии</b>\n\nКопий пока нет.\n\n"
            "<i>Копия включает базу целиком, файл настроек и версию проекта.</i>"
        )

    total = sum(item.size for item in items)
    lines = [
        "💾 <b>Резервные копии</b>",
        f"Всего: <b>{len(items)}</b>, объём {total // 1024} КБ",
        "",
    ]
    for item in items[:10]:
        lines.append(f"• <code>{item.name}</code>\n  {item.when} · {item.size_human}")
    lines.append("")
    lines.append(
        "<i>Хранятся последние 10. Восстановление — установщиком: "
        "<code>bash install.sh --rollback</code></i>"
    )
    return "\n".join(lines)
