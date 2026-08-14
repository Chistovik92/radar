#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

#
# Система «Радар» v@@VERSION@@ — автономный установщик.
#
#   Надёжный способ — сначала скачать, потом запустить:
#     curl -fsSLo radar-install.sh https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh
#     bash radar-install.sh
#
#   Короткий способ (годится, если связь стабильная):
#     bash <(curl -fsSL https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh)
#
# Флаги:
#   --recreate-env   заново запросить токены и настройки
#   --no-cache       пересобрать образ без кэша Docker
#   --logs           показать логи после запуска
#   --reinstall      принудительная полная переустановка (данные сохраняются)
#   --reset          полный сброс: копия данных, затем установка с нуля
#   --backup         только снять резервную копию и выйти
#   --skip-updates   не обновлять пакеты системы
#   --uninstall      остановить и удалить контейнеры и образ (данные сохраняются)
#
# Файл собирается автоматически: python3 tools/build_installer.py
# Правьте исходники проекта, а не install.sh.

# Всё тело установщика обёрнуто в функцию и вызывается единственной строкой
# в самом конце файла. Это защита от обрыва скачивания: при `bash <(curl ...)`
# скрипт читается потоком, и если связь оборвётся посередине, bash не сможет
# дочитать определение функции — выдаст синтаксическую ошибку и не выполнит
# ни одной команды. Без обёртки он выполнял бы всё до места обрыва:
# именно так установка однажды записала половину файлов проекта.
radar_installer_main() {

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
FULL_RESET=false
BACKUP_ONLY=false
CLI_MODE_SET=false      # способ установки задан ключом, спрашивать не нужно
BACKUP_PATH=""
SKIP_UPDATES=false
LOG_FILE=""
START_TS=$(date +%s)

ORIGINAL_ARGS="$*"

# Справка печатается из кода, а не вычитывается из собственного файла:
# при запуске через `bash <(curl ...)` файл — это поток, и перечитать его нельзя.
show_help() {
    cat <<'RADAR_HELP_EOF'
Система «Радар» — автономный установщик.

Надёжный способ:
  curl -fsSLo radar-install.sh https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh
  bash radar-install.sh

Флаги:
  --recreate-env   заново запросить токены и настройки
  --no-cache       пересобрать образ без кэша Docker
  --logs           показать логи после запуска
  --reinstall      принудительная полная переустановка (данные сохраняются)
  --reset          полный сброс: копия данных, затем установка с нуля
  --backup         только снять резервную копию и выйти
  --skip-updates   не обновлять пакеты системы
  --uninstall      остановить и удалить контейнеры и образ (данные сохраняются)
  --version        показать версию
  --help           эта справка
RADAR_HELP_EOF
}

for arg in "$@"; do
    case "$arg" in
        --recreate-env) RECREATE_ENV=true ;;
        --no-cache)     NO_CACHE_FLAG="--no-cache" ;;
        --logs)         SHOW_LOGS=true ;;
        --reinstall)    FORCE_REINSTALL=true; CLI_MODE_SET=true; NO_CACHE_FLAG="--no-cache" ;;
        --reset)        FULL_RESET=true; FORCE_REINSTALL=true; CLI_MODE_SET=true; NO_CACHE_FLAG="--no-cache" ;;
        --backup)       BACKUP_ONLY=true ;;
        --skip-updates) SKIP_UPDATES=true ;;
        --uninstall)    UNINSTALL=true ;;
        -v|--version)   echo "radar $VERSION"; exit 0 ;;
        -h|--help)      show_help; exit 0 ;;
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
STEP_TOTAL=9

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
    local started ended status
    started=$(date +%s)
    log_raw "CMD   $*"
    if [ -n "$LOG_FILE" ]; then
        "$@" >> "$LOG_FILE" 2>&1
        status=$?
    else
        "$@" >/dev/null 2>&1
        status=$?
    fi
    ended=$(date +%s)
    log_raw "EXIT  код=$status, время=$((ended - started)) с — $1"
    return $status
}

# --- индикатор выполнения -------------------------------------------------
# Docker не сообщает точный прогресс, поэтому полоса показывает долю
# завершённых подзадач — честнее, чем анимация без привязки к делу.
# Символы полосы намеренно ASCII: `tr` работает побайтово и многобайтную
# псевдографику превращает в мусор, а локаль в чужой системе непредсказуема.
repeat() {            # repeat <символ> <сколько>
    [ "$2" -le 0 ] && return 0
    printf "%${2}s" "" | tr ' ' "$1"
    return 0
}

progress() {          # progress <текущий> <всего> <подпись>
    local current="$1" total="$2" label="$3"
    local width=28 filled percent
    [ "$total" -le 0 ] && total=1
    percent=$(( current * 100 / total ))
    [ "$percent" -gt 100 ] && percent=100
    filled=$(( percent * width / 100 ))
    printf "\r  %s[%s%s]%s %3d%%  %-34s" \
        "$C_CYAN" \
        "$(repeat '#' "$filled")" \
        "$(repeat '.' $((width - filled)))" \
        "$C_RESET" "$percent" "$label"
    # Обязательный return 0: конструкция `[ ... ] && ...` при ложном условии
    # вернула бы 1, а под `set -e` это мгновенно роняет установку.
    if [ "$percent" -ge 100 ]; then
        printf "\n"
    fi
    return 0
}

progress_done() { printf "\r%*s\r" "$((COLS - 1))" ""; return 0; }

# --- резервное копирование ------------------------------------------------
make_backup() {       # make_backup <причина>
    local reason="${1:-ручная}"
    local stamp archive dir
    stamp="$(date +%Y%m%d-%H%M%S)"
    dir="$APP_DIR/backups"
    archive="$dir/radar-backup-$stamp.tar.gz"
    mkdir -p "$dir"

    local staging="$dir/.staging-$stamp"
    mkdir -p "$staging"

    info "Собираю резервную копию ($reason)"

    # 1. дамп базы, если она поднята
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^radar_db$'; then
        local db_user db_name
        db_user="$(grep -E '^DB_USER=' .env 2>/dev/null | cut -d= -f2- || echo radar)"
        db_name="$(grep -E '^DB_NAME=' .env 2>/dev/null | cut -d= -f2- || echo radar)"
        : "${db_user:=radar}"; : "${db_name:=radar}"
        progress 1 4 "дамп базы данных"
        if docker exec radar_db pg_dump -U "$db_user" "$db_name" > "$staging/database.sql" 2>>"$LOG_FILE"; then
            log_raw "Дамп базы: $(wc -c < "$staging/database.sql") байт"
        else
            warn "Дамп базы не удался — копия будет без него"
            rm -f "$staging/database.sql"
        fi
    else
        info "Контейнер базы не запущен — дамп пропущен"
    fi

    # 2. конфигурация
    progress 2 4 "настройки"
    [ -f "$APP_DIR/.env" ] && cp "$APP_DIR/.env" "$staging/env.backup"

    # 3. пользовательские данные вне базы
    progress 3 4 "файлы данных"
    if [ -d "$APP_DIR/data" ]; then
        mkdir -p "$staging/data"
        find "$APP_DIR/data" -maxdepth 1 -type f -exec cp {} "$staging/data/" \; 2>/dev/null || true
    fi

    printf 'Система «Радар»\nВерсия: %s\nДата: %s\nПричина: %s\n' \
        "$VERSION" "$(date '+%Y-%m-%d %H:%M:%S')" "$reason" > "$staging/manifest.txt"

    # 4. упаковка
    progress 4 4 "упаковка архива"
    tar -czf "$archive" -C "$staging" . 2>>"$LOG_FILE"
    rm -rf "$staging"

    if [ -f "$archive" ]; then
        ok "Копия сохранена: $archive ($(du -h "$archive" | cut -f1))"
        # Оставляем последние 10 копий
        ls -1t "$dir"/radar-backup-*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm -f || true
        BACKUP_PATH="$archive"
        return 0
    fi
    warn "Резервную копию создать не удалось"
    return 1
}

# --- выбор базы данных ----------------------------------------------------
# Спрашивается при любом способе установки: и при обновлении поверх,
# и при переустановке, и на чистой машине. Прежде выбор молча наследовался
# из старого .env, где строки DB_BACKEND могло не быть вовсе.
set_env_value() {     # set_env_value <ключ> <значение>
    local key="$1" value="$2" file="$APP_DIR/.env"
    touch "$file"
    if grep -qE "^${key}=" "$file"; then
        # Разделитель | — в значениях встречаются слэши (пути, URL)
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
    log_raw "ENV   ${key}=${value}"
}

get_env_value() {     # get_env_value <ключ>
    grep -E "^$1=" "$APP_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- || true
}

choose_database() {
    local current wanted has_sqlite has_pg
    current="$(get_env_value DB_BACKEND)"
    : "${current:=sqlite}"

    has_sqlite=false; has_pg=false
    [ -f "$APP_DIR/data/radar.db" ] && has_sqlite=true
    [ -d "$APP_DIR/data/postgres" ] && [ -n "$(ls -A "$APP_DIR/data/postgres" 2>/dev/null)" ] && has_pg=true

    echo
    printf "  %sКакую базу данных использовать?%s\n\n" "$C_BOLD" "$C_RESET"
    printf "    1) SQLite %s(рекомендуется)%s\n" "$C_GREEN" "$C_RESET"
    printf "       %sфайл data/radar.db рядом с ботом, отдельный контейнер не нужен,%s\n" "$C_DIM" "$C_RESET"
    printf "       %sни пароля, ни ожидания запуска — подходит для 1–2 ГБ ОЗУ%s\n" "$C_DIM" "$C_RESET"
    printf "    2) PostgreSQL\n"
    printf "       %sотдельный контейнер, +300–500 МБ памяти; нужен на машине помощнее%s\n" "$C_DIM" "$C_RESET"

    if [ "$has_sqlite" = true ] || [ "$has_pg" = true ]; then
        echo
        [ "$has_sqlite" = true ] && info "Найдена база SQLite ($(du -h "$APP_DIR/data/radar.db" 2>/dev/null | cut -f1))"
        [ "$has_pg" = true ] && info "Найден том PostgreSQL"
    fi

    local default_choice=1
    [ "$current" = "postgres" ] && default_choice=2

    printf "\n  Сейчас выбрано: %s%s%s\n" "$C_BOLD" "$current" "$C_RESET"
    printf "  Выбор [%d]: " "$default_choice"
    read -r db_choice < /dev/tty || db_choice="$default_choice"
    : "${db_choice:=$default_choice}"

    case "$db_choice" in
        2) wanted="postgres" ;;
        *) wanted="sqlite" ;;
    esac
    log_raw "Выбрана база: $wanted (было $current)"

    # Данные между разными базами сами не переезжают — предупреждаем честно
    if [ "$wanted" != "$current" ]; then
        warn "Смена базы: $current → $wanted"
        if [ -f "$APP_DIR/data/db.json" ]; then
            info "Данные будут перенесены заново из data/db.json"
        elif { [ "$current" = "sqlite" ] && [ "$has_sqlite" = true ]; } ||
             { [ "$current" = "postgres" ] && [ "$has_pg" = true ]; }; then
            warn "Содержимое прежней базы в новую автоматически не переносится"
            info "Старая база остаётся на диске — вернуть выбор можно тем же меню"
            printf "  %sПродолжить смену базы?%s (y/N): " "$C_BOLD" "$C_RESET"
            read -r confirm_db < /dev/tty || confirm_db="n"
            case "${confirm_db:-n}" in
                [Yy]*) : ;;
                *) wanted="$current"; info "Оставляю прежнюю базу: $current" ;;
            esac
        fi
    fi

    set_env_value DB_BACKEND "$wanted"

    if [ "$wanted" = "postgres" ]; then
        local pass
        pass="$(get_env_value DB_PASSWORD)"
        if [ -z "$pass" ] || printf '%s' "$pass" | grep -q '\$'; then
            [ -n "$pass" ] && warn "Прежний пароль содержит символ \$ — Compose его исказит"
            pass="$(head -c 32 /dev/urandom | base64 | tr -d '/+=$' | head -c 24)"
            set_env_value DB_PASSWORD "$pass"
            ok "Сгенерирован пароль базы: $pass"
            info "Запишите его: при пересоздании тома он понадобится"
        fi
        set_env_value DB_HOST postgres
        set_env_value DB_PORT 5432
        set_env_value DB_NAME radar
        set_env_value DB_USER radar
    else
        set_env_value DB_FILE "data/radar.db"
    fi

    ok "База данных: $wanted"
    DB_BACKEND_VALUE="$wanted"
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

# Журнал на каждый запуск свой — так видно историю установок, а не только
# последнюю. Каталог внутри data/, потому что только он смонтирован
# в контейнер: иначе бот не смог бы отдать журнал установки.
LOG_DIR="$APP_DIR/data/logs"
mkdir -p "$LOG_DIR"
RUN_STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/installer_log_${RUN_STAMP}.txt"

# Оставляем последние 10 журналов установки.
# `|| true` обязателен: без существующих файлов ls возвращает ненулевой код,
# а под `set -e` это мгновенно обрывает установку.
ls -1t "$LOG_DIR"/installer_log_*.txt 2>/dev/null | tail -n +11 | xargs -r rm -f || true
{
    printf '\n%s\n' "============================================================"
    printf 'Запуск установщика «Радар» v%s\n' "$VERSION"
    printf 'Дата: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
    printf 'Хост: %s · %s\n' "$(hostname 2>/dev/null || echo неизвестно)" "$(uname -srm)"
    printf 'Каталог: %s\n' "$APP_DIR"
    printf 'Аргументы: %s\n' "${ORIGINAL_ARGS:-нет}"
    printf 'Пользователь: %s (uid %s)\n' "$(id -un 2>/dev/null || echo ?)" "$(id -u)"
    printf 'Оболочка: %s\n' "${BASH_VERSION:-неизвестна}"
    printf 'Локаль: %s\n' "${LANG:-не задана}"
    printf 'Память: %s\n' "$(awk '/MemTotal|MemAvailable/ {printf "%s=%dМБ ", $1, $2/1024}' /proc/meminfo 2>/dev/null || echo неизвестно)"
    printf 'Диск: %s\n' "$(df -Ph "$APP_DIR" 2>/dev/null | awk 'NR==2 {print $4" свободно из "$2}' || echo неизвестно)"
    printf 'Загрузка: %s\n' "$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo неизвестно)"
    printf '%s\n' "============================================================"
} >> "$LOG_FILE"

ok "Каталог: $APP_DIR"
ok "Журнал установки: $LOG_FILE"
info "Журналов прошлых установок: $(ls -1 "$LOG_DIR"/installer_log_*.txt 2>/dev/null | wc -l || echo 0)"

if [ "$BACKUP_ONLY" = true ]; then
    cd "$APP_DIR"
    make_backup "по запросу" || die "Не удалось создать копию"
    printf "\n  Восстановление: распакуйте архив и выполните\n"
    printf "    docker exec -i radar_db psql -U radar radar < database.sql\n\n"
    exit 0
fi

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

# Шкала общая по шагу, плюс отдельная строка на каждый компонент —
# так видно и общий ход, и чем именно установщик занят сейчас.
UPD_TOTAL=4
UPD_DONE=0

upd_step() {          # upd_step <подпись>
    progress "$UPD_DONE" "$UPD_TOTAL" "$1"
    return 0
}

upd_finish() {        # upd_finish <результат>
    UPD_DONE=$((UPD_DONE + 1))
    progress "$UPD_DONE" "$UPD_TOTAL" "$1"
    return 0
}

# --- 1. список пакетов ---
if [ "$SKIP_UPDATES" = true ]; then
    info "Обновление пакетов пропущено (--skip-updates)"
    UPD_DONE=2
elif [ "$(id -u)" != "0" ]; then
    info "Нет прав root — обновление системы пропущено"
    UPD_DONE=2
elif command -v apt-get >/dev/null 2>&1; then
    upd_step "список пакетов"
    if run apt-get update; then
        upd_finish "список пакетов обновлён"
        ok "Список пакетов актуален"
    else
        upd_finish "список пакетов пропущен"
        warn "Список пакетов обновить не удалось, продолжаю"
    fi

    # --- 2. сами пакеты ---
    upd_step "проверка обновлений"
    UPGRADABLE=$(apt-get -s upgrade 2>/dev/null | grep -c '^Inst' || echo 0)
    if [ "$UPGRADABLE" -gt 0 ]; then
        info "Доступно обновлений: $UPGRADABLE"
        upd_step "установка пакетов ($UPGRADABLE)"
        if DEBIAN_FRONTEND=noninteractive run apt-get -y \
                -o Dpkg::Options::=--force-confold upgrade; then
            upd_finish "пакеты обновлены"
            ok "Пакеты системы обновлены: $UPGRADABLE"
        else
            upd_finish "пакеты пропущены"
            warn "Обновление завершилось с ошибкой, продолжаю (подробности в журнале)"
        fi
    else
        upd_finish "обновлений нет"
        ok "Все пакеты актуальны"
    fi
else
    info "Менеджер пакетов apt не найден — обновление пропущено"
    UPD_DONE=2
fi

# --- 3 и 4. базовые образы Docker ---
for image in python:3.11-slim postgres:16-alpine; do
    upd_step "образ $image"
    BEFORE_ID="$(docker image inspect -f '{{.Id}}' "$image" 2>/dev/null || echo нет)"
    if run docker pull "$image"; then
        AFTER_ID="$(docker image inspect -f '{{.Id}}' "$image" 2>/dev/null || echo нет)"
        if [ "$BEFORE_ID" = "$AFTER_ID" ] && [ "$BEFORE_ID" != "нет" ]; then
            upd_finish "$image — актуален"
            ok "$image: уже последней версии"
        else
            upd_finish "$image — обновлён"
            ok "$image: обновлён"
        fi
    else
        upd_finish "$image — пропущен"
        warn "$image: обновить не удалось, использую локальный"
    fi
done

progress "$UPD_TOTAL" "$UPD_TOTAL" "компоненты проверены"

# --------------------------------------------------------------------------
#  Шаг 4. Диагностика существующей установки
# --------------------------------------------------------------------------

step "Проверка предыдущей установки"

MODE="новая установка"
HEALTHY=false
RECOMMENDED=1          # что предложить по умолчанию: 1 поверх, 2 файлы, 3 с нуля
DIAGNOSIS=""

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
            HEALTHY=false
            warn "Бот нестабилен: состояние «$STATE», перезапусков $RESTARTS"
            log_raw "--- последние строки лога бота ---"
            docker logs --tail 60 "$CONTAINER_NAME" >> "$LOG_FILE" 2>&1 || true

            # Разбираем причину, чтобы совет был по существу, а не наугад
            CRASH_LOG="$(docker logs --tail 200 "$CONTAINER_NAME" 2>&1 || true)"
            if printf '%s' "$CRASH_LOG" | grep -qi "MissingGreenlet\|sqlalchemy.exc"; then
                DIAGNOSIS="ошибка работы с базой данных"
                RECOMMENDED=2
            elif printf '%s' "$CRASH_LOG" | grep -qi "password authentication failed\|отклонил подключение"; then
                DIAGNOSIS="база не принимает пароль"
                RECOMMENDED=3
            elif printf '%s' "$CRASH_LOG" | grep -qi "Unauthorized\|token is invalid"; then
                DIAGNOSIS="Telegram отклонил токен бота"
                RECOMMENDED=1
            elif printf '%s' "$CRASH_LOG" | grep -qi "ModuleNotFoundError\|ImportError"; then
                DIAGNOSIS="в образе не хватает зависимостей"
                RECOMMENDED=2
            else
                DIAGNOSIS="причина не распознана"
                RECOMMENDED=2
            fi
            warn "Предполагаемая причина: $DIAGNOSIS"
        fi
    else
        info "Контейнер бота не найден"
        RECOMMENDED=1
    fi

    if [ -f "$APP_DIR/data/db.json" ]; then
        info "Найдены данные версии 3.x — будут перенесены в базу"
    fi
    if [ -f "$APP_DIR/data/radar.db" ]; then
        info "Найдена база SQLite: $(du -h "$APP_DIR/data/radar.db" 2>/dev/null | cut -f1)"
    fi
    if [ -d "$APP_DIR/data/postgres" ]; then
        info "Найден том PostgreSQL от прежней версии"
    fi
else
    info "Предыдущих установок не найдено"
fi

# --- выбор способа установки ---------------------------------------------
# Решение принимает человек. Диагностика лишь подсказывает, что вероятнее
# поможет: раньше автоматика молча выбирала переустановку и меню не показывала.
CHOICE=""
if [ "$CLI_MODE_SET" = true ]; then
    info "Способ задан ключом командной строки"
elif [ "$MODE" = "новая установка" ]; then
    CHOICE=1
else
    echo
    printf "  %sКак поступить с существующей установкой?%s\n\n" "$C_BOLD" "$C_RESET"
    printf "    1) Обновить поверх\n"
    printf "       %sфайлы обновятся, база, настройки и образ сохранятся%s\n" "$C_DIM" "$C_RESET"
    printf "    2) Переустановить\n"
    printf "       %sобраз и файлы проекта заново, база и .env сохраняются%s\n" "$C_DIM" "$C_RESET"
    printf "    3) С чистого листа\n"
    printf "       %sсначала резервная копия, затем удаление базы и настроек%s\n" "$C_DIM" "$C_RESET"
    printf "    4) Только резервная копия и выход\n\n"

    if [ "$HEALTHY" != true ] && [ -n "$DIAGNOSIS" ]; then
        printf "  %sДиагностика: %s → рекомендуется вариант %d%s\n" \
            "$C_YELLOW" "$DIAGNOSIS" "$RECOMMENDED" "$C_RESET"
    fi

    printf "  Выбор [%d]: " "$RECOMMENDED"
    read -r CHOICE < /dev/tty || CHOICE="$RECOMMENDED"
    : "${CHOICE:=$RECOMMENDED}"
    log_raw "Выбран способ установки: $CHOICE (рекомендовался $RECOMMENDED)"

    case "$CHOICE" in
        2) FORCE_REINSTALL=true; NO_CACHE_FLAG="--no-cache" ;;
        3) FULL_RESET=true; FORCE_REINSTALL=true; NO_CACHE_FLAG="--no-cache" ;;
        4)
            make_backup "по запросу" || die "Не удалось создать копию"
            printf "\n  Установка не выполнялась. Копия: %s\n\n" "${BACKUP_PATH:-$APP_DIR/backups}"
            exit 0
            ;;
        *) info "Обновляю поверх существующей установки" ;;
    esac
fi

# --- применение выбранного способа ----------------------------------------
if [ "$FULL_RESET" = true ]; then
    MODE="полный сброс"
    echo
    warn "Будут удалены база данных и настройки бота"
    info "Перед удалением снимается резервная копия"
    printf "  %sПродолжить?%s (введите СБРОС): " "$C_BOLD" "$C_RESET"
    read -r confirm_reset < /dev/tty || confirm_reset=""
    case "$confirm_reset" in
        СБРОС|сброс|RESET|reset) : ;;
        *) die "Сброс отменён" ;;
    esac

    make_backup "перед установкой с чистого листа" || warn "Продолжаю без копии"

    info "Останавливаю контейнеры"
    (cd "$APP_DIR" && run $COMPOSE down --remove-orphans) || true
    run docker rm -f "$CONTAINER_NAME" radar_db || true
    run docker rmi -f "$IMAGE_NAME" || true

    info "Удаляю базу и файлы проекта"
    rm -rf "$APP_DIR/data/postgres" "$APP_DIR/radar" "$APP_DIR/migrations" 2>/dev/null || true
    rm -f "$APP_DIR/data/radar.db" "$APP_DIR/data/radar.db-wal" \
          "$APP_DIR/data/radar.db-shm" "$APP_DIR/data/db.json.migrated" 2>/dev/null || true
    ok "Сброс выполнен, копия сохранена в $APP_DIR/backups"

elif [ "$FORCE_REINSTALL" = true ]; then
    MODE="полная переустановка"
    info "Пересобираю образ и файлы проекта, данные сохраняются"
    (cd "$APP_DIR" && run $COMPOSE down --remove-orphans) || true
    run docker rm -f "$CONTAINER_NAME" || true
    run docker rmi -f "$IMAGE_NAME" || true
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

# Сборщик журналов на стороне хоста. Журналы контейнеров Docker боту
# недоступны: чтобы их читать, ему пришлось бы дать доступ к сокету Docker,
# а это фактически полный доступ к серверу.
cat > "$APP_DIR/collect-logs.sh" <<'RADAR_COLLECT_EOF'
#!/usr/bin/env bash
# Собирает все журналы системы «Радар» в один архив.
#   bash collect-logs.sh            # архив в текущем каталоге
#   bash collect-logs.sh /tmp       # архив в указанном каталоге
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${1:-$APP_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
STAGE="$(mktemp -d)"
ARCHIVE="$OUT_DIR/radar-all-logs-$STAMP.tar.gz"

trap 'rm -rf "$STAGE"' EXIT

echo "Собираю журналы..."

mkdir -p "$STAGE/installer" "$STAGE/bot" "$STAGE/docker"
cp "$APP_DIR"/data/logs/installer_log_*.txt "$STAGE/installer/" 2>/dev/null || true
cp "$APP_DIR"/data/logs/bot.log* "$STAGE/bot/" 2>/dev/null || true

for container in radar_container radar_db; do
    if docker inspect "$container" >/dev/null 2>&1; then
        docker logs --tail 3000 "$container" > "$STAGE/docker/$container.log" 2>&1 || true
        docker inspect "$container" > "$STAGE/docker/$container.inspect.json" 2>/dev/null || true
        echo "  + $container"
    fi
done

{
    echo "Система «Радар»"
    echo "Собрано: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "Хост: $(hostname) · $(uname -srm)"
    echo
    echo "--- контейнеры ---"
    docker ps -a --filter name=radar --format '{{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null || true
    echo
    echo "--- ресурсы ---"
    free -m 2>/dev/null | head -2 || true
    df -h "$APP_DIR" 2>/dev/null | tail -1 || true
    echo
    echo "--- настройки (без секретов) ---"
    grep -vE 'TOKEN|KEY|PASSWORD|SECRET' "$APP_DIR/.env" 2>/dev/null || true
} > "$STAGE/summary.txt"

tar -czf "$ARCHIVE" -C "$STAGE" .
echo "Готово: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
echo "Секреты из .env в архив не попадают."
RADAR_COLLECT_EOF
chmod +x "$APP_DIR/collect-logs.sh"
ok "Сборщик журналов: $APP_DIR/collect-logs.sh"

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
LOG_DIR=data/logs
LOG_KEEP_DAYS=14
LOG_MAX_MB=5
PROMO_ENABLED=1
PROMO_TITLE=🐙 HydraSite
PROMO_URL=https://t.me/+WWJFBZVhxBs4ZmNi
PROMO_IN_ALERTS=0
ENVEOF
    umask 022
    chmod 600 .env
    ok "Файл .env создан (права 600)"
    if [ -z "${IN_GEMINI:-}" ]; then
        warn "Ключ Gemini не задан: ассистент отключён, анализ пойдёт по ключевым словам"
    fi
fi

# Базу выбираем всегда: и при новом .env, и при использовании существующего.
# Раньше выбор молча наследовался из старого файла, где строки DB_BACKEND
# могло не быть вовсе — пользователь о базе даже не знал.
choose_database

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

info "Собираю образ (первый раз это занимает 5–15 минут)"
(
    # Полоса ползёт по времени: точного прогресса Docker не сообщает,
    # поэтому шкала показывает долю от ожидаемых 15 минут.
    elapsed=0
    while [ "$elapsed" -lt 900 ]; do
        progress "$elapsed" 900 "сборка образа"
        sleep 5
        elapsed=$((elapsed + 5))
    done
) &
PROGRESS_PID=$!
if ! run $COMPOSE build $NO_CACHE_FLAG; then
    kill "$PROGRESS_PID" 2>/dev/null || true
    wait "$PROGRESS_PID" 2>/dev/null || true
    progress_done
    die "Сборка образа не удалась. Подробности: $LOG_FILE"
fi
kill "$PROGRESS_PID" 2>/dev/null || true
wait "$PROGRESS_PID" 2>/dev/null || true
progress 900 900 "образ готов"
ok "Образ собран"

# PostgreSQL запоминает пароль при инициализации тома. Если .env изменился,
# а том остался прежним, бот будет молча биться в отказ авторизации.
if [ -d "$APP_DIR/data/postgres" ] && [ -n "$(ls -A "$APP_DIR/data/postgres" 2>/dev/null)" ]; then
    info "Проверяю пароль существующей базы"
    run $COMPOSE up -d postgres || die "Не удалось запустить PostgreSQL"

    for _ in $(seq 1 45); do
        docker exec radar_db pg_isready -U radar >/dev/null 2>&1 && break
        sleep 2
    done

    ENV_DB_PASS="$(grep -E '^DB_PASSWORD=' .env | cut -d= -f2- || true)"
    ENV_DB_USER="$(grep -E '^DB_USER=' .env | cut -d= -f2- || echo radar)"
    ENV_DB_NAME="$(grep -E '^DB_NAME=' .env | cut -d= -f2- || echo radar)"
    : "${ENV_DB_USER:=radar}"
    : "${ENV_DB_NAME:=radar}"

    if docker exec -e PGPASSWORD="$ENV_DB_PASS" radar_db \
        psql -U "$ENV_DB_USER" -d "$ENV_DB_NAME" -c 'SELECT 1' >/dev/null 2>&1; then
        ok "Пароль базы совпадает"
    else
        warn "База не принимает пароль из .env"
        info "PostgreSQL задаёт пароль только при первой инициализации тома,"
        info "поэтому правка .env на уже созданную базу ничего не меняет."

        HAS_DATA=false
        if docker exec radar_db psql -U postgres -d "$ENV_DB_NAME" -tAc \
            "SELECT count(*) FROM users" 2>/dev/null | grep -qE '^[1-9]'; then
            HAS_DATA=true
        fi

        echo
        if [ "$HAS_DATA" = true ]; then
            warn "В базе есть данные пользователей — пересоздание их удалит!"
            printf "  Рекомендуется вернуть прежний пароль в .env, а не пересоздавать базу.\n"
        elif [ -f "$APP_DIR/data/db.json" ]; then
            info "Данные версии 3.x лежат в data/db.json — после пересоздания перенесутся заново"
        else
            info "Пользовательских данных в базе не найдено"
        fi

        printf "  %sПересоздать базу с новым паролем?%s (y/N): " "$C_BOLD" "$C_RESET"
        read -r recreate_db < /dev/tty || recreate_db="n"

        case "${recreate_db:-n}" in
            [Yy]*)
                info "Останавливаю контейнеры и пересоздаю том базы"
                run $COMPOSE down || true
                BACKUP_DIR="$APP_DIR/data/postgres.bak-$(date +%Y%m%d-%H%M%S)"
                mv "$APP_DIR/data/postgres" "$BACKUP_DIR"
                ok "Прежний том сохранён: $BACKUP_DIR"
                mkdir -p "$APP_DIR/data/postgres"
                chown -R 999:999 "$APP_DIR/data/postgres" 2>/dev/null || true
                ;;
            *)
                die "Верните прежний пароль в .env и запустите установщик заново"
                ;;
        esac
    fi
fi

# Профиль postgres поднимается только если выбран PostgreSQL
: "${DB_BACKEND_VALUE:=$(get_env_value DB_BACKEND)}"
: "${DB_BACKEND_VALUE:=sqlite}"
COMPOSE_ARGS=""
if [ "$DB_BACKEND_VALUE" = "postgres" ]; then
    COMPOSE_ARGS="--profile postgres"
    info "База данных: PostgreSQL (отдельный контейнер)"
    mkdir -p "$APP_DIR/data/postgres"
    chown -R 999:999 "$APP_DIR/data/postgres" 2>/dev/null || true
    run $COMPOSE $COMPOSE_ARGS up -d postgres || die "Не удалось запустить PostgreSQL"
    for _ in $(seq 1 45); do
        docker exec radar_db pg_isready -U radar >/dev/null 2>&1 && break
        sleep 2
    done
else
    info "База данных: SQLite (файл data/radar.db, отдельный контейнер не нужен)"
fi

# --------------------------------------------------------------------------
#  Шаг 8. Диагностика до запуска
# --------------------------------------------------------------------------

step "Проверка системы до запуска бота"

info "Запускаю диагностику внутри контейнера"
DOCTOR_OUT="$APP_DIR/.doctor-out.txt"
set +e
$COMPOSE $COMPOSE_ARGS run --rm --no-deps radar python -m radar.doctor \
    > "$DOCTOR_OUT" 2>&1
DOCTOR_CODE=$?
set -e

cat "$DOCTOR_OUT" >> "$LOG_FILE" 2>/dev/null || true

# Показываем результат построчно, сохраняя пометки диагностики
while IFS= read -r dline; do
    case "$dline" in
        *"✓ "*) printf "  %s\n" "$dline" ;;
        *"! "*) printf "  %s%s%s\n" "$C_YELLOW" "$dline" "$C_RESET" ;;
        *"✗ "*) printf "  %s%s%s\n" "$C_RED" "$dline" "$C_RESET" ;;
        *"→ "*) printf "  %s%s%s\n" "$C_DIM" "$dline" "$C_RESET" ;;
        *) [ -n "$dline" ] && printf "  %s\n" "$dline" ;;
    esac
done < "$DOCTOR_OUT"

rm -f "$DOCTOR_OUT"

if [ "$DOCTOR_CODE" -eq 1 ]; then
    echo
    fail "Диагностика нашла ошибки — бот не запущен"
    printf "\n  %sЧто делать:%s\n" "$C_BOLD" "$C_RESET"
    printf "    1. Исправьте то, что указано выше\n"
    printf "    2. Запустите установщик снова\n"
    printf "    3. Если не помогает — установка с чистого листа:\n"
    printf "       bash <(curl -fsSL %s) --reset\n" \
        "https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh"
    printf "\n  Полный отчёт с трассировками: %s\n\n" "$LOG_FILE"
    exit 1
elif [ "$DOCTOR_CODE" -eq 2 ]; then
    warn "Есть предупреждения, но запуск возможен"
else
    ok "Диагностика пройдена без замечаний"
fi

# --------------------------------------------------------------------------
#  Шаг 9. Запуск
# --------------------------------------------------------------------------

step "Запуск бота"

run $COMPOSE $COMPOSE_ARGS up -d || die "Не удалось запустить контейнеры"

# Первый запуск включает миграции Alembic, перенос данных и геокодирование —
# на слабом железе это занимает минуты, а не секунды.
info "Жду запуска бота (первый запуск — до 10 минут)"

BOT_OK=false
BOT_DEAD=false
LAST_STAGE=""
WAIT_LIMIT=300      # циклов по 2 секунды

for tick in $(seq 1 "$WAIT_LIMIT"); do
    state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo нет)"
    snapshot="$(docker logs "$CONTAINER_NAME" 2>&1 || true)"

    # Показываем этапы по мере прохождения, чтобы ожидание не было немым
    for stage in "База загружена:загрузка данных" \
                 "Схема базы актуальна:схема базы готова" \
                 "Перенос завершён:данные перенесены" \
                 "Адреса дозаполнены:адреса уточнены" \
                 "Run polling:подключение к Telegram"; do
        marker="${stage%%:*}"
        title="${stage#*:}"
        if printf '%s' "$snapshot" | grep -q "$marker"; then
            if [ "$LAST_STAGE" != "$title" ]; then
                LAST_STAGE="$title"
                info "· $title"
            fi
        fi
    done

    if printf '%s' "$snapshot" | grep -q "Run polling"; then
        BOT_OK=true
        break
    fi

    if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
        BOT_DEAD=true
        break
    fi

    # Фатальные причины: ждать дальше бессмысленно
    if printf '%s' "$snapshot" | grep -qi "отклонил подключение\|Unauthorized\|Ошибка конфигурации"; then
        BOT_DEAD=true
        break
    fi

    # Полоса показывает пройденные этапы, а не абстрактное время
    STAGES_DONE=0
    for marker in "База загружена" "Схема базы" "Перенос завершён" "Run polling"; do
        printf '%s' "$snapshot" | grep -q "$marker" && STAGES_DONE=$((STAGES_DONE + 1))
    done
    progress "$STAGES_DONE" 4 "${LAST_STAGE:-запуск}"

    sleep 2
done
progress_done

log_raw "--- лог бота после запуска ---"
docker logs --tail 120 "$CONTAINER_NAME" >> "$LOG_FILE" 2>&1 || true

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
printf "    Все журналы   bash %s/collect-logs.sh\n" "$APP_DIR"
printf "    Журналы в боте  /logs · /logtail · /logclear %s(суперадминистратор)%s\n" "$C_DIM" "$C_RESET"
echo
printf "  %sЖурнал установки: %s%s\n" "$C_DIM" "$LOG_FILE" "$C_RESET"
echo
log_raw "=== УСТАНОВКА ЗАВЕРШЕНА УСПЕШНО за ${ELAPSED} с ==="

if [ "$SHOW_LOGS" = true ]; then
    docker logs -f "$CONTAINER_NAME"
fi

}   # конец radar_installer_main

# Единственная исполняемая строка файла. Если скачивание оборвалось,
# до неё дело не дойдёт — bash упадёт на разборе незакрытой функции.
radar_installer_main "$@"
