#!/usr/bin/env python3
"""Проверка того, что все модули бота попали в манифест установщика.

**Поломка, ради которой написана проверка.** В 4.8.4.4 появился модуль
`radar/timezones.py`, а список `MANIFEST` в `tools/build_installer.py`
остался прежним: установщик просто не разворачивал файл на сервере.
Локально всё было зелёным — тесты, `stubcheck`, все линтеры работают
с рабочим деревом, где файл на месте. На сервере бот падал бы при первом
же импорте, и понять причину по `ImportError` в журнале контейнера
непросто: файла нет, хотя версия «установилась успешно».

Поймать это иначе нечем. `build_installer.py` проверяет обратное — что
каждый файл манифеста существует; отсутствие файла В манифесте для него
норма. Dockerfile копирует каталог `radar` целиком, поэтому сборка из
клона репозитория тоже проходит, и расхождение видно только на живой
установке через `install.sh`.

Сверяется: каждый `.py` внутри `radar/` есть в манифесте. Обратная
сторона — файл в манифесте без файла на диске — остаётся за
`build_installer.py`, который на этом останавливается.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def manifest() -> list[str]:
    """Список MANIFEST из build_installer.py, прочитанный без импорта.

    Через ast, а не импортом: сборщик при импорте ничего не делает, но
    проверка должна оставаться независимой от его внутренностей.
    """
    source = (ROOT / "tools" / "build_installer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(getattr(item, "id", "") == "MANIFEST" for item in targets):
            return [str(item) for item in ast.literal_eval(node.value)]
    raise SystemExit("tools/build_installer.py: не найден MANIFEST")


def modules() -> list[str]:
    """Все модули бота — то, без чего он не запустится."""
    found: list[str] = []
    for path in sorted((ROOT / "radar").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        found.append(path.relative_to(ROOT).as_posix())
    return found


def main() -> int:
    listed = set(manifest())
    missing = [name for name in modules() if name not in listed]

    if missing:
        print("Модули бота отсутствуют в манифесте установщика:")
        for name in missing:
            print(f"  {name}")
        print()
        print("Добавьте их в MANIFEST в tools/build_installer.py и пересоберите")
        print("установщик, иначе на сервере файлов не будет и бот не поднимется.")
        return 1

    print(f"Манифест полон: модулей бота {len(modules())}, всего файлов {len(listed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
