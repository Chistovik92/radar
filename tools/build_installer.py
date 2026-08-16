#!/usr/bin/env python3
"""Собирает автономный install.sh, встраивая все исходники проекта.

    python3 tools/build_installer.py

Файлы попадают в установщик в виде heredoc-блоков, поэтому install.sh
не требует git и разворачивает проект одной командой.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "tools" / "install.template.sh"
OUTPUT = ROOT / "install.sh"

# Порядок важен только для читаемости логов установки.
MANIFEST = [
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "alembic.ini",
    ".dockerignore",
    "main.py",
    "radar/__init__.py",
    "radar/config.py",
    "radar/textutils.py",
    "radar/roles.py",
    "radar/ratelimit.py",
    "radar/matching.py",
    "radar/identity.py",
    "radar/features.py",
    "radar/logs.py",
    "radar/presets.py",
    "radar/sourcecheck.py",
    "radar/sos.py",
    "radar/media.py",
    "radar/secrets.py",
    "radar/aibench.py",
    "radar/proxy.py",
    "radar/provider.py",
    "radar/digest.py",
    "radar/quiet.py",
    "radar/backup.py",
    "radar/weather_image.py",
    "radar/web/__init__.py",
    "radar/web/auth.py",
    "radar/web/audit.py",
    "radar/web/panel.py",
    "radar/web/backup.py",
    "radar/db/__init__.py",
    "radar/db/models.py",
    "radar/db/engine.py",
    "radar/db/repo.py",
    "radar/db/importer.py",
    "radar/doctor.py",
    "migrations/env.py",
    "migrations/script.py.mako",
    "migrations/versions/0001_initial.py",
    "radar/platforms/__init__.py",
    "radar/platforms/base.py",
    "radar/platforms/max.py",
    "radar/storage.py",
    "radar/exporting.py",
    "radar/ai.py",
    "radar/geocode.py",
    "radar/weather.py",
    "radar/sources.py",
    "radar/tg.py",
    "radar/keyboards.py",
    "radar/states.py",
    "radar/middlewares.py",
    "radar/monitor.py",
    "radar/handlers/__init__.py",
    "radar/handlers/common.py",
    "radar/handlers/locations.py",
    "radar/handlers/settings.py",
    "radar/handlers/sources.py",
    "radar/handlers/users.py",
    "radar/handlers/features.py",
    "radar/handlers/logs.py",
    "radar/handlers/sos.py",
    "radar/handlers/media.py",
    "radar/handlers/settings_admin.py",
    "radar/handlers/network.py",
    "radar/handlers/digest.py",
    "radar/handlers/assistant.py",
]

def version() -> str:
    source = (ROOT / "radar" / "__init__.py").read_text("utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', source, re.M)
    if not match:
        sys.exit("Не найден __version__ в radar/__init__.py")
    return match.group(1)


def render_files() -> str:
    directories = sorted({os.path.dirname(name) for name in MANIFEST if os.path.dirname(name)})
    lines: list[str] = []
    if directories:
        lines.append("mkdir -p " + " ".join(f'"{d}"' for d in directories))
    lines.append(f"FILE_COUNT={len(MANIFEST)}")

    for index, name in enumerate(MANIFEST):
        path = ROOT / name
        if not path.exists():
            sys.exit(f"Файл манифеста отсутствует: {name}")
        body = path.read_text("utf-8").rstrip("\n")
        delimiter = f"RADAR_FILE_{index:02d}"
        for line in body.splitlines():
            if line.strip() == delimiter:
                sys.exit(f"{name} содержит строку-разделитель {delimiter}")
        lines.append(f'printf "  %s·%s %s\\n" "$C_DIM" "$C_RESET" "{name}"')
        lines.append(f'cat > "{name}" <<\'{delimiter}\'')
        lines.append(body)
        lines.append(delimiter)
    return "\n".join(lines)


def main() -> None:
    current = version()
    template = TEMPLATE.read_text("utf-8")
    if "@@FILES@@" not in template:
        sys.exit("В шаблоне нет маркера @@FILES@@")
    result = template.replace("@@VERSION@@", current).replace("@@FILES@@", render_files())
    OUTPUT.write_text(result, encoding="utf-8")
    OUTPUT.chmod(0o755)
    print(
        f"install.sh собран: версия {current}, файлов {len(MANIFEST)}, "
        f"строк {result.count(chr(10)) + 1}"
    )


if __name__ == "__main__":
    main()
