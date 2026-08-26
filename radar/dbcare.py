"""Компактность базы: чистка истории, сжатие файла, контроль размера.

Пункт 5 раздела 4.8. Три отдельные задачи, и каждая нужна по своей
причине.

**Чистка истории.** `purge_old_events` существовала с 4.0, но вызывалась
только при старте. Бот, работающий месяцами без перезапуска, не чистил
историю вовсе — а это ровно тот режим, ради которого он написан.

**Сжатие файла.** Здесь суть, которую легко упустить: **SQLite не отдаёт
место операционной системе после DELETE.** Строки помечаются свободными
и переиспользуются внутри файла, но сам файл не уменьшается никогда.
То есть чистка истории без `VACUUM` не освобождает ни байта на диске —
она лишь замедляет дальнейший рост. На одноплатнике, где место кончается
раньше терпения, это разница между «работает» и «база не пишется».

**PostgreSQL сжимаем иначе — то есть не сжимаем.** Там есть autovacuum,
который делает то же самое сам, а `VACUUM FULL` берёт исключительную
блокировку на всю таблицу: для системы оповещения это недопустимо.
Поэтому явное сжатие делается только для SQLite.

**Когда сжимать.** Только после того, как что-то действительно удалено:
`VACUUM` переписывает файл целиком и на большой базе занимает время,
в течение которого база заблокирована. Гонять его вхолостую каждую ночь
значило бы платить блокировкой ни за что.

**Место на диске.** `VACUUM` строит новый файл рядом со старым, поэтому
на время работы нужно вдвое больше места. Если его нет, сжатие
пропускается: попытка «освободить место» не должна быть тем, что
переполнит диск окончательно.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
from datetime import datetime

log = logging.getLogger("radar.dbcare")

# Ночью: переписывание файла заметно нагружает слабый процессор,
# а в четыре утра городские каналы молчат.
SCHEDULE_HOUR = 4
# Порог предупреждения. Полгигабайта на одноплатнике — уже повод
# посмотреть, что происходит: при обычной нагрузке база столько
# не набирает.
WARN_SIZE_MB = 500
# Ниже этого размера сжимать нечего: выигрыш меньше, чем стоимость
# блокировки.
MIN_VACUUM_MB = 5


def due_today(last_run: str, now: datetime) -> bool:
    """Пора ли обслуживать базу.

    Сравнение по дате, а не по часам: если сервер был выключен в четыре
    утра, обслуживание пройдёт при первой возможности, а не пропадёт
    до следующих суток. Та же логика, что у резервных копий.
    """
    if now.hour < SCHEDULE_HOUR:
        return False
    return last_run != now.strftime("%Y-%m-%d")


def format_size(size_bytes: float) -> str:
    """«12.4 МБ» — человеку нужен порядок, а не байты."""
    units = (("ГБ", 1024 ** 3), ("МБ", 1024 ** 2), ("КБ", 1024))
    for name, scale in units:
        if size_bytes >= scale:
            return f"{size_bytes / scale:.1f} {name}"
    return f"{int(size_bytes)} Б"


def sqlite_files(path: str) -> list[str]:
    """Файл базы и его спутники.

    В режиме WAL рядом лежат `-wal` и `-shm`, и журнал может весить
    больше самой базы. Считать только основной файл — значит показывать
    размер, не совпадающий с тем, что видно в `du`.
    """
    return [path, f"{path}-wal", f"{path}-shm"]


def measure_sqlite(path: str) -> int:
    """Суммарный размер базы SQLite в байтах. Нет файла — ноль."""
    total = 0
    for name in sqlite_files(path):
        try:
            total += os.path.getsize(name)
        except OSError:
            continue
    return total


def free_space(path: str) -> float:
    """Свободно байт там, где лежит база. Неизвестно — бесконечность."""
    import shutil

    probe = os.path.dirname(os.path.abspath(path)) or "."
    try:
        return float(shutil.disk_usage(probe).free)
    except OSError:
        return float("inf")


def can_vacuum(size_bytes: int, free_bytes: float) -> tuple[bool, str]:
    """Хватит ли места на сжатие и есть ли в нём смысл.

    `VACUUM` строит новый файл рядом со старым — нужно вдвое больше
    места. Попытка освободить место не должна стать тем, что окончательно
    переполнит диск.
    """
    if size_bytes < MIN_VACUUM_MB * 1024 * 1024:
        return False, "база меньше порога — сжимать нечего"
    if free_bytes < size_bytes * 2:
        return False, (
            f"нужно {format_size(size_bytes * 2)} свободного места, "
            f"а есть {format_size(free_bytes)}"
        )
    return True, ""


def size_report(size_bytes: int, backend: str) -> str:
    """Строка о размере базы для отчёта и предупреждения."""
    text = f"База ({backend}): {format_size(size_bytes)}"
    if size_bytes >= WARN_SIZE_MB * 1024 * 1024:
        text += (
            f"\n⚠️ Это больше {WARN_SIZE_MB} МБ. Проверьте "
            f"EVENT_RETENTION_DAYS и место на диске."
        )
    return text


async def vacuum_sqlite() -> tuple[int, int, str]:
    """Сжимает базу. Возвращает (было, стало, объяснение отказа).

    Перед сжатием переносим журнал WAL в основной файл: иначе `-wal`
    остаётся раздутым, и суммарный размер почти не меняется — самая
    обидная разновидность «сделали и не помогло».
    """
    from . import config
    from .db import engine as db_engine

    path = config.DB_FILE
    before = measure_sqlite(path)

    allowed, why = can_vacuum(before, free_space(path))
    if not allowed:
        return before, before, why

    try:
        from sqlalchemy import text

        raw = db_engine.get_engine()
        # VACUUM не выполняется внутри транзакции, поэтому нужен режим
        # AUTOCOMMIT — иначе SQLAlchemy обернёт его в BEGIN и получит
        # «cannot VACUUM from within a transaction».
        async with raw.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            await connection.execute(text("VACUUM"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Сжатие базы не удалось: %s", exc)
        return before, measure_sqlite(path), "сжатие не удалось, подробности в журнале"

    after = measure_sqlite(path)
    log.info("База сжата: %s -> %s", format_size(before), format_size(after))
    return before, after, ""


async def run_scheduled(now: datetime) -> str:
    """Ежедневное обслуживание. Пустая строка — не время или нечего делать."""
    from . import config
    from .db import repo

    try:
        last_run = str(await repo.get_meta("dbcare_last_run", "") or "")
    except Exception:  # noqa: BLE001
        log.exception("Не удалось прочитать отметку об обслуживании базы")
        return ""

    if not due_today(last_run, now):
        return ""

    parts: list[str] = []

    try:
        removed = await repo.purge_old_events()
    except Exception:  # noqa: BLE001
        log.exception("Чистка истории не удалась")
        removed = 0
    if removed:
        parts.append(f"удалено событий: {removed}")

    # Сжимаем только SQLite и только если что-то удалено: VACUUM
    # переписывает файл целиком и на время блокирует базу. Гонять его
    # вхолостую каждую ночь — платить блокировкой ни за что.
    if config.is_sqlite() and removed:
        before, after, why = await vacuum_sqlite()
        if why:
            parts.append(f"без сжатия ({why})")
        elif after < before:
            parts.append(f"освобождено {format_size(before - after)}")

    try:
        await repo.set_meta("dbcare_last_run", now.strftime("%Y-%m-%d"))
    except Exception:  # noqa: BLE001
        # Отметку не записали — завтра обслужим ещё раз. Это безвреднее,
        # чем не обслужить вовсе.
        log.warning("Отметка об обслуживании базы не сохранилась")

    return "; ".join(parts)
