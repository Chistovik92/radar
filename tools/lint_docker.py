#!/usr/bin/env python3
"""Сверяет инструкции COPY в Dockerfile с правилами .dockerignore.

Зачем нужен: в 4.0.8 сборка образа падала с «/tools/doctor.py not found»,
потому что Dockerfile копировал файл из каталога, целиком исключённого
из контекста сборки. Ошибка обнаруживается только в момент `docker build`
на сервере — то есть после того, как установщик уже отработал половину шагов.

    python3 tools/lint_docker.py
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"

COPY_RE = re.compile(r"^\s*COPY\s+(?P<args>.+?)\s*$", re.M)


def ignore_rules() -> list[tuple[str, bool]]:
    """Правила .dockerignore: (шаблон, это ли исключение из исключения)."""
    if not DOCKERIGNORE.exists():
        return []
    rules: list[tuple[str, bool]] = []
    for line in DOCKERIGNORE.read_text("utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("!"):
            rules.append((text[1:].strip(), True))
        else:
            rules.append((text, False))
    return rules


def is_excluded(path: str, rules: list[tuple[str, bool]]) -> str | None:
    """Возвращает шаблон, который исключает путь, либо None."""
    excluded_by: str | None = None
    for pattern, negated in rules:
        match = (
            path == pattern
            or path.startswith(pattern.rstrip("/") + "/")
            or fnmatch.fnmatch(path, pattern)
            or fnmatch.fnmatch(Path(path).name, pattern)
        )
        if match:
            excluded_by = None if negated else pattern
    return excluded_by


def copy_sources() -> list[str]:
    if not DOCKERFILE.exists():
        return []
    sources: list[str] = []
    for match in COPY_RE.finditer(DOCKERFILE.read_text("utf-8")):
        parts = [part for part in match.group("args").split() if not part.startswith("--")]
        if len(parts) < 2:
            continue
        sources.extend(parts[:-1])   # последний аргумент — путь назначения
    return sources


COMPOSE = ROOT / "docker-compose.yml"
REQUIRED_VAR = re.compile(r"\$\{(\w+):\?")


def compose_required_vars() -> list[str]:
    """Переменные вида ${VAR:?...} в compose-файле.

    Compose подставляет переменные во всём файле сразу, не разбирая профили.
    Поэтому обязательная переменная в сервисе под профилем роняет и обычную
    сборку — именно так падала установка 4.2.0, где ключи Bot API Server
    требовались даже при выключенной загрузке видео.
    """
    if not COMPOSE.exists():
        return []

    text = COMPOSE.read_text("utf-8")
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        found.extend(REQUIRED_VAR.findall(stripped))
    return sorted(set(found))


def main() -> int:
    if not DOCKERFILE.exists():
        print("Dockerfile не найден — проверять нечего.")
        return 0

    rules = ignore_rules()
    problems: list[str] = []

    for source in copy_sources():
        if any(char in source for char in "*?["):
            continue  # шаблоны проверять надёжно не получится

        target = ROOT / source
        if not target.exists():
            problems.append(f"COPY {source} — такого файла нет в проекте")
            continue

        pattern = is_excluded(source, rules)
        if pattern:
            problems.append(
                f"COPY {source} — исключён правилом «{pattern}» в .dockerignore; "
                f"сборка упадёт с «not found»"
            )

    for name in compose_required_vars():
        problems.append(
            f"docker-compose.yml: переменная ${{{name}:?}} обязательна — "
            f"Compose потребует её даже когда сервис выключен профилем"
        )

    for problem in problems:
        print(f"  ✗ {problem}")
    if problems:
        print(f"\nНайдено несоответствий: {len(problems)}")
        return 1

    print(
        f"Dockerfile и .dockerignore согласованы ({len(copy_sources())} инструкций COPY), "
        "обязательных переменных в compose нет."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
