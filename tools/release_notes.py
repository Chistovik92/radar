#!/usr/bin/env python3
"""Заголовок и текст релиза для автоматического выпуска (с 5.0).

Правило проекта: код в `main` без релиза ломает `install.sh --versions` —
установщик берёт список версий из релизов GitHub. Раньше тег и релиз
ставились руками после слияния, и 4.6.5 с 4.7.3.2 так и ушли без них.
Теперь это делает `.github/workflows/release.yml`, а здесь — то, что
ему нужно знать:

* версия — из `radar/__init__.py`, единственного источника правды;
* текст — из `docs/releases/<версия>.md`, если он написан руками:
  первая строка `# …` становится заголовком релиза, остальное — телом;
* иначе — из верхней записи `RELEASES` в `main.py` (то же, что получает
  администрация после обновления), с HTML-разметкой бота, переведённой
  в Markdown.

Запуск:

    python3 tools/release_notes.py version
    python3 tools/release_notes.py title
    python3 tools/release_notes.py body
    python3 tools/release_notes.py newer v4.9.9.4 v4.9.9.3 ...

`newer` завершается с ошибкой, если текущая версия не больше самой
старшей из переданных: номер только растёт, и выпуск назад не должен
стать «последним» релизом.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import ast
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def current_version(root: Path = ROOT) -> str:
    source = (root / "radar" / "__init__.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "__version__" for target in node.targets
        ):
            return str(ast.literal_eval(node.value))
    raise SystemExit("radar/__init__.py: не найден __version__")


def release_items(version: str, root: Path = ROOT) -> list[str]:
    """Пункты записи `RELEASES` для версии. Разбор через ast: main.py
    тянет aiogram, а выпуск должен работать на голом Python."""
    source = (root / "main.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        if not any(getattr(item, "id", "") == "RELEASES" for item in targets):
            continue
        for entry in ast.literal_eval(node.value):
            if entry and entry[0] == version:
                return [str(item) for item in entry[1]]
    return []


def to_markdown(text: str) -> str:
    """HTML-разметка сообщений бота → Markdown релиза."""
    text = re.sub(r"</?(b|strong)>", "**", text)
    text = re.sub(r"</?(i|em)>", "_", text)
    text = re.sub(r"</?code>", "`", text)
    text = re.sub(r'<a href="([^"]+)">(.*?)</a>', r"[\2](\1)", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def notes(version: str, root: Path = ROOT) -> tuple[str, str]:
    """(заголовок, тело) релиза."""
    written = root / "docs" / "releases" / f"{version}.md"
    if written.exists():
        lines = written.read_text(encoding="utf-8").strip().splitlines()
        if lines and lines[0].startswith("# "):
            return lines[0][2:].strip(), "\n".join(lines[1:]).strip() + "\n"
        return f"v{version}", "\n".join(lines).strip() + "\n"

    items = release_items(version, root)
    if not items:
        raise SystemExit(
            f"Нет текста для v{version}: ни docs/releases/{version}.md, "
            f"ни записи в RELEASES")
    body = "\n".join(f"- {to_markdown(item)}" for item in items)
    return f"v{version}", body + "\n"


def parse(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.lstrip("v").split("."))


def is_newer(version: str, tags: list[str]) -> bool:
    """Больше ли версия каждого из тегов. Чужие теги (не vX.Y…) не в счёт."""
    known = []
    for tag in tags:
        try:
            known.append(parse(tag))
        except ValueError:
            continue
    return not known or parse(version) > max(known)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, rest = argv[0], argv[1:]
    version = current_version()
    if command == "version":
        print(version)
    elif command == "title":
        print(notes(version)[0])
    elif command == "body":
        sys.stdout.write(notes(version)[1])
    elif command == "newer":
        if not is_newer(version, rest):
            print(f"v{version} не больше уже выпущенных — номер только растёт",
                  file=sys.stderr)
            return 1
    else:
        print(f"Неизвестная команда: {command}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
