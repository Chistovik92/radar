#!/usr/bin/env python3
"""Проверка совместимости кода с той версией Python, что стоит в образе.

Зачем нужен отдельный инструмент: разработка может идти на Python 3.12,
а образ собран на 3.11. Часть синтаксиса, разрешённого в 3.12, старая версия
не принимает — и ошибка всплывает только при запуске контейнера.

Именно так в 4.2.7 уехал `aibench.py` с обратным слэшем внутри f-строки:
локально всё компилировалось, а бот на сервере падал с SyntaxError ещё
на импорте, не успев даже подключиться к базе.

Ни `py_compile`, ни `ast.parse(feature_version=...)` этого не ловят:
у f-строк отдельный токенизатор, и понижение версии на него не влияет.
Поэтому f-строки разбираются здесь вручную по тексту.

    python3 tools/lint_pyversion.py
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "data"}

DOCKERFILE = ROOT / "Dockerfile"
DEFAULT_TARGET = (3, 11)

TRIPLES = ('"""', "'''")
QUOTES = "\"'"
PREFIX_CHARS = "fFrRbBuU"


def target_version() -> tuple[int, int]:
    """Версия Python из Dockerfile: на ней код и будет исполняться."""
    if not DOCKERFILE.exists():
        return DEFAULT_TARGET
    match = re.search(r"FROM\s+python:(\d+)\.(\d+)", DOCKERFILE.read_text("utf-8"))
    if match:
        return int(match.group(1)), int(match.group(2))
    return DEFAULT_TARGET


def _skip_string(source: str, index: int, line: int) -> tuple[int, int, str]:
    """Пропускает строковый литерал. Возвращает (позиция после, строка, тело)."""
    triple = source[index:index + 3] in TRIPLES
    quote = source[index] * 3 if triple else source[index]
    index += len(quote)
    start = index
    length = len(source)

    while index < length:
        if source[index] == "\\":
            index += 2
            continue
        if source.startswith(quote, index):
            break
        if source[index] == "\n":
            line += 1
            if not triple:
                break
        index += 1

    body = source[start:index]
    return index + len(quote), line, body


def _fstring_literals(source: str) -> list[tuple[int, str, str]]:
    """Находит f-строки: (номер строки, кавычка, тело).

    Разбор ручной, а не через `tokenize`: начиная с Python 3.12 f-строка
    разбивается на отдельные токены, и целиком её оттуда уже не получить.
    Точность здесь не самоцель — достаточно уверенно находить реальные случаи.
    """
    results: list[tuple[int, str, str]] = []
    index = 0
    line = 1
    length = len(source)

    while index < length:
        char = source[index]

        if char == "\n":
            line += 1
            index += 1
            continue

        if char == "#":                       # комментарий до конца строки
            while index < length and source[index] != "\n":
                index += 1
            continue

        if char in PREFIX_CHARS:
            start = index
            while index < length and source[index] in PREFIX_CHARS:
                index += 1
            prefix = source[start:index]
            if index < length and source[index] in QUOTES and "f" in prefix.lower():
                quote = (
                    source[index] * 3 if source[index:index + 3] in TRIPLES
                    else source[index]
                )
                started = line
                index, line, body = _skip_string(source, index, line)
                results.append((started, quote, body))
                continue
            index = start + 1
            continue

        if char in QUOTES:                    # обычная строка — пропускаем
            index, line, _body = _skip_string(source, index, line)
            continue

        index += 1

    return results


def fstring_problems(path: Path, target: tuple[int, int]) -> list[str]:
    """Возможности f-строк, появившиеся только в Python 3.12 (PEP 701)."""
    if target >= (3, 12):
        return []

    problems: list[str] = []
    source = path.read_text("utf-8")

    for line, quote, body in _fstring_literals(source):
        for expression in re.findall(r"\{([^{}]*)\}", body):
            if "\\" in expression:
                problems.append(
                    f"{path.relative_to(ROOT)}:{line}: обратный слэш в выражении "
                    "f-строки — запрещён до Python 3.12"
                )
            if quote in expression:
                problems.append(
                    f"{path.relative_to(ROOT)}:{line}: кавычки того же типа внутри "
                    "f-строки — запрещены до Python 3.12"
                )
    return problems


def syntax_problems(path: Path, target: tuple[int, int]) -> list[str]:
    """Синтаксис, отвергаемый целевой версией."""
    try:
        ast.parse(path.read_text("utf-8"), filename=str(path), feature_version=target)
    except SyntaxError as exc:
        return [f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}"]
    return []


def targets() -> list[Path]:
    return [
        path for path in sorted(ROOT.rglob("*.py"))
        if not any(part in SKIP_DIRS for part in path.parts)
    ]


def main() -> int:
    target = target_version()
    problems: list[str] = []

    files = targets()
    for path in files:
        problems.extend(syntax_problems(path, target))
        problems.extend(fstring_problems(path, target))

    unique = list(dict.fromkeys(problems))
    for problem in unique:
        print(f"  ✗ {problem}")

    if unique:
        print(f"\nНесовместимо с Python {target[0]}.{target[1]}: {len(unique)} мест")
        return 1

    print(
        f"Совместимо с Python {target[0]}.{target[1]} "
        f"(файлов: {len(files)}, текущий интерпретатор "
        f"{sys.version_info.major}.{sys.version_info.minor})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
