"""Замер стадий цикла мониторинга и ресурсов контейнера.

Оптимизировать наугад — тратить время не там. Модуль отвечает на один
вопрос: куда уходят секунды одного прохода. Отдельно считаются сбор
источников, разбор ИИ и рассылка, потому что лечатся они по-разному:
сбор упирается в сеть, разбор — во внешний сервис, рассылка — в лимиты
Telegram.

Замер обязан быть дешевле того, что он измеряет: хранятся только
скользящие суммы по стадиям и последние проходы, ничего не пишется на
диск и не уходит в базу. Память ограничена сверху числом стадий.

Показания снимаются с /proc, без psutil: лишняя зависимость ради двух
файлов на слабом железе не окупается.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

log = logging.getLogger("radar.profiling")

HISTORY = 20              # сколько последних проходов помним
STAGES = ("sources", "vk", "ai", "dispatch", "digest", "save")


@dataclass
class Stage:
    """Накопленные показания одной стадии."""

    calls: int = 0
    total: float = 0.0
    worst: float = 0.0
    recent: list[float] = field(default_factory=list)

    def add(self, seconds: float) -> None:
        self.calls += 1
        self.total += seconds
        self.worst = max(self.worst, seconds)
        self.recent.append(seconds)
        del self.recent[:-HISTORY]

    @property
    def average(self) -> float:
        return self.total / self.calls if self.calls else 0.0

    @property
    def last(self) -> float:
        return self.recent[-1] if self.recent else 0.0


_stages: dict[str, Stage] = {}
_started_at = time.monotonic()


@contextmanager
def measure(stage: str) -> Iterator[None]:
    """Замеряет блок. Ошибку не глотает, но время всё равно записывает.

    Провалившаяся стадия — тоже показание: обращение к недоступному
    сервису, висящее до таймаута, и есть та самая потерянная минута.
    """
    began = time.perf_counter()
    try:
        yield
    finally:
        _stages.setdefault(stage, Stage()).add(time.perf_counter() - began)


def reset() -> None:
    global _started_at
    _stages.clear()
    _started_at = time.monotonic()


def uptime() -> float:
    return time.monotonic() - _started_at


def snapshot() -> dict[str, Stage]:
    """Копия показаний в порядке стадий цикла."""
    ordered = {name: _stages[name] for name in STAGES if name in _stages}
    for name, stage in _stages.items():      # стадии вне списка — в конец
        ordered.setdefault(name, stage)
    return ordered


# --- ресурсы --------------------------------------------------------------

def memory_mb() -> float:
    """Занятая процессом память, МиБ. Ноль, если /proc недоступен."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[1])
    except (OSError, ValueError, IndexError):
        return 0.0
    return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)


def cpu_seconds() -> float:
    """Процессорное время процесса. Ноль, если недоступно."""
    try:
        times = os.times()
    except OSError:
        return 0.0
    return times.user + times.system


def load_average() -> tuple[float, float, float]:
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return (0.0, 0.0, 0.0)


def cpu_count() -> int:
    return os.cpu_count() or 1
