"""Проверка жизни бота для HEALTHCHECK контейнера.

Запускается снаружи процесса — `python -m radar.health` — и потому смотрит
не в память, а на файл отметки, который фоновый цикл переписывает на каждом
витке. Смысл в том, что живой процесс и работающий мониторинг — разные вещи:
бот может исправно отвечать на команды, когда тревоги уже не приходят,
и никакая проверка «процесс запущен» этого не покажет.

Нездоровый контейнер сам по себе не перезапускается — за это отвечает сторож
внутри процесса. Проверка нужна, чтобы состояние было видно снаружи:
в `docker ps`, в панели и в чужом мониторинге.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import sys
import time
from pathlib import Path

from . import config

HEARTBEAT_FILE = "data/heartbeat"

# Запас поверх предела молчания: проверка не должна срабатывать раньше
# сторожа, иначе контейнер будет числиться больным ровно в тот момент,
# когда цикл уже поднимается заново.
GRACE = 120


def limit() -> int:
    return max(300, config.POLL_INTERVAL * 3) + GRACE


def check(now: float | None = None) -> tuple[bool, str]:
    """Жив ли фоновый цикл. Возвращает (здоров, объяснение)."""
    moment = now if now is not None else time.time()
    path = Path(HEARTBEAT_FILE)
    try:
        beat = int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        # Файла нет — бот только поднимается. Считать это поломкой нельзя:
        # первый проход по источникам занимает до минуты.
        return True, "отметки ещё нет, бот запускается"

    silent = int(moment - beat)
    if silent > limit():
        return False, f"цикл молчит {silent} с при пределе {limit()} с"
    return True, f"цикл отвечал {silent} с назад"


def main() -> int:
    healthy, reason = check()
    print(reason)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
