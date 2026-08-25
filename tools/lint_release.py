#!/usr/bin/env python3
"""Проверка того, что номер версии поднят везде.

Правило проекта гласит: «номер правится разом везде». Правило,
за которым никто не следит, соблюдается ровно до первой спешки —
и именно это произошло.

**Поломка, ради которой написана проверка.** Список `RELEASES` в `main.py`
остановился на 4.7.5.2, а `build_changelog` берёт из него два верхних
выпуска. В результате после каждого обновления администрация получала одно
и то же сообщение про 4.7.5.2 — при том что заголовок показывал настоящую
версию. То есть сообщение не просто устарело, оно вводило в заблуждение:
«v4.7.10», а под ним изменения полугодовой давности. Продержалось это
восемь выпусков, потому что проверять было нечем.

Что сверяется:

* верхняя запись `RELEASES` — это текущая версия;
* версия есть в таблице истории `docs/STATUS.md`;
* версия стоит в заголовках `README.md` и `README.en.md`;
* версия названа в `CLAUDE.md`.

Ничего из этого не ловится тестами: файлы согласованы между собой, но
каждый по отдельности синтаксически безупречен.
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


def current_version() -> str:
    """Версия из radar/__init__.py — единственный источник правды."""
    source = (ROOT / "radar" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if getattr(target, "id", "") == "__version__":
                return str(ast.literal_eval(node.value))
    raise SystemExit("radar/__init__.py: не найден __version__")


def latest_release() -> str:
    """Верхняя запись RELEASES из main.py.

    Разбираем через ast, а не импортом: main.py тянет за собой aiogram
    и всё остальное, а проверка должна работать на голом Python.
    """
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if not any(getattr(item, "id", "") == "RELEASES" for item in targets):
            continue
        value = node.value
        if not isinstance(value, (ast.List, ast.Tuple)) or not value.elts:
            return ""
        first = value.elts[0]
        if isinstance(first, ast.Tuple) and first.elts:
            return str(ast.literal_eval(first.elts[0]))
    return ""


def main() -> int:
    version = current_version()
    problems: list[str] = []

    top = latest_release()
    if not top:
        problems.append("main.py: список RELEASES пуст или не разобран")
    elif top != version:
        problems.append(
            f"main.py: верхняя запись RELEASES — {top}, а версия {version}.\n"
            f"      Администрация получит changelog от {top} с заголовком "
            f"«v{version}» — сообщение будет вводить в заблуждение.\n"
            f"      Добавьте запись про {version} в начало RELEASES."
        )

    checks = [
        ("docs/STATUS.md", f"| {version} |", "нет строки в таблице истории версий"),
        ("docs/STATUS.md", f"**Версия:** {version}", "не обновлён заголовок"),
        ("README.md", f"v{version}", "не обновлён заголовок"),
        ("README.en.md", f"v{version}", "не обновлён заголовок"),
        ("CLAUDE.md", version, "не названа текущая версия"),
    ]
    for name, needle, complaint in checks:
        path = ROOT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # В STATUS строка истории выделяется жирным для текущей версии.
        if needle not in text and f"| **{version}** |" not in text:
            problems.append(f"{name}: {complaint} ({version})")

    if problems:
        print(f"Версия {version} проставлена не везде:\n")
        for item in problems:
            print(f"  {item}")
        print()
        return 1

    print(f"Версия {version} согласована во всех файлах")
    return 0


if __name__ == "__main__":
    sys.exit(main())
