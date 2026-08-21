#!/usr/bin/env python3
"""Проверка порядка определения функций в install.sh.

В bash функция должна быть ОПРЕДЕЛЕНА к моменту вызова, а не просто
присутствовать в файле. Установщик — один большой скрипт, и вызов,
переставленный выше определения, ломается только на живом сервере:
`bash -n` синтаксис проверяет, а порядок — нет.

Так уже дважды падала установка: сначала на `C_BOLD: unbound variable`,
потом на `fetch_versions: command not found`. Эта проверка ловит третий
раз до того, как он случится.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "install.sh"

DEFINITION = re.compile(r"^(\w+)\(\)\s*\{")
# Вызов на верхнем уровне: строка целиком состоит из имени функции.
TOP_LEVEL_CALL = re.compile(r"^([a-z_][a-z0-9_]*)$")


def main() -> int:
    if not TARGET.exists():
        print("install.sh не собран — сначала build_installer.py")
        return 1

    lines = TARGET.read_text(encoding="utf-8").split("\n")
    defined: dict[str, int] = {}
    problems: list[str] = []

    for number, line in enumerate(lines, 1):
        match = DEFINITION.match(line)
        if match and match.group(1) not in defined:
            defined[match.group(1)] = number
            continue

        call = TOP_LEVEL_CALL.match(line)
        if not call:
            continue
        name = call.group(1)
        # Интересуют только вызовы наших функций: слово, которое где-то
        # в файле объявлено как функция.
        if not any(DEFINITION.match(other) and DEFINITION.match(other).group(1) == name
                   for other in lines):
            continue
        where = defined.get(name)
        if where is None:
            problems.append(
                f"строка {number}: вызов {name}() до его определения"
            )

    if problems:
        print("Порядок функций в install.sh нарушен:")
        for item in problems:
            print(f"  {item}")
        return 1

    print(f"Порядок функций в install.sh верный (функций: {len(defined)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
