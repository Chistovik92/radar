#!/usr/bin/env python3
"""Поиск обращений к именам, которые нигде не определены и не импортированы.

Зачем нужен: `NameError` возникает только в момент выполнения строки, поэтому
ни импорт модуля, ни сверка перекрёстных имён его не ловят. Ровно так в 4.0.0
уехал в продакшен `main.py` с потерянным импортом `db_engine` — бот падал
в цикле рестарта, хотя все проверки были зелёными.

    python3 tools/lint_undefined.py
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import ast
import builtins
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "data", "migrations"}

BUILTINS = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__builtins__", "__debug__", "__loader__", "__annotations__",
}


class Scope:
    """Имена, определённые в области видимости."""

    def __init__(self, parent: "Scope | None" = None, transparent: bool = False):
        self.parent = parent
        self.names: set[str] = set()
        # Тело класса не видно вложенным функциям, но видно своим выражениям.
        self.transparent = transparent

    def add(self, name: str) -> None:
        if name:
            self.names.add(name)

    def has(self, name: str) -> bool:
        scope: Scope | None = self
        first = True
        while scope is not None:
            if name in scope.names:
                return True
            # Пропускаем область класса при подъёме из вложенной функции
            if not first and scope.transparent:
                scope = scope.parent
                continue
            first = False
            scope = scope.parent
        return False


class Checker(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.problems: list[tuple[int, str]] = []
        self.module = Scope()
        self.scope = self.module
        self._collect_module_level()

    # -- сбор имён -------------------------------------------------------

    def _collect_module_level(self) -> None:
        """Имена уровня модуля видны отовсюду независимо от порядка строк."""
        source = self.path.read_text("utf-8")
        self.tree = ast.parse(source, filename=str(self.path))
        for node in ast.walk(self.tree):
            self._declare(node, self.module)

    def _declare(self, node: ast.AST, scope: Scope) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                scope.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    scope.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            scope.add(node.id)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                scope.add(name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            scope.add(node.name)
        elif isinstance(node, ast.arg):
            scope.add(node.arg)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and getattr(node, "name", None):
            scope.add(node.name)

    # -- обход -----------------------------------------------------------

    def run(self) -> list[tuple[int, str]]:
        for node in self.tree.body:
            self.visit(node)
        return self.problems

    def _nested(self, node: ast.AST, transparent: bool = False) -> None:
        outer = self.scope
        self.scope = Scope(outer, transparent=transparent)
        for child in ast.walk(node):
            if child is node:
                continue
            self._declare(child, self.scope)
        for child in ast.iter_child_nodes(node):
            self.visit(child)
        self.scope = outer

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._nested(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        self._nested(node, transparent=True)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._nested(node)

    def visit_comprehension_scope(self, node: ast.AST) -> None:
        self._nested(node)

    visit_ListComp = visit_comprehension_scope  # type: ignore[assignment]
    visit_SetComp = visit_comprehension_scope   # type: ignore[assignment]
    visit_DictComp = visit_comprehension_scope  # type: ignore[assignment]
    visit_GeneratorExp = visit_comprehension_scope  # type: ignore[assignment]

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return
        if node.id in BUILTINS or self.scope.has(node.id):
            return
        self.problems.append((node.lineno, node.id))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.visit(node.value)


def targets() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def main() -> int:
    problems: list[str] = []
    for path in targets():
        try:
            found = Checker(path).run()
        except SyntaxError as exc:
            problems.append(f"{path.relative_to(ROOT)}: синтаксис — {exc}")
            continue
        for line, name in found:
            problems.append(f"{path.relative_to(ROOT)}:{line}: имя «{name}» не определено")

    for problem in problems:
        print(f"  ✗ {problem}")
    if problems:
        print(f"\nНайдено обращений к неопределённым именам: {len(problems)}")
        return 1
    print(f"Неопределённых имён нет ({len(targets())} файлов).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
