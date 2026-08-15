"""Журнал действий в панели: кто, когда и что менял.

Хранится в памяти процесса и в файле рядом с журналами бота. В базу
не пишется намеренно: журнал должен переживать и сбой базы тоже —
именно тогда он и нужен больше всего.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from .. import config

log = logging.getLogger("radar.web.audit")

MEMORY = 500


@dataclass(frozen=True)
class Record:
    when: str
    actor: str
    action: str
    detail: str = ""


_records: deque[Record] = deque(maxlen=MEMORY)


def record(actor: str, action: str, detail: str = "") -> None:
    entry = Record(
        when=f"{datetime.now():%d.%m %H:%M:%S}",
        actor=str(actor or "—"),
        action=action,
        detail=detail,
    )
    _records.append(entry)
    log.info("Панель: %s — %s %s", entry.actor, action, detail)

    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        path = os.path.join(config.LOG_DIR, "audit.log")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{entry.when}\t{entry.actor}\t{action}\t{detail}\n")
    except OSError:
        pass


def recent(limit: int = 100) -> list[Record]:
    return list(_records)[-limit:][::-1]


def clear() -> int:
    count = len(_records)
    _records.clear()
    return count
