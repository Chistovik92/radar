#!/usr/bin/env python3
"""Проверка источников и удаление молчащих (с 5.9.2.1).

    python3 tools/prune_sources.py                  # только показать, что убрали бы
    python3 tools/prune_sources.py --days 60        # молчат дольше 60 дней
    python3 tools/prune_sources.py --dead           # и недоступные тоже
    python3 tools/prune_sources.py --yes            # действительно удалить

Это тонкая обёртка над `python -m radar.cli sources prune`: вся логика
живёт в `radar/sourceprune.py`, а сама проверка — в `radar/sourcecheck.py`,
тот же код использует кнопка в боте. Запускать на сервере, в каталоге
бота, откуда виден `data/` и `.env`; в контейнере —
`bash radarctl.sh sources prune --yes`.

Удаление выполняется только с --yes. Если недоступна большая часть списка
(похоже на сбой сети), оно отказывается работать без --force.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar import cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli.main(["sources", "prune", *sys.argv[1:]]))
