#!/usr/bin/env python3
"""Статическая сверка имён внутри пакета radar.

Проверяет два класса ошибок, которые иначе всплывают только в рантайме:
  1. `from .module import name` — имени нет в модуле;
  2. `module.attribute` — атрибута нет среди объявлений модуля.

    python3 tools/lint_names.py
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "radar"

def public_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.If):  # блоки вида `if config.AI_ENABLED:`
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for target in sub.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
    return names


def module_path(name: str) -> str | None:
    parts = name.split(".")
    candidate = os.path.join(ROOT, *parts) + ".py"
    if os.path.exists(candidate):
        return candidate
    candidate = os.path.join(ROOT, *parts, "__init__.py")
    return candidate if os.path.exists(candidate) else None


def resolve(current: str, node: ast.ImportFrom, is_package: bool) -> str | None:
    if node.level == 0:
        return node.module if (node.module or "").startswith(PACKAGE) else None
    base = current.split(".")
    # Внутри __init__.py уровень 1 указывает на сам пакет, а не на родителя.
    strip = node.level - 1 if is_package else node.level
    base = base[: len(base) - strip] if strip <= len(base) else []
    if node.module:
        base = base + node.module.split(".")
    return ".".join(base) or None


def collect_files() -> list[tuple[str, str]]:
    files = [("main", os.path.join(ROOT, "main.py"))]
    for dirpath, _dirs, names in os.walk(os.path.join(ROOT, PACKAGE)):
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT)[:-3].replace(os.sep, ".")
            if rel.endswith(".__init__"):
                rel = rel[: -len(".__init__")]
            files.append((rel, path))
    return files


def shadowed_submodules() -> list[str]:
    """Ищет пакеты, где __init__.py вводит имя, совпадающее с подмодулем.

    Такое затенение ломает `from pkg import submodule`: вернётся не модуль,
    а то, что положил в пространство имён __init__.py, и обращение
    к атрибутам модуля упадёт с AttributeError уже в рантайме — ровно так
    `from radar.db import engine` отдавал функцию вместо модуля.
    """
    problems: list[str] = []
    for dirpath, _dirs, names in os.walk(os.path.join(ROOT, PACKAGE)):
        if "__init__.py" not in names:
            continue
        submodules = {
            name[:-3] for name in names
            if name.endswith(".py") and name != "__init__.py"
        }
        submodules |= {
            entry for entry in os.listdir(dirpath)
            if os.path.isdir(os.path.join(dirpath, entry))
            and os.path.exists(os.path.join(dirpath, entry, "__init__.py"))
        }
        if not submodules:
            continue
        init_path = os.path.join(dirpath, "__init__.py")
        with open(init_path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=init_path)
        introduced = public_names(tree)
        # Импорт самого подмодуля именем подмодуля — это не затенение
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                for alias in node.names:
                    name = alias.asname or alias.name
                    if alias.name in submodules and name == alias.name:
                        continue
        package = os.path.relpath(dirpath, ROOT).replace(os.sep, ".")
        for name in sorted(introduced & submodules):
            # Разрешено, если это импорт ровно того же подмодуля
            legal = any(
                isinstance(node, ast.ImportFrom)
                and node.level == 1
                and not node.module
                and any((alias.asname or alias.name) == name for alias in node.names)
                for node in ast.walk(tree)
            )
            if legal:
                continue
            problems.append(
                f"{package}/__init__.py: имя «{name}» затеняет подмодуль "
                f"{package}.{name}"
            )
    return problems


def main() -> int:
    cache: dict[str, set[str]] = {}

    def names_of(mod: str) -> set[str] | None:
        if mod in cache:
            return cache[mod]
        path = module_path(mod)
        if path is None:
            return None
        with open(path, encoding="utf-8") as handle:
            cache[mod] = public_names(ast.parse(handle.read()))
        return cache[mod]

    problems: list[str] = []
    for current, path in collect_files():
        is_package = os.path.basename(path) == "__init__.py"
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)

        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = resolve(current, node, is_package)
                if not target:
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    submodule = f"{target}.{alias.name}"
                    if module_path(submodule):
                        aliases[alias.asname or alias.name] = submodule
                        continue
                    available = names_of(target)
                    if available is None:
                        continue
                    if alias.name not in available:
                        problems.append(
                            f"{current}: из {target} импортируется «{alias.name}», "
                            f"но такого имени нет"
                        )

        for name, target in list(aliases.items()):
            available = names_of(target)
            if available is None:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == name
                    and node.attr not in available
                    and not node.attr.startswith("_")
                ):
                    problems.append(
                        f"{current}:{node.lineno}: {name}.{node.attr} — "
                        f"в модуле {target} такого имени нет"
                    )

    problems.extend(shadowed_submodules())

    for problem in sorted(set(problems)):
        print("  ✗", problem)
    if problems:
        print(f"\nНайдено замечаний: {len(set(problems))}")
        return 1
    print("Перекрёстные имена в порядке.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
