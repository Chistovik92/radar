"""Журналы системы: перечисление, выгрузка и очистка.

Все журналы лежат в одном каталоге внутри `data/`, потому что это
единственный путь, видимый одновременно боту (внутри контейнера)
и установщику (на хосте). Благодаря этому суперадминистратор может
забрать журнал установки прямо из бота, не заходя по SSH.

Журналы контейнеров Docker сюда не попадают: чтобы их читать, боту
пришлось бы дать доступ к сокету Docker, а это фактически полный доступ
к хосту. Вместо этого установщик кладёт рядом скрипт `collect-logs.sh`,
который собирает всё в один архив уже на стороне сервера.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import io
import logging
import os
import re
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config

log = logging.getLogger("radar.logs")

# Что считаем журналом: имена, которые пишем мы сами и наш установщик.
PATTERNS = (
    re.compile(r"^bot\.log(\.\d+)?$"),
    re.compile(r"^installer_log.*\.txt$"),
    re.compile(r"^doctor.*\.(txt|json)$"),
)


@dataclass
class LogFile:
    path: Path
    kind: str          # bot | installer | doctor | other
    size: int
    modified: float

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
    def age_human(self) -> str:
        delta = time.time() - self.modified
        if delta < 3600:
            return f"{int(delta // 60)} мин назад"
        if delta < 86400:
            return f"{int(delta // 3600)} ч назад"
        return f"{int(delta // 86400)} дн назад"


def _classify(name: str) -> str:
    if name.startswith("bot.log"):
        return "bot"
    if name.startswith("installer"):
        return "installer"
    if name.startswith("doctor"):
        return "doctor"
    return "other"


def directory() -> Path:
    return Path(config.LOG_DIR)


def collect() -> list[LogFile]:
    """Все журналы, новые сверху."""
    root = directory()
    if not root.exists():
        return []
    found: list[LogFile] = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        if not any(pattern.match(path.name) for pattern in PATTERNS):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found.append(LogFile(path, _classify(path.name), stat.st_size, stat.st_mtime))
    return sorted(found, key=lambda item: item.modified, reverse=True)


def by_kind() -> dict[str, list[LogFile]]:
    grouped: dict[str, list[LogFile]] = {}
    for item in collect():
        grouped.setdefault(item.kind, []).append(item)
    return grouped


def find(name: str) -> LogFile | None:
    """Ищет журнал по имени. Имя проверяется, чтобы нельзя было выйти из каталога."""
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    return next((item for item in collect() if item.name == name), None)


def tail(item: LogFile, lines: int = 60) -> str:
    """Последние строки журнала — для быстрого просмотра прямо в чате."""
    try:
        with item.path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(handle.readlines()[-lines:])
    except OSError as exc:
        return f"Не удалось прочитать: {exc}"


def read_bytes(item: LogFile, limit_mb: int = 20) -> bytes | None:
    limit = limit_mb * 1024 * 1024
    try:
        with item.path.open("rb") as handle:
            if item.size <= limit:
                return handle.read()
            # Слишком большой файл отдаём хвостом: начало обычно уже неактуально
            handle.seek(item.size - limit)
            return "…[начало файла обрезано]…\n".encode("utf-8") + handle.read()
    except OSError as exc:
        log.warning("Журнал %s не прочитан: %s", item.name, exc)
        return None


def archive(kinds: set[str] | None = None) -> tuple[bytes, str, int] | None:
    """Собирает журналы в tar.gz. Возвращает (данные, имя файла, число файлов)."""
    items = [item for item in collect() if kinds is None or item.kind in kinds]
    if not items:
        return None

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for item in items:
            try:
                bundle.add(item.path, arcname=f"{item.kind}/{item.name}")
            except OSError as exc:
                log.warning("Журнал %s не добавлен: %s", item.name, exc)

        summary = (
            f"Система «Радар» v{config.VERSION}\n"
            f"Собрано: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n"
            f"Файлов: {len(items)}\n\n"
            + "\n".join(f"{item.kind:<10} {item.name:<44} {item.size_human}" for item in items)
        ).encode("utf-8")
        info = tarfile.TarInfo("manifest.txt")
        info.size = len(summary)
        info.mtime = int(time.time())
        bundle.addfile(info, io.BytesIO(summary))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return buffer.getvalue(), f"radar-logs-{config.VERSION}-{stamp}.tar.gz", len(items)


def purge(kinds: set[str] | None = None, keep_current: bool = True) -> tuple[int, int]:
    """Удаляет журналы. Возвращает (сколько удалено, сколько байт освобождено).

    Текущий `bot.log` по умолчанию не трогаем: он открыт на запись, и его
    удаление оставило бы систему без журнала до перезапуска.
    """
    removed = 0
    freed = 0
    for item in collect():
        if kinds is not None and item.kind not in kinds:
            continue
        if keep_current and item.name == "bot.log":
            continue
        try:
            size = item.size
            item.path.unlink()
            removed += 1
            freed += size
        except OSError as exc:
            log.warning("Не удалось удалить %s: %s", item.name, exc)
    if removed:
        log.info("Удалено журналов: %d, освобождено %d КБ", removed, freed // 1024)
    return removed, freed


def purge_old(days: int | None = None) -> int:
    """Чистка по возрасту — вызывается при старте."""
    keep = config.LOG_KEEP_DAYS if days is None else days
    if keep <= 0:
        return 0
    edge = time.time() - keep * 86400
    removed = 0
    for item in collect():
        if item.name == "bot.log" or item.modified >= edge:
            continue
        try:
            item.path.unlink()
            removed += 1
        except OSError:
            pass
    if removed:
        log.info("Удалено журналов старше %d дней: %d", keep, removed)
    return removed


def total_size() -> int:
    return sum(item.size for item in collect())


def ensure_directory() -> None:
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
    except OSError as exc:
        log.warning("Каталог журналов недоступен: %s", exc)
