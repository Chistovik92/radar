#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

# Запуск стенда в одноразовом Docker-контейнере — на хосте ничего ставить не нужно.
#
#   ./run.sh --probe
#   ./run.sh --providers groq,deepseek,zai --verbose
#   ./run.sh --list-models
#
set -Eeuo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "Нет .env — скопируйте .env.example и впишите ключи"; exit 1; }

docker run --rm -it \
    -v "$PWD:/bench" \
    -w /bench \
    --env-file .env \
    python:3.11-slim \
    bash -c "pip install --quiet --no-cache-dir -r requirements.txt && python bench.py $*"
