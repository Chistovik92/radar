#!/usr/bin/env python3
"""Проверки установщика, которых не делает `bash -n`.

Синтаксис у обеих пойманных здесь поломок был безупречный — ломались
значения и полнота словаря. Обе дошли до сервера.

**1. Числовые подстановки.** В 4.7.6 на сервере печаталось:

    install.sh: line 1771: [: 0\\n0: integer expression expected

Виновата конструкция

    UPGRADABLE=$(apt-get -s upgrade | grep -c '^Inst' || echo 0)

`grep -c` печатает «0» И ПРИ ЭТОМ выходит с кодом 1, когда совпадений
нет. Поэтому `|| echo 0` дописывал второй ноль, переменная становилась
двухстрочной, и сравнение падало. Установку это не останавливало —
ошибка просто вылезала в отчёт при каждом запуске на актуальной системе,
где обновлять нечего. То есть ровно в самом обычном случае.

**2. Полнота словаря.** У установщика два блока `case` — английский
и русский. Ключ, заведённый только в одном, молча отдаёт пустую строку:
человек видит дыру в интерфейсе, а `bash -n` доволен. Проверяем, что
каждый используемый ключ определён и определён РОВНО ДВАЖДЫ.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "tools" / "install.template.sh"
SHELL_FILES = [ROOT / "install.sh", TEMPLATE] + sorted(ROOT.glob("tools/*.sh"))

# Подстановка $( ... ) без вложенных скобок — этого хватает: проблемные
# места всегда однострочные конвейеры.
SUBSTITUTION = re.compile(r"\$\((?P<body>[^()]*)\)")
COUNTING = re.compile(r"\bgrep\s+(-\w+\s+)*-\w*c\b|\bgrep\s+--count\b")
FALLBACK_ECHO = re.compile(r"\|\|\s*echo\b")

KEY_USED = re.compile(r"\$\(t\s+([a-z0-9_]+)\)")
KEY_DEFINED = re.compile(r"^\s+([a-z0-9_]+)\)\s+value=", re.M)


def numeric_problems() -> list[str]:
    """`grep -c` вместе с `|| echo` — получится два числа вместо одного."""
    found: list[str] = []
    for target in SHELL_FILES:
        if not target.exists():
            continue
        for number, line in enumerate(target.read_text(encoding="utf-8").split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for match in SUBSTITUTION.finditer(line):
                body = match.group("body")
                if COUNTING.search(body) and FALLBACK_ECHO.search(body):
                    found.append(
                        f"{target.relative_to(ROOT)}:{number}: "
                        f"«grep -c» вместе с «|| echo» — получится два числа\n"
                        f"      {stripped}\n"
                        f"      замените «|| echo 0» на «|| true» и приведите "
                        f"значение к числу отдельно"
                    )
                    break
    return found


def dictionary_problems() -> list[str]:
    """Каждый ключ должен быть определён ровно дважды: ru и en."""
    if not TEMPLATE.exists():
        return []

    text = TEMPLATE.read_text(encoding="utf-8")
    used = set(KEY_USED.findall(text))
    counts = Counter(KEY_DEFINED.findall(text))
    problems: list[str] = []

    for key in sorted(used - set(counts)):
        problems.append(f"ключ «{key}» используется, но нигде не определён")

    for key in sorted(used):
        seen = counts.get(key, 0)
        if seen == 1:
            problems.append(
                f"ключ «{key}» определён один раз — "
                f"нет перевода на один из языков"
            )
        elif seen > 2:
            problems.append(
                f"ключ «{key}» определён {seen} раза — "
                f"лишнее определение молча перекроет нужное"
            )

    return problems


def main() -> int:
    numeric = numeric_problems()
    dictionary = dictionary_problems()

    if numeric:
        print("Небезопасные числовые подстановки:\n")
        for item in numeric:
            print(f"  {item}\n")

    if dictionary:
        print("Словарь установщика:\n")
        for item in dictionary:
            print(f"  {item}")
        print()

    if numeric or dictionary:
        return 1

    keys = len(set(KEY_USED.findall(TEMPLATE.read_text(encoding="utf-8")))) \
        if TEMPLATE.exists() else 0
    print(
        f"Установщик в порядке: числовые подстановки безопасны, "
        f"словарь полон ({keys} ключей на двух языках)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
