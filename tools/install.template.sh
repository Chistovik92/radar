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
#   --reinstall      принудительная полная переустановка (данные сохраняются)
#   --skip-updates   не обновлять пакеты системы
#   --uninstall      остановить и удалить контейнеры и образ (данные сохраняются)
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
FORCE_REINSTALL=false
SKIP_UPDATES=false
LOG_FILE=""
START_TS=$(date +%s)

ORIGINAL_ARGS="$*"

for arg in "$@"; do
    case "$arg" in
        --recreate-env) RECREATE_ENV=true ;;
        --no-cache)     NO_CACHE_FLAG="--no-cache" ;;
        --logs)         SHOW_LOGS=true ;;
        --reinstall)    FORCE_REINSTALL=true; NO_CACHE_FLAG="--no-cache" ;;
        --skip-updates) SKIP_UPDATES=true ;;
        --uninstall)    UNINSTALL=true ;;
        -v|--version)   echo "radar $VERSION"; exit 0 ;;
        -h|--help)      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Неизвестный флаг: $arg" >&2; exit 1 ;;
    esac
done

# --------------------------------------------------------------------------
#  Логирование и оформление
# --------------------------------------------------------------------------

COLS=$( (tput cols 2>/dev/null || echo 72) )
[ "$COLS" -gt 78 ] && COLS=78
[ "$COLS" -lt 48 ] && COLS=48

if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'
    C_CYAN=$'\033[1;36m'; C_GREEN=$'\033[1;32m'
    C_YELLOW=$'\033[1;33m'; C_RED=$'\033[1;31m'; C_BLUE=$'\033[1;34m'
else
    C_RESET=""; C_DIM=""; C_BOLD=""; C_CYAN=""; C_GREEN=""
    C_YELLOW=""; C_RED=""; C_BLUE=""
fi

STEP_CURRENT=0
STEP_TOTAL=8

# Лог пишется целиком, включая то, что на экран не попадает.
log_raw() {
    [ -n "$LOG_FILE" ] && printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
    return 0
}

line()  { printf "%s%s%s\n" "$C_DIM" "$(printf '─%.0s' $(seq 1 "$COLS"))" "$C_RESET"; }
step()  {
    STEP_CURRENT=$((STEP_CURRENT + 1))
    printf "\n%s[%d/%d]%s %s%s%s\n" "$C_BLUE" "$STEP_CURRENT" "$STEP_TOTAL" \
        "$C_RESET" "$C_BOLD" "$*" "$C_RESET"
    log_raw "=== ШАГ $STEP_CURRENT/$STEP_TOTAL: $* ==="
}
info() { printf "  %s→%s %s\n" "$C_CYAN" "$C_RESET" "$*"; log_raw "INFO  $*"; }
ok()   { printf "  %s✓%s %s\n" "$C_GREEN" "$C_RESET" "$*"; log_raw "OK    $*"; }
warn() { printf "  %s!%s %s\n" "$C_YELLOW" "$C_RESET" "$*"; log_raw "WARN  $*"; }
fail() { printf "  %s✗%s %s\n" "$C_RED" "$C_RESET" "$*"; log_raw "FAIL  $*"; }
die()  {
    printf "\n%s✗ %s%s\n" "$C_RED" "$*" "$C_RESET" >&2
    log_raw "ERROR $*"
    [ -n "$LOG_FILE" ] && printf "  Полный лог: %s\n" "$LOG_FILE" >&2
    exit 1
}
run()  {  # выполнить команду, весь вывод — только в лог
    log_raw "CMD   $*"
    if [ -n "$LOG_FILE" ]; then
        "$@" >> "$LOG_FILE" 2>&1
    else
        "$@" >/dev/null 2>&1
    fi
}

trap 'die "Установка прервана (строка $LINENO)"' ERR

# Оформление намеренно без центрирования и рамок: ширина кириллицы
# в printf считается в байтах, а локаль в контейнере может быть не UTF-8 —
# любая «красивая» рамка на таком сочетании гарантированно съезжает.
banner() {
    printf "\n%s%s%s\n" "$C_CYAN" "$(printf '━%.0s' $(seq 1 "$COLS"))" "$C_RESET"
    printf "  %sСИСТЕМА «РАДАР»%s  %sv%s%s\n" "$C_BOLD" "$C_RESET" "$C_DIM" "$VERSION" "$C_RESET"
    printf "  %sмониторинг городских угроз и аварий ЖКХ%s\n" "$C_DIM" "$C_RESET"
    printf "  %sавтор SecretHero · github.com/Chistovik92/radar%s\n" "$C_DIM" "$C_RESET"
    printf "%s%s%s\n" "$C_CYAN" "$(printf '━%.0s' $(seq 1 "$COLS"))" "$C_RESET"
}

banner

# --------------------------------------------------------------------------
#  Шаг 1. Каталог и лог
# --------------------------------------------------------------------------

step "Подготовка каталога и журнала установки"

mkdir -p "$APP_DIR/data"
cd "$APP_DIR"
chmod 700 "$APP_DIR" 2>/dev/null || true

LOG_FILE="$APP_DIR/installer_log.txt"
# Лог накапливается между запусками, но не растёт бесконечно.
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)" -gt 2097152 ]; then
    mv -f "$LOG_FILE" "$LOG_FILE.old"
fi
{
    printf '\n%s\n' "============================================================"
    printf 'Запуск установщика «Радар» v%s\n' "$VERSION"
    printf 'Дата: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
    printf 'Хост: %s · %s\n' "$(hostname 2>/dev/null || echo неизвестно)" "$(uname -srm)"
    printf 'Каталог: %s\n' "$APP_DIR"
    printf 'Аргументы: %s\n' "${ORIGINAL_ARGS:-нет}"
    printf '%s\n' "============================================================"
} >> "$LOG_FILE"

ok "Каталог: $APP_DIR"
ok "Журнал установки: $LOG_FILE"

# --------------------------------------------------------------------------
#  Шаг 2. Проверка окружения
# --------------------------------------------------------------------------

step "Проверка компонентов системы"

check_ok=true

# --- операционная система ---
OS_NAME="$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -s)"
info "Система: $OS_NAME"
info "Архитектура: $(uname -m)"

# --- оперативная память ---
MEM_MB=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)
if [ "$MEM_MB" -gt 0 ]; then
    if [ "$MEM_MB" -lt 900 ]; then
        warn "Оперативной памяти ${MEM_MB} МБ — для бота с PostgreSQL это мало"
        warn "Рекомендуется от 2 ГБ; при нехватке добавьте файл подкачки"
    else
        ok "Оперативная память: ${MEM_MB} МБ"
    fi
fi

# --- свободное место ---
DISK_MB=$(df -Pm "$APP_DIR" 2>/dev/null | awk 'NR==2 {print $4}')
if [ -n "$DISK_MB" ]; then
    if [ "$DISK_MB" -lt 2048 ]; then
        warn "Свободно ${DISK_MB} МБ — образы и база могут не поместиться"
    else
        ok "Свободно на диске: ${DISK_MB} МБ"
    fi
fi

# --- Docker ---
if command -v docker >/dev/null 2>&1; then
    DOCKER_VER="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo неизвестна)"
    if docker info >/dev/null 2>&1; then
        ok "Docker $DOCKER_VER"
    else
        fail "Docker установлен, но демон не отвечает"
        check_ok=false
    fi
else
    fail "Docker не установлен"
    check_ok=false
fi

# --- Docker Compose ---
COMPOSE=""
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
    ok "Docker Compose $(docker compose version --short 2>/dev/null || echo v2)"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
    warn "Найден устаревший docker-compose v1 — рекомендуется перейти на Compose v2"
else
    fail "Docker Compose не найден"
    check_ok=false
fi

# --- вспомогательные утилиты ---
for tool in curl tar gzip; do
    if command -v "$tool" >/dev/null 2>&1; then
        ok "$tool"
    else
        warn "$tool не найден — часть операций может не работать"
    fi
done

# --- время ---
if command -v timedatectl >/dev/null 2>&1; then
    if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes; then
        ok "Время синхронизировано"
    else
        warn "Время не синхронизировано — оповещения по расписанию будут смещаться"
    fi
fi

# --- доступ в интернет ---
if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 12 -o /dev/null https://api.telegram.org 2>/dev/null; then
        ok "Telegram API доступен"
    else
        warn "Telegram API недоступен — проверьте сеть или настройте выход через прокси"
    fi
fi

if [ "$check_ok" != true ]; then
    echo
    printf "  Установите недостающее и повторите запуск:\n"
    printf "    curl -fsSL https://get.docker.com | sh\n"
    die "Не хватает обязательных компонентов"
fi

# --------------------------------------------------------------------------
#  Шаг 3. Обновление системы
# --------------------------------------------------------------------------

step "Обновление компонентов системы"

if [ "$SKIP_UPDATES" = true ]; then
    info "Пропущено по ключу --skip-updates"
elif [ "$(id -u)" != "0" ]; then
    info "Нет прав root — обновление системы пропущено"
elif command -v apt-get >/dev/null 2>&1; then
    info "Проверяю обновления пакетов (может занять пару минут)"
    if run apt-get update; then
        UPGRADABLE=$(apt-get -s upgrade 2>/dev/null | grep -c '^Inst' || echo 0)
        if [ "$UPGRADABLE" -gt 0 ]; then
            info "Доступно обновлений: $UPGRADABLE — устанавливаю"
            if DEBIAN_FRONTEND=noninteractive run apt-get -y -o Dpkg::Options::=--force-confold upgrade; then
                ok "Пакеты системы обновлены"
            else
                warn "Обновление завершилось с ошибкой, продолжаю (подробности в логе)"
            fi
        else
            ok "Все пакеты актуальны"
        fi
    else
        warn "Список пакетов обновить не удалось, продолжаю"
    fi
else
    info "Менеджер пакетов apt не найден — обновление пропущено"
fi

info "Обновляю базовые образы Docker"
run docker pull python:3.11-slim || warn "Не удалось обновить образ python:3.11-slim"
run docker pull postgres:16-alpine || warn "Не удалось обновить образ postgres:16-alpine"
ok "Базовые образы проверены"

# --------------------------------------------------------------------------
#  Шаг 4. Диагностика существующей установки
# --------------------------------------------------------------------------

step "Проверка предыдущей установки"

MODE="новая установка"
HEALTHY=false

if [ -f "$APP_DIR/bot.py" ] && [ ! -d "$APP_DIR/radar" ]; then
    warn "Обнаружена версия 2.x — переношу bot.py в bot.py.bak-2x"
    mv -f "$APP_DIR/bot.py" "$APP_DIR/bot.py.bak-2x"
fi

if [ -f "$APP_DIR/.env" ] || [ -d "$APP_DIR/radar" ]; then
    MODE="обновление"
    info "Найдена предыдущая установка"

    if docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
        STATE="$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo нет)"
        RESTARTS="$(docker inspect -f '{{.RestartCount}}' "$CONTAINER_NAME" 2>/dev/null || echo 0)"
        info "Контейнер бота: $STATE, перезапусков: $RESTARTS"
        if [ "$STATE" = "running" ] && [ "$RESTARTS" -lt 5 ]; then
            HEALTHY=true
            ok "Текущая установка работоспособна"
        else
            warn "Бот нестабилен — будет переустановлен полностью"
            log_raw "--- последние строки лога бота ---"
            docker logs --tail 40 "$CONTAINER_NAME" >> "$LOG_FILE" 2>&1 || true
            FORCE_REINSTALL=true
        fi
    else
        info "Контейнер бота не найден"
    fi

    if [ -f "$APP_DIR/data/db.json" ]; then
        info "Найдена база версии 3.x — данные будут перенесены в PostgreSQL"
    fi
else
    info "Предыдущих установок не найдено"
fi

if [ "$FORCE_REINSTALL" = true ]; then
    MODE="полная переустановка"
    warn "Режим: полная переустановка. Данные в data/ сохраняются"
    NO_CACHE_FLAG="--no-cache"
    info "Останавливаю и удаляю контейнеры"
    (cd "$APP_DIR" && run $COMPOSE down --remove-orphans) || true
    run docker rm -f "$CONTAINER_NAME" || true
    run docker rmi -f "$IMAGE_NAME" || true
    # Каталоги проекта пересоздаются, данные не трогаем
    rm -rf "$APP_DIR/radar" "$APP_DIR/migrations" 2>/dev/null || true
fi

ok "Режим: $MODE"

# --------------------------------------------------------------------------
#  Шаг 5. Файлы проекта
# --------------------------------------------------------------------------

step "Развёртывание файлов проекта"

chown -R 1000:1000 "$APP_DIR/data" 2>/dev/null || chmod -R a+rwX "$APP_DIR/data"

@@FILES@@
ok "Развёрнуто файлов: $(printf '%s' "$FILE_COUNT")"

# --------------------------------------------------------------------------
#  Шаг 6. Настройки
# --------------------------------------------------------------------------

step "Настройка параметров"

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
    info "Файл .env уже существует"
    read -r -p "  Использовать текущие настройки? (Y/n): " reply < /dev/tty || true
    case "${reply:-y}" in
        [Nn]*) RECREATE_ENV=true ;;
        *) ok "Использую существующий .env" ;;
    esac
else
    RECREATE_ENV=true
fi

if [ "$RECREATE_ENV" = true ]; then
    echo
    printf "  %sЗаполните параметры (Ctrl+C — выход)%s\n" "$C_DIM" "$C_RESET"
    ask "  Токен Telegram-бота (@BotFather): " IN_TOKEN '^[0-9]{6,}:[A-Za-z0-9_-]{30,}$' yes
    ask "  Ваш Telegram ID (@userinfobot): " IN_ADMIN '^[0-9]{5,}$' yes
    ask "  Ключ Google Gemini (Enter — без ИИ): " IN_GEMINI '^.{20,}$' no
    # Символ $ недопустим: Docker Compose раскроет его как переменную
    ask "  Пароль базы данных (Enter — сгенерировать): " IN_DBPASS '^[^$]{8,}$' no
    if [ -z "${IN_DBPASS:-}" ]; then
        IN_DBPASS="$(head -c 32 /dev/urandom | base64 | tr -d '/+=$' | head -c 24)"
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
    ok "Файл .env создан (права 600)"
    [ -z "${IN_GEMINI:-}" ] && warn "Ключ Gemini не задан: ассистент отключён, анализ пойдёт по ключевым словам."
fi

TZ_VALUE="$(grep -E '^TZ=' .env | cut -d= -f2- || true)"
: "${TZ_VALUE:=Europe/Saratov}"

# --------------------------------------------------------------------------
#  Шаг 7. Сборка и запуск
# --------------------------------------------------------------------------

step "Сборка образа и запуск контейнеров"

TZ_VALUE="$(grep -E '^TZ=' .env | cut -d= -f2- || true)"
: "${TZ_VALUE:=Europe/Saratov}"
info "Часовой пояс: $TZ_VALUE"

# Пароль с символом $ ломает подстановку переменных в Docker Compose
if grep -qE '^DB_PASSWORD=.*\$' .env 2>/dev/null; then
    die "DB_PASSWORD содержит символ \$ — Compose примет его за переменную. Смените пароль в .env"
fi

info "Останавливаю прежние контейнеры"
run $COMPOSE down --remove-orphans || true
run docker rm -f "$CONTAINER_NAME" || true   # наследие версий 3.x

mkdir -p "$APP_DIR/data/postgres"
chown -R 999:999 "$APP_DIR/data/postgres" 2>/dev/null || true

info "Собираю образ (первый раз это занимает 5–15 минут)"
if ! run $COMPOSE build $NO_CACHE_FLAG; then
    die "Сборка образа не удалась. Подробности: $LOG_FILE"
fi
ok "Образ собран"

info "Запускаю бота и базу данных"
run $COMPOSE up -d || die "Не удалось запустить контейнеры"

# --------------------------------------------------------------------------
#  Шаг 8. Проверка запуска
# --------------------------------------------------------------------------

step "Проверка работоспособности"

info "Жду готовности PostgreSQL"
DB_READY=false
for _ in $(seq 1 45); do
    if docker exec radar_db pg_isready -U radar >/dev/null 2>&1; then
        DB_READY=true
        break
    fi
    sleep 2
done
if [ "$DB_READY" = true ]; then
    ok "База данных отвечает"
else
    warn "База не ответила за 90 секунд — смотрите: docker logs radar_db"
fi

info "Жду запуска бота"
BOT_OK=false
for _ in $(seq 1 45); do
    state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo нет)"
    if [ "$state" = "running" ]; then
        if docker logs "$CONTAINER_NAME" 2>&1 | grep -q "Run polling"; then
            BOT_OK=true
            break
        fi
    fi
    if [ "$state" = "exited" ]; then
        break
    fi
    sleep 2
done

log_raw "--- лог бота после запуска ---"
docker logs --tail 80 "$CONTAINER_NAME" >> "$LOG_FILE" 2>&1 || true

if [ "$BOT_OK" != true ]; then
    fail "Бот не вышел в рабочий режим"
    echo
    printf "  %sПоследние строки лога:%s\n" "$C_DIM" "$C_RESET"
    docker logs --tail 25 "$CONTAINER_NAME" 2>&1 | sed 's/^/    /' || true
    echo
    if [ "$FORCE_REINSTALL" != true ]; then
        printf "  Попробуйте полную переустановку:\n"
        printf "    bash <(curl -fsSL %s) --reinstall\n" \
            "https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh"
    fi
    die "Запуск не удался. Полный лог: $LOG_FILE"
fi

ok "Бот вышел в рабочий режим"

# Что удалось разобрать из лога — полезно видеть сразу
MIGRATED=$(docker logs "$CONTAINER_NAME" 2>&1 | grep -oP 'пользователей \K\d+' | head -1 || true)
[ -n "$MIGRATED" ] && ok "Перенесено пользователей: $MIGRATED"
docker logs "$CONTAINER_NAME" 2>&1 | grep -q "Схема базы актуальна" && ok "Схема базы актуальна"

trap - ERR
ELAPSED=$(( $(date +%s) - START_TS ))
echo
line
printf "  %s✓ Система «Радар» v%s запущена%s   %s(%d мин %d с)%s\n" \
    "$C_GREEN" "$VERSION" "$C_RESET" "$C_DIM" $((ELAPSED / 60)) $((ELAPSED % 60)) "$C_RESET"
line
echo
printf "  %sДальше:%s\n" "$C_BOLD" "$C_RESET"
printf "    Откройте бота в Telegram → /start → пришлите геопозицию\n"
echo
printf "  %sУправление:%s\n" "$C_BOLD" "$C_RESET"
printf "    Логи бота     docker logs -f %s\n" "$CONTAINER_NAME"
printf "    Логи базы     docker logs -f radar_db\n"
printf "    Перезапуск    cd %s && %s restart\n" "$APP_DIR" "$COMPOSE"
printf "    Остановка     cd %s && %s down\n" "$APP_DIR" "$COMPOSE"
printf "    Копия базы    docker exec radar_db pg_dump -U radar radar | gzip > radar-\$(date +%%F).sql.gz\n"
echo
printf "  %sЖурнал установки: %s%s\n" "$C_DIM" "$LOG_FILE" "$C_RESET"
echo
log_raw "=== УСТАНОВКА ЗАВЕРШЕНА УСПЕШНО за ${ELAPSED} с ==="

if [ "$SHOW_LOGS" = true ]; then
    docker logs -f "$CONTAINER_NAME"
fi
