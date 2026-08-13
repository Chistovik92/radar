#!/usr/bin/env python3
"""Проставляет подпись автора в шапку всех исходных файлов проекта.

    python3 tools/stamp_headers.py           # проставить или обновить
    python3 tools/stamp_headers.py --check   # только проверить (для CI)

Подпись вставляется после docstring модуля и не дублируется при повторном
запуске: старый блок распознаётся по маркеру и заменяется целиком.
Единственный источник имени и версии — radar/__init__.py.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar import __author__, __license__, __url__  # noqa: E402

MARKER = "Автор:"

PY_BLOCK = (
    f"# {'-' * 74}\n"
    f"# Система «Радар» — мониторинг городских угроз и аварий ЖКХ\n"
    f"# Автор: {__author__} · {__url__}\n"
    f"# Лицензия: {__license__}\n"
    f"# {'-' * 74}\n"
)

SH_BLOCK = (
    f"# {'-' * 74}\n"
    f"# Система «Радар» — мониторинг городских угроз и аварий ЖКХ\n"
    f"# Автор: {__author__} · {__url__}\n"
    f"# Лицензия: {__license__}\n"
    f"# {'-' * 74}\n"
)

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "data", "migrations"}
SKIP_FILES = {"install.sh"}  # генерируется, подпись приходит из шаблона

BLOCK_RE = re.compile(
    r"# -{60,}\n# Система «Радар».*?\n# Автор:.*?\n# Лицензия:.*?\n# -{60,}\n",
    re.S,
)

def targets() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix in (".py", ".sh"):
            files.append(path)
    return files


def split_prelude(text: str, suffix: str) -> tuple[str, str]:
    """Отделяет то, что обязано остаться в самом верху файла.

    Для .py это shebang, кодировка и docstring модуля; для .sh — shebang.
    """
    lines = text.splitlines(keepends=True)
    index = 0

    if lines and lines[0].startswith("#!"):
        index += 1
    if suffix == ".py":
        while index < len(lines) and re.match(r"#.*coding[:=]", lines[index]):
            index += 1
        rest = "".join(lines[index:])
        match = re.match(r'\s*(?P<q>"""|\'\'\')', rest)
        if match:
            quote = match.group("q")
            start = rest.index(quote)
            end = rest.find(quote, start + 3)
            if end != -1:
                offset = end + 3
                return "".join(lines[:index]) + rest[:offset], rest[offset:]
    return "".join(lines[:index]), "".join(lines[index:])


def stamp(path: Path) -> tuple[bool, str]:
    """Возвращает (изменился ли файл, новое содержимое)."""
    original = path.read_text("utf-8")
    cleaned = BLOCK_RE.sub("", original)
    prelude, body = split_prelude(cleaned, path.suffix)

    block = PY_BLOCK if path.suffix == ".py" else SH_BLOCK
    body = body.lstrip("\n")
    # Сборка строго детерминированная: повторный запуск обязан дать тот же файл.
    if prelude:
        prelude = prelude.rstrip("\n") + "\n"
        updated = f"{prelude}\n{block}\n{body}"
    else:
        updated = f"{block}\n{body}"
    return updated != original, updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Подпись автора в шапке файлов")
    parser.add_argument("--check", action="store_true", help="только проверить")
    args = parser.parse_args()

    changed: list[Path] = []
    for path in targets():
        differs, content = stamp(path)
        if not differs:
            continue
        changed.append(path)
        if not args.check:
            path.write_text(content, encoding="utf-8")

    relative = [str(path.relative_to(ROOT)) for path in changed]
    if args.check:
        if changed:
            print("Без подписи или с устаревшей подписью:")
            for name in relative:
                print(f"  ✗ {name}")
            print("\nВыполните: python3 tools/stamp_headers.py")
            return 1
        print("Подпись на месте во всех файлах.")
        return 0

    if changed:
        print(f"Обновлено файлов: {len(changed)}")
        for name in relative:
            print(f"  ✓ {name}")
    else:
        print("Все файлы уже подписаны.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
