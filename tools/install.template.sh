#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

#
# Система «Радар» v@@VERSION@@ — автономный установщик.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh)
#
# Флаги:
#   --recreate-env   заново запросить токены и настройки
#   --no-cache       пересобрать образ без кэша Docker
#   --logs           показать логи после запуска
#   --uninstall      остановить и удалить контейнер и образ (данные сохраняются)
#
# Файл собирается автоматически: python3 tools/build_installer.py
# Правьте исходники проекта, а не install.sh.

set -Eeuo pipefail

VERSION="@@VERSION@@"
APP_DIR="${RADAR_HOME:-$HOME/radar_bot}"
IMAGE_NAME="${RADAR_IMAGE:-radar_image}"
CONTAINER_NAME="${RADAR_CONTAINER:-radar_container}"
RECREATE_ENV=false
NO_CACHE_FLAG=""
SHOW_LOGS=false
UNINSTALL=false

for arg in "$@"; do
    case "$arg" in
        --recreate-env) RECREATE_ENV=true ;;
        --no-cache)     NO_CACHE_FLAG="--no-cache" ;;
        --logs)         SHOW_LOGS=true ;;
        --uninstall)    UNINSTALL=true ;;
        -v|--version)   echo "radar $VERSION"; exit 0 ;;
        -h|--help)      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Неизвестный флаг: $arg" >&2; exit 1 ;;
    esac
done

info() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ERR]\033[0m %s\n' "$*" >&2; exit 1; }
trap 'die "Установка прервана (строка $LINENO)"' ERR

echo "==========================================================="
echo "        СИСТЕМА «РАДАР» v${VERSION} — установка"
echo "==========================================================="

command -v docker >/dev/null 2>&1 || die "Docker не установлен: https://docs.docker.com/engine/install/"
docker info >/dev/null 2>&1 || die "Docker-демон недоступен. Запустите его или добавьте пользователя в группу docker."

if [ "$UNINSTALL" = true ]; then
    info "Удаляю контейнеры и образ (данные в $APP_DIR/data сохраняются)"
    (cd "$APP_DIR" 2>/dev/null && docker compose down --remove-orphans) >/dev/null 2>&1 || true
    docker stop "$CONTAINER_NAME" radar_db >/dev/null 2>&1 || true
    docker rm "$CONTAINER_NAME" radar_db >/dev/null 2>&1 || true
    docker rmi "$IMAGE_NAME" >/dev/null 2>&1 || true
    ok "Готово."
    exit 0
fi

[ -e /dev/tty ] || die "Нет интерактивного терминала для ввода настроек."

# --- 1. Каталог -----------------------------------------------------------
info "Каталог установки: $APP_DIR"
mkdir -p "$APP_DIR/data"
cd "$APP_DIR"
chmod 700 "$APP_DIR" 2>/dev/null || true
chown -R 1000:1000 "$APP_DIR/data" 2>/dev/null || chmod -R a+rwX "$APP_DIR/data"

if [ -f "$APP_DIR/bot.py" ] && [ ! -d "$APP_DIR/radar" ]; then
    warn "Обнаружена установка версии 2.x — переношу bot.py в bot.py.bak-2x"
    mv -f "$APP_DIR/bot.py" "$APP_DIR/bot.py.bak-2x"
fi

# --- 2. Файлы проекта -----------------------------------------------------
info "Разворачиваю файлы проекта"
@@FILES@@
ok "Файлы записаны"

# --- 3. Настройки ---------------------------------------------------------
ask() { # ask <подсказка> <переменная> <regexp> <обязательно yes|no>
    local prompt="$1" varname="$2" pattern="$3" required="$4" value=""
    while true; do
        read -r -p "$prompt" value < /dev/tty || true
        value="$(printf '%s' "$value" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
        if [ -z "$value" ] && [ "$required" = "no" ]; then break; fi
        if [ -z "$value" ]; then warn "Значение не может быть пустым."; continue; fi
        if [ -n "$pattern" ] && ! printf '%s' "$value" | grep -Eq "$pattern"; then
            warn "Формат не распознан, проверьте значение."; continue
        fi
        break
    done
    printf -v "$varname" '%s' "$value"
}

if [ -f .env ] && [ "$RECREATE_ENV" = false ]; then
    read -r -p "Файл .env найден. Использовать текущие настройки? (Y/n): " reply < /dev/tty || true
    case "${reply:-y}" in
        [Nn]*) RECREATE_ENV=true ;;
        *) ok "Использую существующий .env" ;;
    esac
else
    RECREATE_ENV=true
fi

if [ "$RECREATE_ENV" = true ]; then
    echo
    echo "Заполните параметры (Ctrl+C — выход):"
    ask "  Токен Telegram-бота (@BotFather): " IN_TOKEN '^[0-9]{6,}:[A-Za-z0-9_-]{30,}$' yes
    ask "  Ваш Telegram ID (@userinfobot): " IN_ADMIN '^[0-9]{5,}$' yes
    ask "  Ключ Google Gemini (Enter — без ИИ): " IN_GEMINI '^.{20,}$' no
    ask "  Пароль базы данных (Enter — сгенерировать): " IN_DBPASS '^.{8,}$' no
    if [ -z "${IN_DBPASS:-}" ]; then
        IN_DBPASS="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
        echo "  Сгенерирован пароль базы: $IN_DBPASS"
    fi
    ask "  Часовой пояс [Europe/Saratov]: " IN_TZ '^[A-Za-z]+/[A-Za-z_+-]+$' no
    ask "  Город по умолчанию [Саратов]: " IN_CITY '.+' no
    echo "  Наборы источников: saratov, moscow, spb, kazan, samara (через запятую)"
    ask "  Какие подключить [saratov]: " IN_PRESET '^[a-z, ]+$' no
    : "${IN_TZ:=Europe/Saratov}"
    : "${IN_CITY:=Саратов}"
    : "${IN_PRESET:=saratov}"

    umask 077
    cat > .env <<ENVEOF
BOT_TOKEN=${IN_TOKEN}
SUPERADMIN_ID=${IN_ADMIN}
GEMINI_API_KEY=${IN_GEMINI:-}
DB_PASSWORD=${IN_DBPASS}
DB_HOST=postgres
DB_PORT=5432
DB_NAME=radar
DB_USER=radar
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
EVENT_RETENTION_DAYS=180
MAX_BOT_TOKEN=
MAX_API_URL=https://platform-api2.max.ru
MAX_MODE=polling
GEMINI_MODEL=gemini-3.6-flash
GEMINI_MODEL_ANALYSIS=gemini-3.5-flash-lite
AI_CONCURRENCY=2
AI_TIMEOUT=90
AI_RPM=10
AI_RPD=250
AI_RESERVE=40
AI_BATCH_SIZE=8
AI_COOLDOWN=900
AI_PREFILTER=1
AI_SEARCH=1
TZ=${IN_TZ}
DEFAULT_CITY=${IN_CITY}
SOURCE_CITIES=${IN_PRESET}
POLL_INTERVAL=180
MSG_PER_SOURCE=5
CLUSTER_RADIUS_M=1000
MAX_LOCATIONS=0
EXTRA_CHANNELS=
EXTRA_RSS=
LOG_LEVEL=INFO
PROMO_ENABLED=1
PROMO_TITLE=🐙 HydraSite
PROMO_URL=https://t.me/+WWJFBZVhxBs4ZmNi
PROMO_IN_ALERTS=0
ENVEOF
    umask 022
    chmod 600 .env
    ok "Файл .env создан"
    [ -z "${IN_GEMINI:-}" ] && warn "Ключ Gemini не задан: ассистент отключён, анализ пойдёт по ключевым словам."
fi

TZ_VALUE="$(grep -E '^TZ=' .env | cut -d= -f2- || true)"
: "${TZ_VALUE:=Europe/Saratov}"

# --- 4. Сборка и запуск ---------------------------------------------------
COMPOSE="docker compose"
if ! docker compose version >/dev/null 2>&1; then
    if command -v docker-compose >/dev/null 2>&1; then
        COMPOSE="docker-compose"
    else
        die "Нужен Docker Compose: https://docs.docker.com/compose/install/"
    fi
fi

TZ_VALUE="$(grep -E '^TZ=' .env | cut -d= -f2- || true)"
: "${TZ_VALUE:=Europe/Saratov}"

info "Останавливаю прежние контейнеры"
$COMPOSE down --remove-orphans >/dev/null 2>&1 || true
# Наследие версий 3.x: одиночный контейнер без compose
docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true

mkdir -p "$APP_DIR/data/postgres"
chown -R 999:999 "$APP_DIR/data/postgres" 2>/dev/null || true

info "Сборка и запуск (бот + PostgreSQL)"
$COMPOSE up -d --build $NO_CACHE_FLAG || die "Не удалось поднять контейнеры"

info "Жду готовности базы и первого запуска"
for _ in $(seq 1 60); do
    state="$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo false)"
    [ "$state" = "true" ] && break
    sleep 2
done

if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null)" != "true" ]; then
    warn "Бот не запустился. Последние строки лога:"
    docker logs --tail 60 "$CONTAINER_NAME" 2>/dev/null || true
    warn "Лог базы данных:"
    docker logs --tail 20 radar_db 2>/dev/null || true
    exit 1
fi

trap - ERR
ok "Система «Радар» v${VERSION} запущена."
echo
echo "  Логи бота:   docker logs -f $CONTAINER_NAME"
echo "  Логи базы:   docker logs -f radar_db"
echo "  Перезапуск:  cd $APP_DIR && $COMPOSE restart"
echo "  Остановка:   cd $APP_DIR && $COMPOSE down"
echo "  Резервная копия базы:"
echo "    docker exec radar_db pg_dump -U radar radar | gzip > radar-\$(date +%F).sql.gz"
echo
echo "  Откройте бота в Telegram и отправьте /start, затем пришлите геопозицию."
echo

if [ "$SHOW_LOGS" = true ]; then
    docker logs -f "$CONTAINER_NAME"
fi
