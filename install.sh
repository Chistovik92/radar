#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

#
# Система «Радар» v4.1.0 — автономный установщик.
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
#   --rollback       вернуть предыдущую версию из последнего снимка
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

VERSION="4.1.0"
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
ROLLBACK_ONLY=false
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
  --rollback       вернуть предыдущую версию из последнего снимка
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
        --rollback)     ROLLBACK_ONLY=true ;;
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

# Общая шкала по всей установке: сколько шагов позади.
overall() {
    local width=28 filled percent
    percent=$(( STEP_CURRENT * 100 / STEP_TOTAL ))
    [ "$percent" -gt 100 ] && percent=100
    filled=$(( percent * width / 100 ))
    printf "  %sвсего%s [%s%s] %3d%%\n" "$C_DIM" "$C_RESET" \
        "$(repeat '=' "$filled")" "$(repeat ' ' $((width - filled)))" "$percent"
    return 0
}

step()  {
    STEP_CURRENT=$((STEP_CURRENT + 1))
    printf "\n%s[%d/%d]%s %s%s%s\n" "$C_BLUE" "$STEP_CURRENT" "$STEP_TOTAL" \
        "$C_RESET" "$C_BOLD" "$*" "$C_RESET"
    overall
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
    # Код возврата снимается через `|| status=$?`, а не отдельной строкой:
    # обработчик ERR срабатывает при ненулевом коде даже когда errexit выключен,
    # и обрывал бы установку до того, как вызывающий проверит результат.
    local started ended status=0
    started=$(date +%s)
    log_raw "CMD   $*"
    if [ -n "$LOG_FILE" ]; then
        "$@" >> "$LOG_FILE" 2>&1 || status=$?
    else
        "$@" >/dev/null 2>&1 || status=$?
    fi
    ended=$(date +%s)
    log_raw "EXIT  код=$status, время=$((ended - started)) с — $1"
    return $status
}

# --- индикатор выполнения -------------------------------------------------
# (определения repeat/progress ниже используются в step, поэтому объявлены
#  до первого вызова — bash разбирает функции при загрузке файла)
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

# --- снимок перед обновлением и откат -------------------------------------
# Файлы проекта перезаписываются на месте, поэтому перед развёртыванием
# сохраняем текущую установку целиком. Если новая версия не поднимется,
# откат возвращает ровно то, что работало до обновления.
FALLBACK_VERSION="3.3.5"     # последняя версия с файловым хранилищем
ROLLBACK_SNAPSHOT=""
PREVIOUS_VERSION=""

installed_version() {
    local init="$APP_DIR/radar/__init__.py"
    [ -f "$init" ] || return 0
    grep -oE '__version__ = "[^"]+"' "$init" 2>/dev/null | head -1 | cut -d'"' -f2 || true
}

make_snapshot() {
    [ -d "$APP_DIR/radar" ] || return 0

    PREVIOUS_VERSION="$(installed_version)"
    : "${PREVIOUS_VERSION:=неизвестна}"

    local dir="$APP_DIR/backups"
    local stamp archive
    mkdir -p "$dir"
    stamp="$(date +%Y%m%d-%H%M%S)"
    archive="$dir/rollback-${PREVIOUS_VERSION}-${stamp}.tar.gz"

    info "Сохраняю снимок текущей установки (v$PREVIOUS_VERSION)"
    local items=""
    for entry in radar migrations main.py requirements.txt Dockerfile \
                 docker-compose.yml alembic.ini .env; do
        [ -e "$APP_DIR/$entry" ] && items="$items $entry"
    done
    [ -z "$items" ] && return 0

    if tar -czf "$archive" -C "$APP_DIR" $items 2>>"$LOG_FILE"; then
        ROLLBACK_SNAPSHOT="$archive"
        printf '%s\n' "$PREVIOUS_VERSION" > "$dir/.last-version"
        ok "Снимок: $(basename "$archive") ($(du -h "$archive" | cut -f1))"
        # Оставляем последние 5 снимков
        ls -1t "$dir"/rollback-*.tar.gz 2>/dev/null | tail -n +6 | xargs -r rm -f || true
    else
        warn "Снимок создать не удалось — откат будет недоступен"
    fi
    return 0
}

latest_snapshot() {
    ls -1t "$APP_DIR/backups"/rollback-*.tar.gz 2>/dev/null | head -1 || true
}

do_rollback() {       # do_rollback [путь к снимку]
    local archive="${1:-$(latest_snapshot)}"
    if [ -z "$archive" ] || [ ! -f "$archive" ]; then
        fail "Снимок предыдущей установки не найден"
        printf "    Каталог снимков: %s/backups\n" "$APP_DIR"
        return 1
    fi

    info "Откатываюсь на снимок: $(basename "$archive")"
    (cd "$APP_DIR" && run $COMPOSE down --remove-orphans) || true
    run docker rm -f "$CONTAINER_NAME" || true

    rm -rf "$APP_DIR/radar" "$APP_DIR/migrations" 2>/dev/null || true
    if ! tar -xzf "$archive" -C "$APP_DIR" 2>>"$LOG_FILE"; then
        fail "Распаковать снимок не удалось"
        return 1
    fi
    ok "Файлы восстановлены"

    info "Пересобираю образ прежней версии"
    if ! (cd "$APP_DIR" && run $COMPOSE build); then
        fail "Сборка прежней версии не удалась"
        return 1
    fi
    if ! (cd "$APP_DIR" && run $COMPOSE up -d); then
        fail "Запуск прежней версии не удался"
        return 1
    fi

    ok "Откат выполнен, восстановлена версия $(installed_version)"
    return 0
}

offer_rollback() {    # offer_rollback <причина>
    local reason="$1" archive
    archive="$(latest_snapshot)"

    echo
    printf "  %sЧто можно сделать:%s\n\n" "$C_BOLD" "$C_RESET"

    if [ -n "$archive" ]; then
        printf "    1) Откатиться на предыдущую версию %s(%s)%s\n" \
            "$C_DIM" "${PREVIOUS_VERSION:-из снимка}" "$C_RESET"
        printf "       %sфайлы вернутся из снимка, база не трогается%s\n" "$C_DIM" "$C_RESET"
    else
        printf "    1) %s(снимка нет — откат недоступен)%s\n" "$C_DIM" "$C_RESET"
    fi
    printf "    2) Поставить проверенную версию %s%s\n" "$FALLBACK_VERSION" ""
    printf "       %sпоследняя версия на файловом хранилище, без базы данных%s\n" "$C_DIM" "$C_RESET"
    printf "    3) Ничего не делать — разберусь сам\n\n"
    printf "  Выбор [3]: "

    local answer=""
    read -r answer < /dev/tty || answer="3"
    : "${answer:=3}"
    log_raw "Действие после сбоя ($reason): $answer"

    case "$answer" in
        1)
            if [ -z "$archive" ]; then
                warn "Снимка нет, откат невозможен"
                return 1
            fi
            do_rollback "$archive" && return 0
            return 1
            ;;
        2)
            echo
            info "Ищу установщик версии $FALLBACK_VERSION"

            # Источники по убыванию надёжности: локальный архив, тег, ветка.
            local local_archive="$APP_DIR/fallback/radar-${FALLBACK_VERSION}.tar.gz"
            if [ -f "$local_archive" ]; then
                info "Найден локальный архив: $local_archive"
                if tar -xzf "$local_archive" -C "$APP_DIR" 2>>"$LOG_FILE"; then
                    ok "Версия $FALLBACK_VERSION распакована"
                    (cd "$APP_DIR" && run $COMPOSE down) || true
                    if (cd "$APP_DIR" && run $COMPOSE build) &&
                       (cd "$APP_DIR" && run $COMPOSE up -d); then
                        ok "Версия $FALLBACK_VERSION запущена"
                        return 0
                    fi
                    fail "Запустить $FALLBACK_VERSION не удалось"
                    return 1
                fi
                warn "Архив повреждён"
            fi

            local url="https://raw.githubusercontent.com/Chistovik92/radar/v${FALLBACK_VERSION}/install.sh"
            printf "  Пробую %s\n" "$url"
            if curl -fsSLo "$APP_DIR/install-${FALLBACK_VERSION}.sh" "$url" 2>>"$LOG_FILE"; then
                ok "Установщик $FALLBACK_VERSION скачан"
                printf "\n  Запустите его:\n    bash %s/install-%s.sh\n\n" \
                    "$APP_DIR" "$FALLBACK_VERSION"
                return 1
            fi

            rm -f "$APP_DIR/install-${FALLBACK_VERSION}.sh"
            warn "Тег v$FALLBACK_VERSION в репозитории не найден (ответ 404)"
            echo
            printf "  %sЧтобы этот вариант заработал, поставьте тег на нужный коммит:%s\n" \
                "$C_BOLD" "$C_RESET"
            printf "    git log --oneline | grep -i 3.3.5      %s# найти коммит%s\n" "$C_DIM" "$C_RESET"
            printf "    git tag v%s <хеш коммита>\n" "$FALLBACK_VERSION"
            printf "    git push origin v%s\n" "$FALLBACK_VERSION"
            echo
            printf "  %sЛибо положите архив вручную:%s\n" "$C_BOLD" "$C_RESET"
            printf "    %s/fallback/radar-%s.tar.gz\n\n" "$APP_DIR" "$FALLBACK_VERSION"
            return 1
            ;;
        *)
            printf "\n  Полный журнал: %s\n" "$LOG_FILE"
            printf "  Откат позже:   bash %s/install.sh --rollback\n\n" "$APP_DIR"
            return 1
            ;;
    esac
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

if [ "$ROLLBACK_ONLY" = true ]; then
    cd "$APP_DIR"
    COMPOSE="docker compose"
    docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"
    step "Откат на предыдущую версию"
    if do_rollback; then
        echo
        printf "  Готово. Логи: docker logs -f %s\n\n" "$CONTAINER_NAME"
        exit 0
    fi
    die "Откат не удался. Журнал: $LOG_FILE"
fi

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

# Снимок делается до перезаписи: после неё вернуть прежнюю версию уже нечем
make_snapshot

chown -R 1000:1000 "$APP_DIR/data" 2>/dev/null || chmod -R a+rwX "$APP_DIR/data"

mkdir -p "migrations" "migrations/versions" "radar" "radar/db" "radar/handlers" "radar/platforms"
FILE_COUNT=50
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "requirements.txt"
cat > "requirements.txt" <<'RADAR_FILE_00'
aiogram>=3.13,<4
aiohttp>=3.9,<4
beautifulsoup4>=4.12
google-genai>=1.0
aiofiles>=23.2
python-dotenv>=1.0

# База данных: SQLite по умолчанию, PostgreSQL по желанию
SQLAlchemy[asyncio]>=2.0,<3
aiosqlite>=0.20
asyncpg>=0.29
alembic>=1.13
RADAR_FILE_00
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "Dockerfile"
cat > "Dockerfile" <<'RADAR_FILE_01'
FROM python:3.11-slim

ARG TZ=Europe/Saratov
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=${TZ}

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py alembic.ini ./
# Диагностика лежит внутри пакета: tools/ исключён из контекста сборки
COPY radar ./radar
COPY migrations ./migrations

RUN useradd -m -u 1000 radar && mkdir -p /app/data && chown -R radar:radar /app
USER radar

CMD ["python", "-u", "main.py"]
RADAR_FILE_01
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "docker-compose.yml"
cat > "docker-compose.yml" <<'RADAR_FILE_02'
# Сборка рассчитана на одноплатник с 1–2 ГБ памяти.
# По умолчанию база — SQLite: файл рядом с ботом, отдельный контейнер не нужен.
# PostgreSQL включается профилем, когда бот переезжает на машину помощнее:
#   DB_BACKEND=postgres docker compose --profile postgres up -d

services:
  radar:
    build:
      context: .
      args:
        TZ: ${TZ:-Europe/Saratov}
    image: radar_image
    container_name: radar_container
    restart: on-failure:5
    env_file: .env
    volumes:
      - ./data:/app/data
    deploy:
      resources:
        limits:
          memory: ${RADAR_MEM_LIMIT:-512M}
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  postgres:
    profiles: ["postgres"]
    image: postgres:16-alpine
    container_name: radar_db
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DB_NAME:-radar}
      POSTGRES_USER: ${DB_USER:-radar}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-radar}
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"
    # Значения подобраны под 1–2 ГБ ОЗУ. На машине с 4 ГB и больше
    # можно поднять shared_buffers до 256MB, а effective_cache_size до 1GB.
    command: >
      postgres
      -c shared_buffers=96MB
      -c effective_cache_size=256MB
      -c work_mem=4MB
      -c maintenance_work_mem=32MB
      -c max_connections=20
      -c max_parallel_workers=0
      -c max_parallel_workers_per_gather=0
      -c max_worker_processes=2
      -c wal_compression=on
      -c synchronous_commit=off
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    shm_size: 64mb
    deploy:
      resources:
        limits:
          memory: 512M
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-radar} -d ${DB_NAME:-radar}"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
RADAR_FILE_02
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "alembic.ini"
cat > "alembic.ini" <<'RADAR_FILE_03'
[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
RADAR_FILE_03
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" ".dockerignore"
cat > ".dockerignore" <<'RADAR_FILE_04'
.git
.github
.env
data
tests
tools
README.md
install.sh
LICENSE
__pycache__
*.pyc

# стенд сравнения провайдеров не нужен в образе
bench
RADAR_FILE_04
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "main.py"
cat > "main.py" <<'RADAR_FILE_05'
#!/usr/bin/env python3
"""Точка входа системы «Радар»."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os

from radar import config

# Логи и проверка конфигурации выполняются до импорта aiogram-слоя:
# без валидного BOT_TOKEN экземпляр Bot создать нельзя.
log = config.setup_logging()
config.validate()

from radar import ai, features, handlers, logs as logstore, monitor, roles, storage  # noqa: E402
from radar.db import engine as db_engine  # noqa: E402
from radar.db import importer, repo  # noqa: E402
from radar.middlewares import AccessMiddleware  # noqa: E402
from radar.tg import bot, dp, send_html  # noqa: E402

# История изменений: список версий, а не склеенный текст. Раньше блоки
# «Из прошлых версий» дописывались друг к другу и дублировались, а название
# базы было вписано жёстко — при переходе на SQLite оно стало враньём.
RELEASES: list[tuple[str, list[str]]] = [
    ("4.1.0", [
        "🆘 <b>Кнопка SOS</b> — отправка геопозиции экстренному контакту.",
        "🌤 <b>Погода для пользователей от администрации</b> — режим и частоту "
        "можно задать за пользователя.",
        "🟠 <b>Одноклассники как источник</b> — через официальный API.",
        "🛡 Больше проверок отказоустойчивости.",
    ]),
    ("4.0.8", [
        "🩺 <b>Диагностика перед запуском</b>: установщик проверяет систему "
        "и не стартует бота при ошибке.",
        "↩️ <b>Откат на предыдущую версию</b> из снимка, если обновление не удалось.",
        "📋 <b>Журналы в боте</b>: /logs, /logtail, /logclear у суперадминистратора.",
        "🔍 <b>Проверка источников</b> — кнопка в панели модератора и /checksources.",
    ]),
    ("4.0", [
        "🗄 <b>Настоящая база данных</b> вместо файла. Данные перенесены автоматически.",
        "🕘 <b>История событий</b> — видно, что приходило по каждому адресу.",
        "⚙️ <b>Управление возможностями</b> в боте: /features у суперадминистратора, "
        "без обновления версии.",
        "🔌 <b>Готовность к мессенджеру MAX</b> — единое ядро для двух платформ.",
        "🐙 Партнёрский проект переименован в <b>HydraSite</b>, команда /partner.",
    ]),
    ("3.3", [
        "✅ <b>Отбой опасности</b> приходит отдельным сообщением с другим сигналом.",
        "📍 <b>Администрация добавляет локации</b> пользователям — адресом или геопозицией.",
        "🔗 Новости из лент СМИ снабжаются ссылкой на источник.",
        "🌍 Новые города: Москва, Санкт-Петербург, Казань, Самара.",
        "📦 Источники выгружаются и загружаются файлом.",
        "📵 <b>Белые списки</b> — предупреждение выдаётся автоматически "
        "вместе с оповещением о БПЛА.",
    ]),
    ("3.0", [
        "🛸 <b>Военные угрозы</b> определяются на весь город и приходят одним "
        "сообщением со списком совпавших локаций.",
        "🛠 <b>ЖКХ</b> ищется адресно — по улице и дому, отдельным сообщением.",
        "📍 Локаций сколько угодно; ближе 1 км — объединяются в одну сводку.",
        "🌤 Погода — по каждой группе локаций отдельно.",
        "🧠 ИИ-ассистент в диалоге — начиная с роли «Модератор».",
        "👥 Роли: суперадминистратор → администратор → модератор → пользователь.",
    ]),
]


def build_changelog(limit: int = 2) -> str:
    """Собирает сообщение об обновлении.

    Показываются последние `limit` выпусков: полный список за всю историю
    в одном сообщении не читается и упирается в ограничение Telegram.
    """
    backend = "PostgreSQL" if not config.is_sqlite() else "SQLite"
    parts = [
        f"🚀 <b>Система «Радар» v{config.VERSION}</b>",
        f"<i>База данных: {backend}</i>",
        "",
    ]
    for index, (version, items) in enumerate(RELEASES[:limit]):
        if index:
            parts.append("")
            parts.append(f"<b>Ранее, в версии {version}:</b>")
        parts.extend(items)

    if len(RELEASES) > limit:
        parts.append("")
        parts.append("<i>Полная история изменений — в репозитории проекта.</i>")
    return "\n".join(parts)


async def announce() -> None:
    """Рассылает changelog один раз на версию, а не при каждом рестарте."""
    marker = await storage.meta_get("announced_version") or {}
    if marker.get("value") == config.VERSION:
        return
    await storage.meta_set("announced_version", {"value": config.VERSION})
    for uid, user in list(storage.users().items()):
        if roles.is_moderator(user.get("role")):
            await send_html(uid, build_changelog())
            await asyncio.sleep(0.2)


async def setup_commands() -> None:
    """Список команд в синей кнопке меню Telegram."""
    from aiogram.types import BotCommand

    commands = [
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="partner", description="Партнёрский проект"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="id", description="Мой ID и роль"),
        BotCommand(command="cancel", description="Отменить ввод"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception:  # noqa: BLE001
        log.warning("Не удалось установить меню команд", exc_info=True)


async def prepare_database() -> None:
    """Готовит базу: ждёт готовности, создаёт схему, переносит старые данные."""
    await db_engine.wait_ready()

    log.info("Проверяю схему базы")
    created, tables, repaired = await db_engine.ensure_schema()
    await db_engine.stamp_alembic()
    if repaired:
        log.warning("Схема была несовместима и пересоздана (%d таблиц)", tables)
    elif created:
        log.info("Схема базы создана (%d таблиц)", tables)
    else:
        log.info("Схема базы актуальна (%d таблиц)", tables)
    if await importer.is_empty():
        log.info("База пуста — переношу данные прежней версии")
        counters = await importer.run()
        log.info(
            "Перенос завершён: пользователей %d, локаций %d",
            counters.get("users", 0), counters.get("locations", 0),
        )
    await storage.load()
    features.apply(await repo.load_features())
    active = sum(1 for flag in features.FLAGS if features.enabled(flag.key))
    log.info("Возможностей включено: %d из %d", active, len(features.FLAGS))
    logstore.ensure_directory()
    stale_logs = logstore.purge_old()
    if stale_logs:
        log.info("Удалено устаревших журналов: %d", stale_logs)

    removed = await repo.purge_old_events()
    if removed:
        log.info("Удалено устаревших событий: %d", removed)


async def main() -> None:
    await prepare_database()

    dp.message.outer_middleware(AccessMiddleware())
    dp.callback_query.outer_middleware(AccessMiddleware())
    handlers.setup(dp)

    log.info(
        "Запуск «Радар» v%s | ИИ: %s | TZ: %s | опрос каждые %d с",
        config.VERSION,
        config.GEMINI_MODEL if config.AI_ENABLED else "выключен (эвристика)",
        os.getenv("TZ", "system"),
        config.POLL_INTERVAL,
    )

    if ai.ENABLED:
        await ai.discover_models()
        log.info(
            "Модели: ассистент «%s», анализ «%s»",
            ai.current_model(ai.ASSISTANT), ai.current_model(ai.ANALYSIS),
        )

    await setup_commands()

    background = asyncio.create_task(monitor.run(), name="monitor")
    asyncio.create_task(announce(), name="announce")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        background.cancel()
        try:
            await background
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await db_engine.dispose()
        log.info("Остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except db_engine.AuthenticationError:
        # Причина уже подробно объяснена в логе — трассировка тут лишний шум.
        raise SystemExit(1)
    except Exception:  # noqa: BLE001
        # Без этого контейнер уходит в бесконечный цикл рестартов, а причина
        # теряется среди одинаковых трейсбеков.
        log.critical("Критический сбой при запуске", exc_info=True)
        log.critical(
            "Проверьте .env (DB_PASSWORD без символа $), доступность базы "
            "и логи radar_db: docker logs --tail 40 radar_db"
        )
        raise SystemExit(1)
RADAR_FILE_05
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/__init__.py"
cat > "radar/__init__.py" <<'RADAR_FILE_06'
"""Система «Радар» — мониторинг городских угроз и ЖКХ-аварий по локациям пользователя.

Автор: SecretHero · https://github.com/Chistovik92/radar
Лицензия: GPL-3.0
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

__version__ = "4.1.0"
__author__ = "SecretHero"
__license__ = "GPL-3.0"
__url__ = "https://github.com/Chistovik92/radar"

SIGNATURE = f"Система «Радар» v{__version__} · автор {__author__} · {__url__}"

__all__ = ["__version__", "__author__", "__license__", "__url__", "SIGNATURE"]
RADAR_FILE_06
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/config.py"
cat > "radar/config.py" <<'RADAR_FILE_07'
"""Конфигурация приложения: читается из переменных окружения (.env)."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from . import __version__

load_dotenv()

def _int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _list(name: str) -> list[str]:
    raw = (os.getenv(name) or "").replace(";", ",")
    return [item.strip().lstrip("@") for item in raw.split(",") if item.strip()]


VERSION: str = __version__

BOT_TOKEN: str = (os.getenv("BOT_TOKEN") or "").strip()
SUPERADMIN_ID: int = _int("SUPERADMIN_ID", 0)

GEMINI_API_KEY: str = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL: str = (os.getenv("GEMINI_MODEL") or "gemini-3.6-flash").strip()
# Разбор новостей — задача классификации: дешёвая модель с большей квотой.
GEMINI_MODEL_ANALYSIS: str = (
    os.getenv("GEMINI_MODEL_ANALYSIS") or "gemini-3.5-flash-lite"
).strip()
AI_CONCURRENCY: int = max(1, _int("AI_CONCURRENCY", 2))
AI_TIMEOUT: int = max(20, _int("AI_TIMEOUT", 90))

# Квоты бесплатного тарифа Gemini. Уточняйте актуальные значения в AI Studio.
AI_RPM: int = max(1, _int("AI_RPM", 10))
AI_RPD: int = max(1, _int("AI_RPD", 250))
# Сколько суточных запросов держать в резерве только под ИИ-ассистента.
AI_RESERVE: int = max(0, _int("AI_RESERVE", 40))
# Сколько новостей отправлять в модель одним запросом.
AI_BATCH_SIZE: int = max(1, _int("AI_BATCH_SIZE", 8))
# Пауза фонового анализа после ответа 429, секунды.
AI_COOLDOWN: int = max(60, _int("AI_COOLDOWN", 900))
# Прогонять сообщения через фильтр по ключевым словам до обращения к модели.
AI_PREFILTER: bool = (os.getenv("AI_PREFILTER") or "1").strip().lower() not in ("0", "false", "no")
# Поиск в интернете для ассистента (grounding).
AI_SEARCH: bool = (os.getenv("AI_SEARCH") or "1").strip().lower() not in ("0", "false", "no")

DATA_FILE: str = (os.getenv("DATA_FILE") or "data/db.json").strip()

# --- база данных ---
# sqlite — по умолчанию: файл рядом с ботом, без отдельного контейнера,
# без пароля и без ожидания готовности. Проверено как единственный вариант,
# уверенно работающий на одноплатнике с 1–2 ГБ памяти.
# postgres — когда бот переезжает на машину помощнее.
DB_BACKEND: str = (os.getenv("DB_BACKEND") or "sqlite").strip().lower()
DB_FILE: str = (os.getenv("DB_FILE") or "data/radar.db").strip()

DB_HOST: str = (os.getenv("DB_HOST") or "postgres").strip()
DB_PORT: int = _int("DB_PORT", 5432)
DB_NAME: str = (os.getenv("DB_NAME") or "radar").strip()
DB_USER: str = (os.getenv("DB_USER") or "radar").strip()
DB_PASSWORD: str = (os.getenv("DB_PASSWORD") or "").strip()
DATABASE_URL: str = (os.getenv("DATABASE_URL") or "").strip()
DB_POOL_SIZE: int = max(1, _int("DB_POOL_SIZE", 5))
DB_MAX_OVERFLOW: int = max(0, _int("DB_MAX_OVERFLOW", 5))
DB_ECHO: bool = (os.getenv("DB_ECHO") or "0").strip().lower() in ("1", "true", "yes")
# Сколько дней хранить историю событий; 0 — бессрочно.
EVENT_RETENTION_DAYS: int = max(0, _int("EVENT_RETENTION_DAYS", 180))


def is_sqlite() -> bool:
    return DB_BACKEND == "sqlite" and not DATABASE_URL


def database_url(async_driver: bool = True) -> str:
    """Строка подключения. DATABASE_URL имеет приоритет над отдельными полями."""
    from urllib.parse import quote_plus

    if is_sqlite():
        path = os.path.abspath(DB_FILE)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return f"sqlite+aiosqlite:///{path}" if async_driver else f"sqlite:///{path}"

    driver = "postgresql+asyncpg" if async_driver else "postgresql+psycopg2"
    if DATABASE_URL:
        url = DATABASE_URL
        # Приводим к нужному драйверу, чтобы одна переменная годилась и Alembic.
        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return driver + "://" + url[len(prefix):]
        return url
    password = f":{quote_plus(DB_PASSWORD)}" if DB_PASSWORD else ""
    return f"{driver}://{DB_USER}{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
POLL_INTERVAL: int = max(60, _int("POLL_INTERVAL", 180))
MSG_PER_SOURCE: int = max(1, _int("MSG_PER_SOURCE", 5))
CLUSTER_RADIUS_M: int = max(0, _int("CLUSTER_RADIUS_M", 1000))
MAX_LOCATIONS: int = _int("MAX_LOCATIONS", 0)  # 0 — без ограничения
DEFAULT_CITY: str = (os.getenv("DEFAULT_CITY") or "").strip()
EXTRA_CHANNELS: list[str] = _list("EXTRA_CHANNELS")
EXTRA_RSS: list[str] = [u for u in (os.getenv("EXTRA_RSS") or "").split(",") if u.strip()]

# --- партнёрский блок (кнопка в меню) ---
PROMO_ENABLED: bool = (os.getenv("PROMO_ENABLED") or "1").strip().lower() not in ("0", "false", "no")
PROMO_TITLE: str = (os.getenv("PROMO_TITLE") or "🐙 HydraSite").strip()
PROMO_URL: str = (os.getenv("PROMO_URL") or "https://t.me/+WWJFBZVhxBs4ZmNi").strip()
PROMO_TEXT: str = (
    os.getenv("PROMO_TEXT")
    or "🐙 <b>HydraSite</b> — второй проект команды «Радар».\n\n"
       "Подробности и доступ — в канале проекта."
).strip()
# Показывать промо внутри оповещений об угрозах (по умолчанию выключено)
PROMO_IN_ALERTS: bool = (os.getenv("PROMO_IN_ALERTS") or "0").strip().lower() in ("1", "true", "yes")

# --- выход в интернет через внешний узел (версия 4.1) ---
# Локальный SOCKS5, который поднимает соседний контейнер sing-box.
EGRESS_PROXY: str = (os.getenv("EGRESS_PROXY") or "").strip()
# Ключ шифрования подписок и ключей серверов в базе.
SECRET_KEY: str = (os.getenv("SECRET_KEY") or "").strip()

# --- мессенджер MAX (включается в 4.2) ---
MAX_BOT_TOKEN: str = (os.getenv("MAX_BOT_TOKEN") or "").strip()
# В документации встречаются оба домена; оставлено настраиваемым.
MAX_API_URL: str = (os.getenv("MAX_API_URL") or "https://platform-api2.max.ru").strip()
MAX_MODE: str = (os.getenv("MAX_MODE") or "polling").strip().lower()  # polling | webhook
MAX_WEBHOOK_URL: str = (os.getenv("MAX_WEBHOOK_URL") or "").strip()
MAX_WEBHOOK_PORT: int = _int("MAX_WEBHOOK_PORT", 8081)

LOG_LEVEL: str = (os.getenv("LOG_LEVEL") or "INFO").upper()
# Каталог журналов. Лежит внутри data/, чтобы его видели и бот, и хост:
# только так бот может отдавать журналы установки и свои собственные.
LOG_DIR: str = (os.getenv("LOG_DIR") or "data/logs").strip()
LOG_KEEP_DAYS: int = max(0, _int("LOG_KEEP_DAYS", 14))
LOG_MAX_MB: int = max(1, _int("LOG_MAX_MB", 5))
USER_AGENT: str = (
    os.getenv("USER_AGENT") or f"RadarBot/{VERSION} (+https://github.com/Chistovik92/radar)"
).strip()

# Города, чьи наборы источников подключаются при первом запуске.
# Доступны: saratov, moscow, spb, kazan, samara (см. radar/presets.py).
SOURCE_CITIES: list[str] = _list("SOURCE_CITIES")

AI_ENABLED: bool = bool(GEMINI_API_KEY)


def setup_logging() -> logging.Logger:
    """Логи одновременно в консоль (docker logs) и в файл внутри data/logs."""
    import logging.handlers

    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)-16s | %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "bot.log")
        rotating = logging.handlers.RotatingFileHandler(
            path, maxBytes=LOG_MAX_MB * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        rotating.setFormatter(fmt)
        root.addHandler(rotating)
    except OSError as exc:  # noqa: BLE001
        root.warning("Журнал в файл недоступен (%s) — пишу только в консоль", exc)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    # Alembic на старте печатает десятки строк о загрузке плагинов —
    # в них тонет всё, что действительно важно при диагностике запуска.
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
    logging.getLogger("alembic.autogenerate").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    return logging.getLogger("radar")


def validate() -> None:
    """Проверяет обязательные параметры и завершает процесс при их отсутствии."""
    log = logging.getLogger("radar.config")
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN не задан")
    if not is_sqlite() and not DATABASE_URL and not DB_PASSWORD:
        problems.append("DB_PASSWORD не задан (или задайте DATABASE_URL целиком)")
    elif DB_PASSWORD and "$" in DB_PASSWORD:
        # Docker Compose раскрывает $ в env_file как подстановку переменной,
        # и до PostgreSQL доедет искажённый пароль.
        problems.append(
            "DB_PASSWORD содержит символ $ — Docker Compose трактует его как "
            "подстановку переменной. Замените пароль на строку без $ "
            "(например: head -c 24 /dev/urandom | base64 | tr -d '/+=$')"
        )
    if not SUPERADMIN_ID:
        problems.append("SUPERADMIN_ID не задан или равен 0")
    if problems:
        for item in problems:
            log.critical("Ошибка конфигурации: %s", item)
        log.critical("Заполните .env и перезапустите контейнер.")
        sys.exit(1)
    if not AI_ENABLED:
        log.warning(
            "GEMINI_API_KEY не задан: ИИ-ассистент отключён, "
            "анализ новостей переключён на эвристический режим."
        )
RADAR_FILE_07
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/textutils.py"
cat > "radar/textutils.py" <<'RADAR_FILE_08'
"""Чистые утилиты: разметка, нормализация адресов, геометрия, кластеризация.

Модуль намеренно не импортирует внешние пакеты — его можно тестировать
без установленного aiogram/aiohttp/google-genai.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
import math
import re
from typing import Any, Iterable, Sequence

TG_LIMIT = 3800

# --------------------------------------------------------------------------
#  Разметка Telegram (HTML)
# --------------------------------------------------------------------------

_CODE_BLOCK = re.compile(r"```(?:[\w+-]*)\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_HEADER = re.compile(r"(?m)^\s{0,3}#{1,6}\s*(.+)$")
_TAG = re.compile(r"<[^>]+>")

def esc(text: Any) -> str:
    """Экранирует текст для Telegram-HTML."""
    return html.escape(str(text), quote=False)


def esc_attr(value: Any) -> str:
    """Экранирует значение HTML-атрибута.

    Отличается от esc() тем, что экранирует кавычки: незакрытая кавычка
    в URL разрывает атрибут href, и Telegram отвергает всё сообщение.
    """
    return html.escape(str(value), quote=True)


def md_to_html(text: str) -> str:
    """Переводит Markdown-ответ модели в безопасный Telegram-HTML."""
    stash: list[str] = []

    def keep(match: re.Match, tag: str) -> str:
        stash.append(f"<{tag}>{html.escape(match.group(1))}</{tag}>")
        return f"\x00{len(stash) - 1}\x00"

    text = _CODE_BLOCK.sub(lambda m: keep(m, "pre"), text)
    text = _INLINE_CODE.sub(lambda m: keep(m, "code"), text)
    text = html.escape(text, quote=False)
    text = _HEADER.sub(r"<b>\1</b>", text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def strip_tags(text: str) -> str:
    return html.unescape(_TAG.sub("", text))


def split_text(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Режет длинное сообщение по строкам, не превышая лимит Telegram."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(buf) + len(line) > limit:
            parts.append(buf)
            buf = line
        else:
            buf += line
    if buf:
        parts.append(buf)
    return parts


# --------------------------------------------------------------------------
#  Нормализация адресов
# --------------------------------------------------------------------------

STREET_TYPES = {
    "улица", "ул", "проспект", "пр", "прт", "проспк", "переулок", "пер",
    "бульвар", "бр", "шоссе", "ш", "площадь", "пл", "проезд", "тупик",
    "набережная", "наб", "аллея", "тракт", "микрорайон", "мкр", "квартал",
    "поселок", "посёлок", "пос", "деревня", "дер", "село", "линия", "въезд",
    "спуск", "взвоз",
}

CITY_TYPES = {"город", "г", "гор", "поселок", "посёлок", "пгт", "село", "деревня"}

_WORD = re.compile(r"[а-яёa-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower().replace("ё", "е"))


def normalize_street(name: str) -> str:
    """«ул. им. Чапаева В.И.» → «чапаева»; «проспект 50 лет Октября» → «50 лет октября»."""
    words = [w for w in _words(name) if w not in STREET_TYPES]
    words = [w for w in words if w not in {"им", "имени"}]
    # одиночные инициалы (в, и, а) отбрасываем
    words = [w for w in words if len(w) > 1 or w.isdigit()]
    return " ".join(words).strip()


def normalize_city(name: str) -> str:
    words = [w for w in _words(name) if w not in CITY_TYPES]
    return " ".join(words).strip()


def normalize_house(house: str) -> str:
    """«д. 12/1 корп. 2» → «12/1»; «14А» → «14а»."""
    raw = (house or "").lower().replace("ё", "е").replace("\\", "/")
    match = re.search(r"\d+\s*[а-я]?(?:\s*/\s*\d+\s*[а-я]?)?", raw)
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(0))


def same_city(a: str, b: str) -> bool:
    na, nb = normalize_city(a), normalize_city(b)
    if not na or not nb:
        return True  # недостаточно данных — не отсекаем
    return na == nb or na in nb or nb in na


def street_matches(loc_street: str, news_street: str) -> bool:
    a, b = normalize_street(loc_street), normalize_street(news_street)
    if not a or not b:
        return False
    if a == b:
        return True
    aw, bw = set(a.split()), set(b.split())
    if aw <= bw or bw <= aw:
        return True
    common = aw & bw
    return bool(common) and min(len(aw), len(bw)) > 0 and len(common) / min(len(aw), len(bw)) >= 1.0


def house_in_range(loc_house: str, houses: Sequence[str]) -> bool:
    """Пустой список домов = вся улица. Поддерживает диапазоны «12-18»."""
    if not houses:
        return True
    target = normalize_house(loc_house)
    if not target:
        return True
    target_num = re.match(r"\d+", target)
    for item in houses:
        raw = (item or "").lower().replace("ё", "е")
        rng = re.match(r"\s*(\d+)\s*[-–—]\s*(\d+)\s*$", raw)
        if rng and target_num:
            low, high = sorted((int(rng.group(1)), int(rng.group(2))))
            if low <= int(target_num.group(0)) <= high:
                return True
            continue
        if normalize_house(item) == target:
            return True
    return False


def district_matches(loc_district: str, news_district: str) -> bool:
    a = " ".join(w for w in _words(loc_district) if w != "район")
    b = " ".join(w for w in _words(news_district) if w != "район")
    return bool(a) and bool(b) and (a == b or a in b or b in a)


# --------------------------------------------------------------------------
#  Геометрия и кластеризация локаций
# --------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между точками в метрах."""
    radius = 6371008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def cluster_locations(
    locations: Iterable[dict[str, Any]], radius_m: float = 1000.0
) -> list[list[dict[str, Any]]]:
    """Объединяет локации, отстоящие друг от друга не более чем на radius_m.

    Связность транзитивная (union-find): A—B и B—C дают один кластер.
    Локации без координат образуют отдельные кластеры.
    """
    locs = list(locations)
    count = len(locs)
    if count == 0:
        return []

    parent = list(range(count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    def coords(loc: dict[str, Any]) -> tuple[float, float] | None:
        lat, lon = loc.get("lat"), loc.get("lon")
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if lat == 0.0 and lon == 0.0:
            return None
        return lat, lon

    for i in range(count):
        ci = coords(locs[i])
        if ci is None:
            continue
        for j in range(i + 1, count):
            cj = coords(locs[j])
            if cj is None:
                continue
            if haversine_m(ci[0], ci[1], cj[0], cj[1]) <= radius_m:
                union(i, j)

    buckets: dict[int, list[dict[str, Any]]] = {}
    for index, loc in enumerate(locs):
        buckets.setdefault(find(index), []).append(loc)
    return [buckets[key] for key in sorted(buckets)]


def cluster_center(cluster: Sequence[dict[str, Any]]) -> tuple[float, float]:
    points = [
        (float(loc["lat"]), float(loc["lon"]))
        for loc in cluster
        if loc.get("lat") or loc.get("lon")
    ]
    if not points:
        return 0.0, 0.0
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )
RADAR_FILE_08
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/roles.py"
cat > "radar/roles.py" <<'RADAR_FILE_09'
"""Роли и права доступа.

Иерархия: superadmin (3) > admin (2) > moderator (1) > user (0).

* Суперадминистратор может всё, включая назначение администраторов.
* Администратор назначает модераторов и обычных пользователей, удаляет
  пользователей уровнем ниже себя.
* Модератор редактирует локации и настройки оповещений пользователей,
  модерирует источники, пользуется ИИ-ассистентом, но никого не назначает
  и не удаляет.
* Пользователь управляет только собой.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

USER = "user"
MODERATOR = "moderator"
ADMIN = "admin"
SUPERADMIN = "superadmin"

ORDER = (USER, MODERATOR, ADMIN, SUPERADMIN)
LEVEL = {role: index for index, role in enumerate(ORDER)}

TITLES = {
    USER: "👤 Пользователь",
    MODERATOR: "🛡 Модератор",
    ADMIN: "👑 Администратор",
    SUPERADMIN: "⭐️ Суперадминистратор",
}

def level(role: str | None) -> int:
    return LEVEL.get(role or USER, 0)


def title(role: str | None) -> str:
    return TITLES.get(role or USER, TITLES[USER])


def at_least(role: str | None, minimum: str) -> bool:
    return level(role) >= level(minimum)


def is_moderator(role: str | None) -> bool:
    return at_least(role, MODERATOR)


def is_admin(role: str | None) -> bool:
    return at_least(role, ADMIN)


def is_superadmin(role: str | None) -> bool:
    return role == SUPERADMIN


def assignable_roles(actor_role: str | None) -> list[str]:
    """Какие роли актор вправе выдавать."""
    if is_superadmin(actor_role):
        return [USER, MODERATOR, ADMIN]
    if is_admin(actor_role):
        return [USER, MODERATOR]
    return []


def can_assign(actor_role: str | None, target_role: str | None, new_role: str) -> bool:
    """Может ли актор сменить роль target_role на new_role."""
    if new_role not in assignable_roles(actor_role):
        return False
    if target_role == SUPERADMIN:
        return False
    if is_superadmin(actor_role):
        return True
    # админ не трогает равных и старших
    return level(target_role) < level(actor_role)


def can_delete_user(actor_role: str | None, target_role: str | None) -> bool:
    """Удаление пользователей — от администратора и выше."""
    if not is_admin(actor_role):
        return False
    if target_role == SUPERADMIN:
        return False
    if is_superadmin(actor_role):
        return True
    return level(target_role) < level(actor_role)


def can_edit_user(actor_role: str | None, target_role: str | None) -> bool:
    """Правка локаций и настроек оповещений — от модератора и выше."""
    if not is_moderator(actor_role):
        return False
    if target_role == SUPERADMIN:
        return is_superadmin(actor_role)
    if is_superadmin(actor_role):
        return True
    return level(target_role) < level(actor_role)


def can_moderate_sources(actor_role: str | None) -> bool:
    return is_moderator(actor_role)


def can_use_assistant(actor_role: str | None) -> bool:
    return is_moderator(actor_role)
RADAR_FILE_09
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/ratelimit.py"
cat > "radar/ratelimit.py" <<'RADAR_FILE_10'
"""Учёт квот Gemini: запросы в минуту, запросы в сутки, резерв под ассистента.

Бесплатный тариф Gemini ограничен по RPM и RPD (для 2.5-flash — порядка
10 запросов в минуту), поэтому фоновый анализ новостей обязан уступать
дорогу живому диалогу с ассистентом. Дневной счётчик сбрасывается в полночь
по тихоокеанскому времени — так, как это делает Google.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

log = logging.getLogger("radar.ratelimit")

# Тихоокеанское время: UTC-8 зимой, UTC-7 летом. Для суточной границы
# достаточно приблизительного смещения.
_PACIFIC_OFFSET = timedelta(hours=-8)

def pacific_day() -> str:
    return (datetime.now(timezone.utc) + _PACIFIC_OFFSET).strftime("%Y-%m-%d")


class QuotaExceeded(RuntimeError):
    """Лимит исчерпан; вызывающая сторона решает, ждать или деградировать."""


class RateLimiter:
    """Скользящее окно по минуте плюс суточный счётчик с резервом."""

    def __init__(self, rpm: int, rpd: int, reserve: int = 0, cooldown: int = 900) -> None:
        self.rpm = max(1, rpm)
        self.rpd = max(1, rpd)
        self.reserve = max(0, reserve)      # запросов, доступных только ассистенту
        self.cooldown = cooldown            # пауза фонового анализа после 429, сек
        self._minute: deque[float] = deque()
        self._day = pacific_day()
        self._used = 0
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    # -- внутреннее --------------------------------------------------------

    def _roll(self) -> None:
        now = time.monotonic()
        while self._minute and now - self._minute[0] >= 60:
            self._minute.popleft()
        today = pacific_day()
        if today != self._day:
            self._day = today
            self._used = 0
            self._blocked_until = 0.0
            log.info("Суточная квота Gemini обнулена (новый день %s по PT)", today)

    def _budget(self, priority: bool) -> int:
        return self.rpd if priority else max(0, self.rpd - self.reserve)

    # -- публичное ---------------------------------------------------------

    @property
    def paused(self) -> bool:
        """Фоновый анализ временно остановлен после ответа 429."""
        return time.monotonic() < self._blocked_until

    async def try_acquire(self, priority: bool = False) -> bool:
        """Берёт слот без ожидания. False — вызывающий переходит на эвристику."""
        async with self._lock:
            self._roll()
            if not priority and self.paused:
                return False
            if self._used >= self._budget(priority):
                return False
            if len(self._minute) >= self.rpm:
                return False
            self._minute.append(time.monotonic())
            self._used += 1
            return True

    async def wait_acquire(self, priority: bool = True, timeout: float = 45.0) -> None:
        """Ждёт свободный слот. Бросает QuotaExceeded, если не дождались."""
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                self._roll()
                if self._used >= self._budget(priority):
                    raise QuotaExceeded("суточная квота исчерпана")
                if len(self._minute) < self.rpm:
                    self._minute.append(time.monotonic())
                    self._used += 1
                    return
                oldest = self._minute[0]
            pause = max(0.5, 60 - (time.monotonic() - oldest))
            if time.monotonic() + pause > deadline:
                raise QuotaExceeded("лимит запросов в минуту, попробуйте позже")
            await asyncio.sleep(min(pause, 5.0))

    def note_rejection(self) -> None:
        """Google ответил 429: приостанавливаем фоновый анализ и считаем сутки занятыми."""
        self._blocked_until = time.monotonic() + self.cooldown
        self._used = max(self._used, self._budget(False))
        log.warning(
            "Получен 429: фоновый анализ приостановлен на %d мин, "
            "оставшаяся квота зарезервирована под ассистента",
            self.cooldown // 60,
        )

    def snapshot(self) -> dict[str, int | bool]:
        self._roll()
        return {
            "used_today": self._used,
            "limit_day": self.rpd,
            "in_minute": len(self._minute),
            "limit_minute": self.rpm,
            "paused": self.paused,
        }
RADAR_FILE_10
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/matching.py"
cat > "radar/matching.py" <<'RADAR_FILE_11'
"""Модель разобранной новости, правила сопоставления с локациями и сборка сообщений.

Только стандартная библиотека — модуль полностью покрывается тестами офлайн.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .textutils import (
    cluster_locations,
    district_matches,
    esc,
    esc_attr,
    house_in_range,
    normalize_city,
    same_city,
    street_matches,
)

# Ключи категорий совпадают с настройками пользователя из версий 2.x —
# это сохраняет совместимость с продакшен-базой.
CATEGORY_TITLES = {
    "bpla": "БПЛА / ракетная опасность",
    "mchs": "Экстренные оповещения МЧС",
    "jkh": "ЖКХ и аварии на сетях",
    "whitelist": "Предупреждать о «белых списках»",
}

CATEGORY_ICONS = {"bpla": "🛸", "mchs": "🆘", "jkh": "🛠", "whitelist": "📶"}

# Военные угрозы объявляются на весь город, независимо от указанных улиц.
CITY_WIDE_ALWAYS = {"bpla"}
# Связь и «белые списки» обычно вводятся на город/регион целиком.
CITY_WIDE_DEFAULT = {"whitelist"}

SEVERITY_ICONS = {"critical": "🔴", "warning": "🟠", "info": "🔵"}

# О «белых списках» в городских пабликах почти не пишут — операторы вводят их
# молча. Поэтому предупреждение выдаётся не по новости, а автоматически:
# объявлена угроза БПЛА или ракетная опасность → значит связь, скорее всего,
# уже ограничена.
ALL_CLEAR_NOTICE = (
    "📶 <b>Мобильный интернет</b>\n"
    "«Белые списки» могут быть отключены в ближайшее время — связь обычно "
    "восстанавливают не сразу после отбоя, а в течение нескольких часов."
)

WHITELIST_NOTICE = (
    "📵 <b>Мобильный интернет</b>\n"
    "При угрозе с воздуха операторы включают «белые списки»: работают только "
    "госуслуги, банки, карты и такси. Мессенджеры и соцсети могут не открываться.\n"
    "Домашний проводной интернет и Wi-Fi обычно продолжают работать. "
    "Для срочной связи — звонки и SMS."
)

@dataclass
class Analysis:
    """Результат разбора одного сообщения источника."""

    relevant: bool = False
    categories: list[str] = field(default_factory=list)
    severity: str = "info"
    scope: str = "city"  # region | city | district | street
    region: str = ""
    city: str = ""
    districts: list[str] = field(default_factory=list)
    streets: list[dict[str, Any]] = field(default_factory=list)  # {"street": str, "houses": [str]}
    summary: str = ""
    source: str = ""
    raw: str = ""
    link: str = ""            # ссылка на новость (для RSS)
    all_clear: bool = False   # отбой ранее объявленной опасности
    engine: str = "ai"  # ai | heuristic

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], *, source: str, raw: str, link: str = ""
    ) -> "Analysis":
        streets: list[dict[str, Any]] = []
        for item in payload.get("streets") or []:
            if isinstance(item, str):
                streets.append({"street": item, "houses": []})
            elif isinstance(item, dict) and item.get("street"):
                houses = item.get("houses") or []
                streets.append(
                    {
                        "street": str(item["street"]),
                        "houses": [str(h) for h in houses if str(h).strip()],
                    }
                )
        categories = [c for c in (payload.get("categories") or []) if c in CATEGORY_TITLES]
        severity = str(payload.get("severity") or "info").lower()
        scope = str(payload.get("scope") or "city").lower()
        return cls(
            relevant=bool(payload.get("relevant")) and bool(categories),
            categories=categories,
            severity=severity if severity in SEVERITY_ICONS else "info",
            scope=scope if scope in {"region", "city", "district", "street"} else "city",
            region=str(payload.get("region") or "").strip(),
            city=str(payload.get("city") or "").strip(),
            districts=[str(d) for d in (payload.get("districts") or []) if str(d).strip()],
            streets=streets,
            summary=str(payload.get("summary") or "").strip(),
            source=source,
            raw=raw,
            link=link,
            all_clear=bool(payload.get("all_clear")),
        )

    @property
    def is_city_wide(self) -> bool:
        """Оповещение действует на весь город (военная угроза, связь, общегородская ЧС)."""
        cats = set(self.categories)
        if cats & CITY_WIDE_ALWAYS:
            return True
        if cats & CITY_WIDE_DEFAULT and not self.streets:
            return True
        if "jkh" in cats:
            return False
        # МЧС и прочее: адресное, только если названы конкретные улицы
        return not self.streets

    @property
    def icon(self) -> str:
        for key in ("bpla", "mchs", "jkh", "whitelist"):
            if key in self.categories:
                return CATEGORY_ICONS[key]
        return "ℹ️"

    def title(self) -> str:
        names = [CATEGORY_TITLES[c] for c in self.categories if c in CATEGORY_TITLES]
        return " / ".join(names) or "Событие"

    def text(self) -> str:
        return self.summary or self.raw[:300]


# --------------------------------------------------------------------------
#  Эвристический разбор (работает без Gemini)
# --------------------------------------------------------------------------

_HEURISTICS: list[tuple[str, re.Pattern]] = [
    ("bpla", re.compile(
        r"бпла|беспилотн|дрон|воздушн\w* тревог|ракетн\w* опасн|работа\w* пво|"
        r"противовоздушн|обломк\w* бпла|угроз\w* атаки", re.I)),
    ("mchs", re.compile(
        r"мчс|штормов\w* предупрежд|чрезвычайн\w* ситуац|эвакуац|крупн\w* пожар|"
        r"экстренн\w* оповещ|режим повышенной готовности|паводок|подтоплен", re.I)),
    ("jkh", re.compile(
        r"отключ\w*\s+(?:воды|холодн|горяч|электро|света|газ|отоплен)|"
        r"без воды|без света|без газа|без отоплен|прекращ\w* подач|"
        r"аварий\w*\s+(?:работ|отключ|ситуац)|порыв|утечк\w* газа|"
        r"ремонтн\w* работ|коммунальн\w* авар|обесточ", re.I)),
    ("whitelist", re.compile(
        r"бел\w* список|ограничен\w* мобильн\w* интернет|мобильн\w* интернет"
        r"|перебо\w* (?:со )?связ|ограничен\w* связи", re.I)),
]

ALL_CLEAR_RE = re.compile(
    r"отбо[йя]\b|снят\w*\s+(?:режим\w*\s+)?(?:беспилотн\w*|ракетн\w*|воздушн\w*|опасн\w*)|"
    r"опасност\w*\s+снят|угроза\s+снят|тревога\s+отмен|"
    r"режим\w*\s+беспилотн\w*\s+опасност\w*\s+отмен|"
    r"отмен\w*\s+(?:режим\w*\s+)?(?:беспилотн\w*|ракетн\w*|воздушн\w*)|"
    r"обстановка\s+спокойн|угроз\w*\s+миновал",
    re.I,
)

_STREET_TYPE_RE = (
    r"(?:ул(?:ица|\.)?|пр(?:оспект|-т|\.)?|пер(?:еулок|\.)?|б(?:ульвар|-р)|"
    r"ш(?:оссе|\.)?|пл(?:ощадь|\.)?|проезд|наб(?:ережная|\.)?|тракт|мкр(?:орайон)?)"
)
_STREET_AFTER = re.compile(
    _STREET_TYPE_RE + r"\s+([А-ЯЁ][\w\-]+(?:\s+[А-ЯЁ]?[\w\-]+){0,2})", re.U
)
_STREET_BEFORE = re.compile(
    r"([А-ЯЁ][\w\-]+(?:\s+[А-ЯЁ]?[\w\-]+){0,1})\s+" + _STREET_TYPE_RE + r"(?![\w])", re.U
)
_HOUSES = re.compile(r"(?:д(?:ом|\.)|№)\s*([\d]+[А-Яа-яA-Za-z]?(?:\s*/\s*\d+)?)", re.U)
_DISTRICT = re.compile(r"([А-ЯЁ][а-яё\-]+)\s+район", re.U)
_CITY = re.compile(r"(?:в|город[еа]?|г\.)\s+([А-ЯЁ][а-яё\-]+)", re.U)


def heuristic_analysis(
    text: str, *, source: str = "", default_city: str = "", link: str = ""
) -> Analysis:
    """Резервный разбор без ИИ: ключевые слова + извлечение улиц и домов."""
    categories = [key for key, pattern in _HEURISTICS if pattern.search(text)]
    if not categories:
        return Analysis(
            relevant=False, source=source, raw=text, link=link, engine="heuristic"
        )

    streets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in list(_STREET_AFTER.finditer(text)) + list(_STREET_BEFORE.finditer(text)):
        name = match.group(1).strip(" ,.;:")
        key = name.lower()
        if len(name) < 3 or key in seen:
            continue
        seen.add(key)
        tail = text[match.end(): match.end() + 60]
        houses = [h.replace(" ", "") for h in _HOUSES.findall(tail)]
        streets.append({"street": name, "houses": houses})

    districts = [f"{d} район" for d in dict.fromkeys(_DISTRICT.findall(text))]
    city_match = _CITY.search(text)
    city = city_match.group(1) if city_match else default_city

    if "bpla" in categories:
        scope = "city"
    elif streets:
        scope = "street"
    elif districts:
        scope = "district"
    else:
        scope = "city"

    all_clear = bool(ALL_CLEAR_RE.search(text))
    if all_clear:
        severity = "info"
    else:
        severity = "critical" if {"bpla", "mchs"} & set(categories) else "warning"
    summary = re.sub(r"\s+", " ", text).strip()
    return Analysis(
        relevant=True,
        all_clear=all_clear,
        categories=categories,
        severity=severity,
        scope=scope,
        city=city,
        districts=districts,
        streets=streets[:8],
        summary=summary[:400],
        source=source,
        raw=text,
        link=link,
        engine="heuristic",
    )


# --------------------------------------------------------------------------
#  Сопоставление новости с локацией
# --------------------------------------------------------------------------

def location_city(loc: dict[str, Any]) -> str:
    return str(loc.get("city") or "")


def matches_location(analysis: Analysis, loc: dict[str, Any]) -> bool:
    """Затрагивает ли событие конкретную локацию пользователя."""
    if not analysis.relevant:
        return False

    loc_city = location_city(loc)
    if analysis.city and loc_city and not same_city(analysis.city, loc_city):
        # Регион совпал, город — нет: пропускаем, кроме региональных оповещений
        if not (analysis.scope == "region" and analysis.region and loc.get("region")
                and same_city(analysis.region, str(loc["region"]))):
            return False

    if analysis.is_city_wide:
        return True

    # Адресный уровень: улица (и дом), затем район, затем общегородская авария.
    loc_street = str(loc.get("street") or "")
    loc_house = str(loc.get("house") or "")
    if analysis.streets:
        if not loc_street:
            return _raw_mentions_location(analysis, loc)
        for item in analysis.streets:
            if street_matches(loc_street, item.get("street", "")):
                if house_in_range(loc_house, item.get("houses") or []):
                    return True
        return False

    if analysis.districts:
        loc_district = str(loc.get("district") or "")
        if loc_district:
            return any(district_matches(loc_district, d) for d in analysis.districts)
        return False

    if analysis.scope in ("city", "region"):
        return True

    return False


def _raw_mentions_location(analysis: Analysis, loc: dict[str, Any]) -> bool:
    """Запасной путь для старых локаций без разобранного адреса."""
    name = str(loc.get("name") or "")
    tokens = {w for w in re.findall(r"[а-яёa-z0-9]{4,}", name.lower())}
    if not tokens:
        return False
    haystack = (analysis.raw + " " + " ".join(s.get("street", "") for s in analysis.streets)).lower()
    return any(token in haystack for token in tokens)


def match_locations(analysis: Analysis, locations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [loc for loc in locations if matches_location(analysis, loc)]


# --------------------------------------------------------------------------
#  Сборка сообщений
# --------------------------------------------------------------------------

def _loc_label(loc: dict[str, Any]) -> str:
    return esc(loc.get("name") or "локация")


def format_locations_header(locations: Sequence[dict[str, Any]], note: str = "") -> str:
    names = ", ".join(_loc_label(loc) for loc in locations)
    suffix = f" <i>({note})</i>" if note else ""
    return f"📍 <b>Совпавшие локации:</b> {names}{suffix}"


def _source_label(analysis: Analysis) -> str:
    label = analysis.source or "источник"
    name = esc(label) if ("." in label or "/" in label) else f"@{esc(label)}"
    # У новости из RSS есть прямая ссылка — делаем заголовок кликабельным.
    if analysis.link:
        return f'<a href="{esc_attr(analysis.link)}">{name}</a>'
    return name


def _event_line(analysis: Analysis) -> str:
    icon = "✅" if analysis.all_clear else SEVERITY_ICONS.get(analysis.severity, "🔵")
    mark = "" if analysis.engine == "ai" else " <i>(без ИИ)</i>"
    line = f"{icon} <b>{_source_label(analysis)}</b>{mark}\n{esc(analysis.text())}"
    if analysis.link:
        line += f'\n🔗 <a href="{esc_attr(analysis.link)}">Читать источник</a>'
    return line


def build_city_alert(
    city: str,
    locations: Sequence[dict[str, Any]],
    events: Sequence[Analysis],
    whitelist_notice: bool = False,
) -> str:
    """Одно сообщение на город: военные и другие общегородские угрозы."""
    titles = {analysis.title() for analysis in events}
    head = f"🚨 <b>ОПАСНОСТЬ — {esc(city or 'город')}</b>"
    lines = [
        head,
        f"<b>{esc(' / '.join(sorted(titles)))}</b>",
        format_locations_header(locations, "весь город"),
        "",
    ]
    lines.extend(_event_line(analysis) for analysis in events)
    if whitelist_notice:
        lines.append("")
        lines.append(WHITELIST_NOTICE)
    return "\n".join(lines)


def build_all_clear(
    city: str,
    locations: Sequence[dict[str, Any]],
    events: Sequence[Analysis],
    whitelist_notice: bool = False,
) -> str:
    """Отбой опасности: спокойный тон, другой сигнал, без слова «ОПАСНОСТЬ»."""
    titles = {analysis.title() for analysis in events}
    lines = [
        f"✅ <b>ОТБОЙ — {esc(city or 'город')}</b>",
        f"<b>{esc(' / '.join(sorted(titles)))}</b> — опасность снята",
        format_locations_header(locations, "весь город"),
        "",
    ]
    lines.extend(_event_line(analysis) for analysis in events)
    if whitelist_notice:
        lines.append("")
        lines.append(ALL_CLEAR_NOTICE)
    return "\n".join(lines)


def build_utility_alert(locations: Sequence[dict[str, Any]], events: Sequence[Analysis], grouped: bool) -> str:
    """Сообщение по ЖКХ/адресным событиям для одной группы локаций."""
    note = "в пределах 1 км" if grouped else ""
    lines = [
        "🛠 <b>ЖКХ и аварии на сетях</b>",
        format_locations_header(locations, note),
        "",
    ]
    lines.extend(_event_line(analysis) for analysis in events)
    return "\n".join(lines)


def cluster_title(cluster: Sequence[dict[str, Any]]) -> str:
    """Заголовок сводки погоды: одна локация или список объединённых."""
    names = ", ".join(_loc_label(loc) for loc in cluster)
    if len(cluster) > 1:
        return f"📍 <b>{names}</b> <i>(в пределах 1 км)</i>"
    return f"📍 <b>{names}</b>"


# --------------------------------------------------------------------------
#  Группировка оповещений для одного пользователя
# --------------------------------------------------------------------------

def _city_of(analysis: Analysis, locations: Sequence[dict[str, Any]], fallback: str) -> tuple[str, str]:
    """Ключ группировки по городу и его отображаемое имя."""
    for loc in locations:
        city = str(loc.get("city") or "")
        if city:
            return normalize_city(city), city
    city = analysis.city or fallback
    return normalize_city(city), city or "город"


def plan_alerts(
    locations: Sequence[dict[str, Any]],
    settings: dict[str, Any],
    analyses: Sequence[Analysis],
    radius_m: float = 1000.0,
    default_city: str = "",
) -> list[tuple[str, str]]:
    """Собирает готовые сообщения для пользователя.

    Правила:
      * военные и другие общегородские угрозы — одно сообщение на город
        со списком всех совпавших локаций в нём;
      * ЖКХ и адресные события — отдельное сообщение на группу локаций;
      * локации ближе radius_m объединяются в одну группу.

    Возвращает список пар («city» | «utility», текст сообщения).
    """
    if not locations:
        return []

    enabled = {key for key, value in (settings or {}).items() if value}
    warn_about_whitelist = "whitelist" in enabled
    clusters = cluster_locations(locations, radius_m)

    city_buckets: dict[str, dict[str, Any]] = {}
    cluster_buckets: dict[int, dict[str, Any]] = {}

    for analysis in analyses:
        if not analysis.relevant or not (set(analysis.categories) & enabled):
            continue
        matched = match_locations(analysis, locations)
        if not matched:
            continue

        if analysis.is_city_wide:
            key, label = _city_of(analysis, matched, default_city)
            # Отбой не должен смешиваться с действующей тревогой в одном сообщении.
            bucket_key = f"{key}:clear" if analysis.all_clear else key
            bucket = city_buckets.setdefault(
                bucket_key,
                {"city": label, "locs": {}, "events": [], "all_clear": analysis.all_clear},
            )
            bucket["events"].append(analysis)
            for loc in matched:
                bucket["locs"][loc.get("id") or loc.get("name")] = loc
            continue

        matched_ids = {id(loc) for loc in matched}
        for index, cluster in enumerate(clusters):
            inside = [loc for loc in cluster if id(loc) in matched_ids]
            if not inside:
                continue
            bucket = cluster_buckets.setdefault(
                index, {"size": len(cluster), "locs": {}, "events": []}
            )
            bucket["events"].append(analysis)
            for loc in inside:
                bucket["locs"][loc.get("id") or loc.get("name")] = loc

    messages: list[tuple[str, str]] = []
    for bucket in city_buckets.values():
        military = any("bpla" in analysis.categories for analysis in bucket["events"])
        notice = military and warn_about_whitelist
        locs = list(bucket["locs"].values())
        if bucket["all_clear"]:
            messages.append(
                ("clear", build_all_clear(bucket["city"], locs, bucket["events"], notice))
            )
        else:
            messages.append(
                ("city", build_city_alert(bucket["city"], locs, bucket["events"], notice))
            )
    for bucket in cluster_buckets.values():
        messages.append(
            (
                "utility",
                build_utility_alert(
                    list(bucket["locs"].values()), bucket["events"], grouped=bucket["size"] > 1
                ),
            )
        )
    return messages
RADAR_FILE_11
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/identity.py"
cat > "radar/identity.py" <<'RADAR_FILE_12'
"""Идентификация пользователя независимо от мессенджера.

Ключ рабочего набора в памяти — строка вида `telegram:123456` или `max:987`.
Для Telegram допускается краткая форма без префикса: так обработчики версий
3.x, передающие `str(message.from_user.id)`, продолжают работать без правок.

Единая точка разбора нужна затем, чтобы в 4.2 добавление MAX не потребовало
трогать логику ролей, локаций и оповещений — она оперирует ключом, а не
конкретным мессенджером.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass

TELEGRAM = "telegram"
MAX = "max"
PLATFORMS = (TELEGRAM, MAX)

DEFAULT_PLATFORM = TELEGRAM

TITLES = {TELEGRAM: "Telegram", MAX: "MAX"}


@dataclass(frozen=True)
class Identity:
    platform: str
    external_id: str

    @property
    def key(self) -> str:
        """Ключ рабочего набора. Telegram — без префикса, ради совместимости."""
        if self.platform == TELEGRAM:
            return self.external_id
        return f"{self.platform}:{self.external_id}"

    @property
    def title(self) -> str:
        return TITLES.get(self.platform, self.platform)

    def __str__(self) -> str:  # удобно в логах
        return self.key


def parse(key: str | int) -> Identity:
    """Разбирает ключ рабочего набора в пару платформа/идентификатор."""
    text = str(key).strip()
    if ":" in text:
        platform, _, external = text.partition(":")
        platform = platform.strip().lower()
        if platform in PLATFORMS:
            return Identity(platform, external.strip())
    return Identity(TELEGRAM, text)


def make(platform: str, external_id: str | int) -> Identity:
    platform = (platform or DEFAULT_PLATFORM).strip().lower()
    if platform not in PLATFORMS:
        platform = DEFAULT_PLATFORM
    return Identity(platform, str(external_id).strip())


def key_of(platform: str, external_id: str | int) -> str:
    return make(platform, external_id).key


def is_telegram(key: str | int) -> bool:
    return parse(key).platform == TELEGRAM
RADAR_FILE_12
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/features.py"
cat > "radar/features.py" <<'RADAR_FILE_13'
"""Переключатели возможностей.

Каждая заметная функция объявлена флагом. Значение по умолчанию задаётся здесь,
переопределение хранится в базе, поэтому суперадминистратор включает и выключает
функции прямо в боте — без обновления версии и без перезапуска контейнера.

Так решается задача постепенного выката: новая возможность приезжает с версией
выключенной, включается на живой системе, а при проблемах гасится одной кнопкой.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("radar.features")


@dataclass(frozen=True)
class Flag:
    key: str
    title: str
    description: str
    default: bool = True
    group: str = "Общее"
    since: str = ""
    locked: bool = False   # нельзя выключить: ядро системы
    aliases: tuple[str, ...] = field(default_factory=tuple)


FLAGS: tuple[Flag, ...] = (
    # --- ядро ---
    Flag("alerts", "Оповещения об угрозах", "Рассылка событий по локациям.",
         group="Ядро", since="3.0", locked=True),
    Flag("weather", "Погода", "Сводки погоды по группам локаций.", group="Ядро", since="3.0"),
    Flag("ai_analysis", "ИИ-разбор новостей",
         "Классификация сообщений моделью. Выключение переводит систему "
         "на эвристику по ключевым словам.", group="Ядро", since="3.0"),
    Flag("ai_assistant", "ИИ-ассистент", "Диалог с моделью для модераторов и выше.",
         group="Ядро", since="3.0"),

    # --- источники ---
    Flag("source_telegram", "Источники Telegram", "Чтение публичных каналов t.me.",
         group="Источники", since="3.0"),
    Flag("source_rss", "Источники RSS", "Ленты СМИ и официальных сайтов.",
         group="Источники", since="3.0"),
    Flag("source_vk", "Источники ВКонтакте", "Стены открытых сообществ через VK API.",
         group="Источники", since="4.1", default=False),
    Flag("source_ok", "Источники Одноклассники",
         "Ленты групп через API OK. Требует регистрации приложения на apiok.ru.",
         group="Источники", since="4.1", default=False),

    # --- подача ---
    Flag("all_clear", "Отбой опасности", "Отдельное сообщение при снятии угрозы.",
         group="Подача", since="3.3.5"),
    Flag("whitelist_notice", "Примечание о «белых списках»",
         "Пояснение об ограничениях мобильного интернета.", group="Подача", since="3.3"),
    Flag("weather_image", "Погода картинкой",
         "Отрисованная сводка вместо текста. Требует Pillow.",
         group="Подача", since="4.1", default=False),
    Flag("quiet_hours", "Тихие часы", "Задержка несрочных оповещений ночью.",
         group="Подача", since="4.1", default=False),
    Flag("antispam", "Антиспам оповещений",
         "Не повторять одно событие для той же локации.", group="Подача", since="4.1"),

    # --- новостные подборки ---
    Flag("digest", "Новостные подборки",
         "Утренняя и вечерняя сводка новостей по выбранным тематикам.",
         group="Новости", since="4.3", default=False),
    Flag("digest_paid", "Платная подписка на подборки",
         "Оплата через Telegram Stars. Цены задаёт суперадминистратор.",
         group="Новости", since="4.3", default=False),
    Flag("digest_suggestions", "Предложение источников новостей",
         "Пользователи предлагают каналы и ленты по тематикам.",
         group="Новости", since="4.3", default=False),

    # --- экстренная помощь ---
    Flag("sos", "Кнопка SOS",
         "Отправка геопозиции экстренному контакту по нажатию кнопки.",
         group="Экстренное", since="4.1", default=False),

    # --- данные ---
    Flag("history", "История событий", "Журнал того, что приходило по адресу.",
         group="Данные", since="4.0"),
    Flag("source_export", "Выгрузка источников", "Скачивание и загрузка списка файлом.",
         group="Данные", since="3.3"),

    # --- инфраструктура ---
    Flag("egress_proxy", "Выход в сеть через внешний узел",
         "Исходящий трафик бота идёт через SOCKS5 от sing-box. "
         "Настраивается только суперадминистратором.",
         group="Инфраструктура", since="4.1", default=False),
    Flag("maintenance", "Режим обслуживания",
         "Бот отвечает «идут работы», фоновый цикл остановлен.",
         group="Инфраструктура", since="4.5", default=False),

    # --- платформы ---
    Flag("platform_max", "Мессенджер MAX", "Работа бота в MAX параллельно с Telegram.",
         group="Платформы", since="4.2", default=False),

    # --- партнёрские проекты ---
    Flag("partners", "Партнёрские проекты", "Раздел меню со списком проектов автора.",
         group="Партнёры", since="4.4", default=False,
         aliases=("promo",)),
    Flag("promo_button", "Кнопка партнёра", "Закреплённая кнопка проекта в меню.",
         group="Партнёры", since="3.3"),
    Flag("promo_codes", "Промокоды", "Персональные коды для партнёрских проектов.",
         group="Партнёры", since="4.4", default=False),

    # --- администрирование ---
    Flag("web_panel", "Веб-панель", "Панель администратора в браузере.",
         group="Администрирование", since="4.3", default=False),
)

BY_KEY: dict[str, Flag] = {flag.key: flag for flag in FLAGS}
GROUPS: tuple[str, ...] = tuple(dict.fromkeys(flag.group for flag in FLAGS))

# Переопределения из базы. Заполняется при старте, меняется командой в боте.
_overrides: dict[str, bool] = {}


def resolve(key: str) -> Flag | None:
    flag = BY_KEY.get(key)
    if flag is not None:
        return flag
    for candidate in FLAGS:
        if key in candidate.aliases:
            return candidate
    return None


def enabled(key: str) -> bool:
    """Включена ли возможность. Неизвестный ключ считается выключенным."""
    flag = resolve(key)
    if flag is None:
        log.warning("Запрошен неизвестный флаг «%s»", key)
        return False
    if flag.locked:
        return True
    return _overrides.get(flag.key, flag.default)


def snapshot() -> dict[str, bool]:
    return {flag.key: enabled(flag.key) for flag in FLAGS}


def overrides() -> dict[str, bool]:
    return dict(_overrides)


def apply(values: dict[str, bool]) -> None:
    """Загружает переопределения из базы."""
    _overrides.clear()
    for key, value in (values or {}).items():
        flag = resolve(key)
        if flag is not None and not flag.locked:
            _overrides[flag.key] = bool(value)


def set_local(key: str, value: bool) -> Flag | None:
    """Меняет флаг в памяти. Запись в базу — на стороне вызывающего."""
    flag = resolve(key)
    if flag is None or flag.locked:
        return None
    _overrides[flag.key] = bool(value)
    return flag


def by_group() -> dict[str, list[Flag]]:
    grouped: dict[str, list[Flag]] = {group: [] for group in GROUPS}
    for flag in FLAGS:
        grouped[flag.group].append(flag)
    return grouped
RADAR_FILE_13
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/logs.py"
cat > "radar/logs.py" <<'RADAR_FILE_14'
"""Журналы системы: перечисление, выгрузка и очистка.

Все журналы лежат в одном каталоге внутри `data/`, потому что это
единственный путь, видимый одновременно боту (внутри контейнера)
и установщику (на хосте). Благодаря этому суперадминистратор может
забрать журнал установки прямо из бота, не заходя по SSH.

Журналы контейнеров Docker сюда не попадают: чтобы их читать, боту
пришлось бы дать доступ к сокету Docker, а это фактически полный доступ
к хосту. Вместо этого установщик кладёт рядом скрипт `collect-logs.sh`,
который собирает всё в один архив уже на стороне сервера.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import io
import logging
import os
import re
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config

log = logging.getLogger("radar.logs")

# Что считаем журналом: имена, которые пишем мы сами и наш установщик.
PATTERNS = (
    re.compile(r"^bot\.log(\.\d+)?$"),
    re.compile(r"^installer_log.*\.txt$"),
    re.compile(r"^doctor.*\.(txt|json)$"),
)


@dataclass
class LogFile:
    path: Path
    kind: str          # bot | installer | doctor | other
    size: int
    modified: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_human(self) -> str:
        value = float(self.size)
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if value < 1024 or unit == "ГБ":
                return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} ГБ"

    @property
    def age_human(self) -> str:
        delta = time.time() - self.modified
        if delta < 3600:
            return f"{int(delta // 60)} мин назад"
        if delta < 86400:
            return f"{int(delta // 3600)} ч назад"
        return f"{int(delta // 86400)} дн назад"


def _classify(name: str) -> str:
    if name.startswith("bot.log"):
        return "bot"
    if name.startswith("installer"):
        return "installer"
    if name.startswith("doctor"):
        return "doctor"
    return "other"


def directory() -> Path:
    return Path(config.LOG_DIR)


def collect() -> list[LogFile]:
    """Все журналы, новые сверху."""
    root = directory()
    if not root.exists():
        return []
    found: list[LogFile] = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        if not any(pattern.match(path.name) for pattern in PATTERNS):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found.append(LogFile(path, _classify(path.name), stat.st_size, stat.st_mtime))
    return sorted(found, key=lambda item: item.modified, reverse=True)


def by_kind() -> dict[str, list[LogFile]]:
    grouped: dict[str, list[LogFile]] = {}
    for item in collect():
        grouped.setdefault(item.kind, []).append(item)
    return grouped


def find(name: str) -> LogFile | None:
    """Ищет журнал по имени. Имя проверяется, чтобы нельзя было выйти из каталога."""
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    return next((item for item in collect() if item.name == name), None)


def tail(item: LogFile, lines: int = 60) -> str:
    """Последние строки журнала — для быстрого просмотра прямо в чате."""
    try:
        with item.path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(handle.readlines()[-lines:])
    except OSError as exc:
        return f"Не удалось прочитать: {exc}"


def read_bytes(item: LogFile, limit_mb: int = 20) -> bytes | None:
    limit = limit_mb * 1024 * 1024
    try:
        with item.path.open("rb") as handle:
            if item.size <= limit:
                return handle.read()
            # Слишком большой файл отдаём хвостом: начало обычно уже неактуально
            handle.seek(item.size - limit)
            return "…[начало файла обрезано]…\n".encode("utf-8") + handle.read()
    except OSError as exc:
        log.warning("Журнал %s не прочитан: %s", item.name, exc)
        return None


def archive(kinds: set[str] | None = None) -> tuple[bytes, str, int] | None:
    """Собирает журналы в tar.gz. Возвращает (данные, имя файла, число файлов)."""
    items = [item for item in collect() if kinds is None or item.kind in kinds]
    if not items:
        return None

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for item in items:
            try:
                bundle.add(item.path, arcname=f"{item.kind}/{item.name}")
            except OSError as exc:
                log.warning("Журнал %s не добавлен: %s", item.name, exc)

        summary = (
            f"Система «Радар» v{config.VERSION}\n"
            f"Собрано: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n"
            f"Файлов: {len(items)}\n\n"
            + "\n".join(f"{item.kind:<10} {item.name:<44} {item.size_human}" for item in items)
        ).encode("utf-8")
        info = tarfile.TarInfo("manifest.txt")
        info.size = len(summary)
        info.mtime = int(time.time())
        bundle.addfile(info, io.BytesIO(summary))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return buffer.getvalue(), f"radar-logs-{config.VERSION}-{stamp}.tar.gz", len(items)


def purge(kinds: set[str] | None = None, keep_current: bool = True) -> tuple[int, int]:
    """Удаляет журналы. Возвращает (сколько удалено, сколько байт освобождено).

    Текущий `bot.log` по умолчанию не трогаем: он открыт на запись, и его
    удаление оставило бы систему без журнала до перезапуска.
    """
    removed = 0
    freed = 0
    for item in collect():
        if kinds is not None and item.kind not in kinds:
            continue
        if keep_current and item.name == "bot.log":
            continue
        try:
            size = item.size
            item.path.unlink()
            removed += 1
            freed += size
        except OSError as exc:
            log.warning("Не удалось удалить %s: %s", item.name, exc)
    if removed:
        log.info("Удалено журналов: %d, освобождено %d КБ", removed, freed // 1024)
    return removed, freed


def purge_old(days: int | None = None) -> int:
    """Чистка по возрасту — вызывается при старте."""
    keep = config.LOG_KEEP_DAYS if days is None else days
    if keep <= 0:
        return 0
    edge = time.time() - keep * 86400
    removed = 0
    for item in collect():
        if item.name == "bot.log" or item.modified >= edge:
            continue
        try:
            item.path.unlink()
            removed += 1
        except OSError:
            pass
    if removed:
        log.info("Удалено журналов старше %d дней: %d", keep, removed)
    return removed


def total_size() -> int:
    return sum(item.size for item in collect())


def ensure_directory() -> None:
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
    except OSError as exc:
        log.warning("Каталог журналов недоступен: %s", exc)
RADAR_FILE_14
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/presets.py"
cat > "radar/presets.py" <<'RADAR_FILE_15'
"""Наборы источников по городам.

Списки — стартовые, не исчерпывающие: каналы переименовываются, закрываются
и мигрируют на другие площадки. Актуальность проверяется командой
`python3 tools/check_sources.py`, которая опрашивает каждый источник
и показывает дату последней публикации.

Важное наблюдение (август 2026): часть государственных ведомств переносит
оперативные сводки в MAX, оставляя в Telegram только ссылки. Публичного
API у MAX нет, поэтому такие источники деградируют до заголовков —
следите за отчётом проверки и заменяйте их городскими СМИ.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class CityPreset:
    key: str
    title: str
    region: str
    channels: list[str] = field(default_factory=list)
    rss: list[str] = field(default_factory=list)
    note: str = ""


# Федеральные источники: полезны всем городам.
FEDERAL = CityPreset(
    key="federal",
    title="Федеральные",
    region="Россия",
    channels=[
        "mchs_official",   # МЧС России
    ],
)

SARATOV = CityPreset(
    key="saratov",
    title="Саратов",
    region="Саратовская область",
    channels=[
        # службы
        "saratovvodokanal", "saratovzhkh", "tplus_saratov", "komgkhsar64",
        "m_u_p_saratovvodostok", "gjisar64", "minstroysaratov",
        # власть
        "saratovmer", "saratovmeriya", "adm_saratov", "sarobl", "busargin_r",
        "rada_saratov", "PavelSurkov_Saratov",
        # районные администрации
        "kir_admin", "len_admin", "admlenin", "okt_admin", "october_admin",
        "frunz_admin", "gagarin_admin", "volzhsky_admin", "zavadm_saratov",
        # МЧС и происшествия
        "mchs_saratov", "chp_saratov", "mysaratov_radar", "saratov_24",
    ],
    rss=[
        "https://www.sarbc.ru/rss",
        "https://www.vzsar.ru/rss",
        "https://nversia.ru/rss",
        "https://sarnovosti.ru/rss",
        "https://saratov.gov.ru/rss",
        "https://saratov24.tv/rss",
        "https://gtrk-saratov.ru/feed",
    ],
    note="Лента fn-volga.ru удалена: издание «Свободные новости» закрылось, "
         "сайт заблокирован.",
)

MOSCOW = CityPreset(
    key="moscow",
    title="Москва",
    region="Москва и область",
    channels=[
        "mchsmsk",        # МЧС Москвы
        "vodamoskvy",     # Вода Москвы / Мосводоканал
        "DtOperativno",   # Дептранс, оперативно
        "mos_sobyanin",   # мэр Москвы
        "mosgorzdrav",    # оперативные сообщения депздрава
    ],
    rss=[
        "https://www.mos.ru/rss/",
        "https://www.mskagency.ru/rss",
    ],
)

SPB = CityPreset(
    key="spb",
    title="Санкт-Петербург",
    region="Санкт-Петербург и Ленобласть",
    channels=[
        "VDKSPB",           # Водоканал Санкт-Петербурга
        "mchspetersburg",   # МЧС Санкт-Петербурга
        "mchs_spb",         # Уведомления МЧС СПб (экстренная информация РСЧС)
        "gov_spb",          # правительство города
        "spb_gorod",        # городские новости
    ],
    rss=[
        "https://www.fontanka.ru/fontanka.rss",
        "https://www.dp.ru/exportnews.xml",
    ],
    note="МЧС Петербурга с весны 2026 публикует полные сводки в MAX, "
         "в Telegram остаются преимущественно ссылки.",
)

KAZAN = CityPreset(
    key="kazan",
    title="Казань",
    region="Татарстан",
    channels=[
        "vodokanalkzn",    # Казанский Водоканал — публикует адреса отключений
        "kzn_official",    # мэрия Казани
        "tatarstansos",    # происшествия в РТ
        "mchs_tatarstan",  # МЧС Татарстана
        "kznonline",       # городской паблик
    ],
    rss=[
        "https://www.business-gazeta.ru/rss",
        "https://inkazan.ru/rss",
    ],
    note="Казанский Водоканал даёт самые подробные адресные списки отключений.",
)

SAMARA = CityPreset(
    key="samara",
    title="Самара",
    region="Самарская область",
    channels=[
        "mchs_samara",     # МЧС Самарской области
        "SamarOblast",     # правительство области
        "chp_samara",      # происшествия, публикует отбои
        "samara_gov",      # администрация Самары
        "rks_samara",      # РКС-Самара, водоснабжение
    ],
    rss=[
        "https://63.ru/rss/",
        "https://volga.news/rss",
    ],
)

ALL: list[CityPreset] = [FEDERAL, SARATOV, MOSCOW, SPB, KAZAN, SAMARA]
BY_KEY = {preset.key: preset for preset in ALL}


def for_city(name: str) -> CityPreset | None:
    """Подбор пресета по названию города (в том числе из DEFAULT_CITY)."""
    needle = (name or "").strip().lower()
    if not needle:
        return None
    for preset in ALL:
        if preset.key == needle or preset.title.lower() == needle:
            return preset
        if needle in preset.title.lower() or preset.title.lower() in needle:
            return preset
    return None


def channels_for(cities: list[str]) -> list[str]:
    result: list[str] = list(FEDERAL.channels)
    for name in cities:
        preset = for_city(name)
        if preset and preset.key != "federal":
            result.extend(preset.channels)
    return list(dict.fromkeys(result))


def rss_for(cities: list[str]) -> list[str]:
    result: list[str] = list(FEDERAL.rss)
    for name in cities:
        preset = for_city(name)
        if preset and preset.key != "federal":
            result.extend(preset.rss)
    return list(dict.fromkeys(result))
RADAR_FILE_15
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/sourcecheck.py"
cat > "radar/sourcecheck.py" <<'RADAR_FILE_16'
"""Проверка доступности источников: Telegram-каналы, RSS-ленты, сообщества VK.

Списки источников устаревают молча: канал переименовали, издание закрылось,
ведомство ушло в другой мессенджер. Бот при этом продолжает работать
и просто получает меньше новостей — без единой строки в журнале.

Модуль используется и ботом (кнопка в панели модератора), и из терминала
(`python3 tools/check_sources.py`).

Почему проверка устроена сложнее, чем «запросить и посмотреть код ответа»:

* `t.me/s/<канал>` отвечает 200 и для несуществующего канала, и для закрытого —
  просто без постов. Судить можно только по наличию блоков сообщений.
* Часть RSS-лент отвечает 403 на запрос без User-Agent.
* Источник может отвечать 200, а последний пост быть годовой давности —
  формально жив, практически бесполезен.
* Запросы идут с паузой: три десятка обращений подряд к одному хосту
  выглядят как перебор.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from . import config

log = logging.getLogger("radar.sourcecheck")

STALE_DAYS = 14          # после скольких дней молчания считаем источник затихшим
REQUEST_TIMEOUT = 20
POLITE_PAUSE = 0.8       # секунд между запросами

ALIVE = "alive"
STALE = "stale"
DEAD = "dead"

ICONS = {ALIVE: "✓", STALE: "!", DEAD: "✗"}


@dataclass
class SourceStatus:
    kind: str                    # tg | rss | vk
    ref: str
    state: str = DEAD
    note: str = ""
    last_post: datetime | None = None
    posts: int = 0
    http_status: int = 0

    @property
    def icon(self) -> str:
        return ICONS.get(self.state, "?")

    @property
    def title(self) -> str:
        if self.kind == "tg":
            return f"@{self.ref}"
        if self.kind == "rss":
            return urlparse(self.ref).netloc or self.ref
        return self.ref

    @property
    def age(self) -> str:
        if self.last_post is None:
            return "—"
        delta = datetime.now(timezone.utc) - self.last_post
        if delta.days < 0:
            return "только что"
        if delta.days == 0:
            hours = delta.seconds // 3600
            return f"{hours} ч назад" if hours else "только что"
        if delta.days == 1:
            return "вчера"
        return f"{delta.days} дн назад"


@dataclass
class CheckReport:
    statuses: list[SourceStatus] = field(default_factory=list)
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def alive(self) -> list[SourceStatus]:
        return [item for item in self.statuses if item.state == ALIVE]

    @property
    def stale(self) -> list[SourceStatus]:
        return [item for item in self.statuses if item.state == STALE]

    @property
    def dead(self) -> list[SourceStatus]:
        return [item for item in self.statuses if item.state == DEAD]

    @property
    def total(self) -> int:
        return len(self.statuses)


def _headers() -> dict[str, str]:
    # Без User-Agent часть лент отвечает 403
    return {"User-Agent": config.USER_AGENT, "Accept-Language": "ru,en;q=0.8"}


def _is_stale(moment: datetime | None) -> bool:
    if moment is None:
        return False
    return (datetime.now(timezone.utc) - moment).days > STALE_DAYS


def _parse_date(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


# --------------------------------------------------------------------------
#  Отдельные виды источников
# --------------------------------------------------------------------------

async def check_channel(session: aiohttp.ClientSession, name: str) -> SourceStatus:
    status = SourceStatus(kind="tg", ref=name)
    try:
        async with session.get(f"https://t.me/s/{name}", allow_redirects=True) as response:
            status.http_status = response.status
            if response.status == 404:
                status.note = "канал не найден"
                return status
            if response.status != 200:
                status.note = f"HTTP {response.status}"
                return status
            page = await response.text()
    except asyncio.TimeoutError:
        status.note = "таймаут"
        return status
    except Exception as exc:  # noqa: BLE001
        status.note = f"{type(exc).__name__}"
        return status

    soup = BeautifulSoup(page, "html.parser")
    posts = soup.find_all("div", class_="tgme_widget_message_text")
    status.posts = len(posts)

    # Код 200 сам по себе ничего не значит: страница отдаётся и для закрытых
    # каналов, и для несуществующих — но без блоков сообщений.
    if not posts:
        if "tgme_page_context" in page or "Preview channel" in page:
            status.note = "закрытый канал или нет публичного превью"
        else:
            status.note = "публикации не найдены"
        return status

    times = soup.find_all("time", attrs={"datetime": True})
    if times:
        try:
            status.last_post = datetime.fromisoformat(
                times[-1]["datetime"].replace("Z", "+00:00")
            )
        except (ValueError, KeyError):
            pass

    tail = " ".join(post.get_text(" ") for post in posts[-5:]).lower()
    if "max.ru" in tail or "перешли в max" in tail:
        status.note = "упоминает переход в MAX"

    if _is_stale(status.last_post):
        status.state = STALE
        status.note = status.note or "давно не обновлялся"
    else:
        status.state = ALIVE
    return status


async def check_feed(session: aiohttp.ClientSession, url: str) -> SourceStatus:
    status = SourceStatus(kind="rss", ref=url)
    try:
        async with session.get(url, allow_redirects=True) as response:
            status.http_status = response.status
            if response.status != 200:
                status.note = f"HTTP {response.status}"
                return status
            body = await response.text()
    except asyncio.TimeoutError:
        status.note = "таймаут"
        return status
    except Exception as exc:  # noqa: BLE001
        status.note = f"{type(exc).__name__}"
        return status

    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError:
        status.note = "ответ не является XML"
        return status

    entries = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    status.posts = len(entries)
    if not entries:
        status.note = "лента пуста"
        return status

    for tag in ("pubDate", "{http://purl.org/dc/elements/1.1/}date",
                "{http://www.w3.org/2005/Atom}updated", "updated"):
        node = entries[0].find(tag)
        if node is not None and node.text:
            status.last_post = _parse_date(node.text)
            break

    if _is_stale(status.last_post):
        status.state = STALE
        status.note = "давно не обновлялась"
    else:
        status.state = ALIVE
    return status


async def check_vk(session: aiohttp.ClientSession, group: str) -> SourceStatus:
    """Заглушка до версии 4.1: полноценная проверка появится вместе с VK API."""
    status = SourceStatus(kind="vk", ref=group)
    status.note = "проверка появится в 4.1"
    status.state = ALIVE
    return status


# --------------------------------------------------------------------------
#  Общий обход
# --------------------------------------------------------------------------

async def check_all(
    channels: list[str],
    feeds: list[str],
    vk_groups: list[str] | None = None,
    *,
    pause: float = POLITE_PAUSE,
    progress=None,
) -> CheckReport:
    """Проверяет все источники по очереди.

    `progress` — необязательная корутина `progress(done, total, current)`:
    бот показывает через неё ход проверки, чтобы ожидание не было немым.
    """
    report = CheckReport()
    total = len(channels) + len(feeds) + len(vk_groups or [])
    done = 0

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout, headers=_headers()) as session:
        for name in channels:
            report.statuses.append(await check_channel(session, name))
            done += 1
            if progress:
                await progress(done, total, f"@{name}")
            await asyncio.sleep(pause)

        for url in feeds:
            report.statuses.append(await check_feed(session, url))
            done += 1
            if progress:
                await progress(done, total, urlparse(url).netloc or url)
            await asyncio.sleep(pause)

        for group in vk_groups or []:
            report.statuses.append(await check_vk(session, group))
            done += 1
            if progress:
                await progress(done, total, group)

    log.info(
        "Проверка источников: живых %d, затихших %d, недоступных %d из %d",
        len(report.alive), len(report.stale), len(report.dead), report.total,
    )
    return report


def render(report: CheckReport, limit: int = 40) -> str:
    """HTML-сводка для сообщения в боте."""
    from .textutils import esc

    lines = [
        "🔍 <b>Проверка источников</b>",
        f"Живых: <b>{len(report.alive)}</b> · "
        f"затихших: <b>{len(report.stale)}</b> · "
        f"недоступных: <b>{len(report.dead)}</b> из {report.total}",
    ]

    if report.dead:
        lines.append("")
        lines.append("✗ <b>Недоступны</b> — стоит убрать или заменить:")
        for item in report.dead[:limit]:
            lines.append(f"• {esc(item.title)} — {esc(item.note)}")

    if report.stale:
        lines.append("")
        lines.append(f"! <b>Молчат более {STALE_DAYS} дней:</b>")
        for item in report.stale[:limit]:
            lines.append(f"• {esc(item.title)} — {esc(item.age)}")

    if not report.dead and not report.stale:
        lines.append("")
        lines.append("Все источники отвечают и обновляются.")

    return "\n".join(lines)
RADAR_FILE_16
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/sos.py"
cat > "radar/sos.py" <<'RADAR_FILE_17'
"""Экстренная кнопка: отправка геопозиции доверенному контакту.

Устройство и ограничение платформы
----------------------------------
Telegram не позволяет боту написать первым тому, кто с ним не общался.
Поэтому доверенный контакт не может быть просто «номером из записной книжки»:
он должен один раз открыть бота по пригласительной ссылке. До этого момента
контакт числится неподтверждённым, и при тревоге бот честно об этом
предупреждает, а сообщение уходит запасному адресату — администраторам.

Что отправляется
----------------
Имя и ссылка на отправителя, координаты, разобранный адрес, время и карта.
Координаты дублируются отдельным сообщением-геопозицией: его удобно открыть
в навигаторе одним касанием.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .textutils import esc

log = logging.getLogger("radar.sos")

# Сколько минут повторять тревогу, пока не нажато «Я в порядке»
REPEAT_MINUTES = 10
MAX_REPEATS = 6
MAX_CONTACTS = 3


@dataclass
class Contact:
    """Доверенный контакт пользователя."""

    key: str                 # ключ рабочего набора: telegram-id или max:<id>
    title: str               # как показывать в списке
    confirmed: bool = False  # нажал ли контакт «Старт» у бота
    invite: str = ""         # одноразовый код приглашения
    added: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Contact":
        return cls(
            key=str(data.get("key") or ""),
            title=str(data.get("title") or data.get("key") or "контакт"),
            confirmed=bool(data.get("confirmed")),
            invite=str(data.get("invite") or ""),
            added=int(data.get("added") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "confirmed": self.confirmed,
            "invite": self.invite,
            "added": self.added,
        }


def contacts_of(user: dict[str, Any]) -> list[Contact]:
    return [Contact.from_dict(item) for item in (user.get("sos_contacts") or [])]


def store_contacts(user: dict[str, Any], contacts: list[Contact]) -> None:
    user["sos_contacts"] = [item.to_dict() for item in contacts]


def add_contact(user: dict[str, Any], key: str, title: str) -> tuple[Contact | None, str]:
    """Добавляет контакт. Возвращает (контакт, сообщение об ошибке)."""
    contacts = contacts_of(user)
    if len(contacts) >= MAX_CONTACTS:
        return None, f"Больше {MAX_CONTACTS} контактов не поддерживается."
    if any(item.key == key for item in contacts):
        return None, "Такой контакт уже добавлен."

    contact = Contact(
        key=key,
        title=title or key,
        confirmed=False,
        invite=secrets.token_urlsafe(9),
        added=int(time.time()),
    )
    contacts.append(contact)
    store_contacts(user, contacts)
    return contact, ""


def remove_contact(user: dict[str, Any], key: str) -> bool:
    contacts = contacts_of(user)
    kept = [item for item in contacts if item.key != key]
    if len(kept) == len(contacts):
        return False
    store_contacts(user, kept)
    return True


def confirm_by_invite(user: dict[str, Any], invite: str, key: str) -> Contact | None:
    """Отмечает контакт подтверждённым, когда он открыл бота по ссылке."""
    contacts = contacts_of(user)
    for contact in contacts:
        if contact.invite and contact.invite == invite:
            contact.confirmed = True
            contact.key = key or contact.key
            store_contacts(user, contacts)
            return contact
    return None


def find_by_invite(users: dict[str, dict[str, Any]], invite: str) -> tuple[str, Contact] | None:
    """Ищет, кому принадлежит пригласительный код."""
    for owner, data in users.items():
        for contact in contacts_of(data):
            if contact.invite and contact.invite == invite:
                return owner, contact
    return None


def confirmed_contacts(user: dict[str, Any]) -> list[Contact]:
    return [item for item in contacts_of(user) if item.confirmed]


# --------------------------------------------------------------------------
#  Сообщения
# --------------------------------------------------------------------------

def map_link(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat:.6f},{lon:.6f}"


def build_alert(
    sender_name: str,
    sender_link: str,
    lat: float,
    lon: float,
    address: str = "",
    note: str = "",
    repeat: int = 0,
) -> str:
    """Сообщение доверенному контакту."""
    lines = [
        "🆘 <b>ПРОСЬБА О ПОМОЩИ</b>",
        "",
        f"<b>{esc(sender_name)}</b> нажал кнопку SOS в системе «Радар»"
        + (f" — {esc(sender_link)}" if sender_link else ""),
    ]
    if note:
        lines.append(f"\n💬 <i>{esc(note)}</i>")

    lines.append("")
    lines.append(f"📍 <b>Координаты:</b> <code>{lat:.6f}, {lon:.6f}</code>")
    if address:
        lines.append(f"🏠 <b>Адрес:</b> {esc(address)}")
    lines.append(f"🕒 <b>Время:</b> {datetime.now():%H:%M:%S, %d.%m.%Y}")
    lines.append("")
    lines.append(f'🗺 <a href="{map_link(lat, lon)}">Открыть на карте</a>')

    if repeat:
        lines.append("")
        lines.append(
            f"<i>Повтор {repeat}: отправитель ещё не отметил, что с ним всё в порядке.</i>"
        )

    lines.append("")
    lines.append("<b>Если человек в опасности — звоните 112.</b>")
    return "\n".join(lines)


def build_receipt(contacts: list[Contact], failed: list[str]) -> str:
    """Подтверждение отправителю: кому ушло, кому нет."""
    lines = ["🆘 <b>Сигнал отправлен</b>", ""]
    delivered = [item for item in contacts if item.title not in failed]
    if delivered:
        lines.append("Получили:")
        lines += [f"• {esc(item.title)}" for item in delivered]
    if failed:
        lines.append("")
        lines.append("⚠️ Не доставлено:")
        lines += [f"• {esc(name)}" for name in failed]
        lines.append("<i>Контакт не открывал бота или заблокировал его.</i>")

    lines.append("")
    lines.append(
        f"Сигнал будет повторяться каждые {REPEAT_MINUTES} мин "
        f"(до {MAX_REPEATS} раз), пока вы не нажмёте «Я в порядке»."
    )
    lines.append("")
    lines.append("<b>При угрозе жизни звоните 112 — бот не заменяет экстренные службы.</b>")
    return "\n".join(lines)


def build_invite_text(owner_name: str, bot_username: str, invite: str) -> str:
    """Текст приглашения, который отправитель пересылает контакту."""
    return (
        "🆘 <b>Приглашение стать доверенным контактом</b>\n\n"
        f"{esc(owner_name)} указал вас как человека, которому придёт сигнал "
        "о помощи с координатами, если он нажмёт кнопку SOS.\n\n"
        "Чтобы сигнал доходил, откройте бота по ссылке и нажмите «Старт» — "
        "иначе Telegram не позволит боту написать вам первым:\n"
        f"https://t.me/{bot_username}?start=sos_{invite}\n\n"
        "<i>Никаких других сообщений бот присылать не будет.</i>"
    )


def build_cancel_notice(sender_name: str) -> str:
    return (
        f"✅ <b>Отбой</b>\n\n{esc(sender_name)} отметил, что всё в порядке. "
        "Повторные сигналы прекращены."
    )


# --------------------------------------------------------------------------
#  Активные тревоги
# --------------------------------------------------------------------------

@dataclass
class ActiveAlert:
    owner: str
    lat: float
    lon: float
    address: str
    note: str
    started: float
    repeats: int = 0
    last_sent: float = 0.0

    def due(self, now: float | None = None) -> bool:
        moment = now if now is not None else time.time()
        if self.repeats >= MAX_REPEATS:
            return False
        return moment - self.last_sent >= REPEAT_MINUTES * 60


_active: dict[str, ActiveAlert] = {}


def start_alert(owner: str, lat: float, lon: float, address: str, note: str) -> ActiveAlert:
    alert = ActiveAlert(
        owner=owner, lat=lat, lon=lon, address=address, note=note,
        started=time.time(), last_sent=time.time(),
    )
    _active[owner] = alert
    return alert


def stop_alert(owner: str) -> bool:
    return _active.pop(owner, None) is not None


def active_alert(owner: str) -> ActiveAlert | None:
    return _active.get(owner)


def due_alerts(now: float | None = None) -> list[ActiveAlert]:
    return [alert for alert in _active.values() if alert.due(now)]


def active_count() -> int:
    return len(_active)
RADAR_FILE_17
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/__init__.py"
cat > "radar/db/__init__.py" <<'RADAR_FILE_18'
"""Слой базы данных: модели, подключение, репозиторий."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from .engine import (
    check_schema_compatible,
    create_schema,
    ensure_schema,
    dispose,
    get_engine,
    session,
    session_factory,
    stamp_alembic,
    wait_ready,
)
from .models import Base, Delivery, Event, Feature, Location, Meta, Source, User

# Внимание: здесь нельзя экспортировать имена `engine`, `models`, `repo`,
# `importer` — они совпадают с именами подмодулей пакета и затенили бы их
# при `from radar.db import engine`.
__all__ = [
    "Base", "Delivery", "Event", "Feature", "Location", "Meta", "Source", "User",
    "create_schema", "dispose", "get_engine", "session", "session_factory",
    "stamp_alembic", "wait_ready",
]
RADAR_FILE_18
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/models.py"
cat > "radar/db/models.py" <<'RADAR_FILE_19'
"""Схема базы данных.

Перенос с JSON-хранилища версий 3.x: структура повторяет прежние сущности,
чтобы миграция была однозначной, но добавляет то, чего в файле быть не могло —
историю событий и доставок, а также журнал источников.

Идентификатор пользователя — это Telegram ID, поэтому первичный ключ задаётся
явно и не генерируется базой.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Один и тот же столбец: JSONB в PostgreSQL, обычный JSON в SQLite.
# Благодаря with_variant модели остаются едиными для обеих баз.
JSONType = JSON().with_variant(JSONB(), "postgresql")

# SQLite подставляет значение автоинкремента только для INTEGER PRIMARY KEY.
# BIGINT для него — обычный тип без связи с rowid, поэтому вставка падала
# с «NOT NULL constraint failed: users.id». В PostgreSQL нужен именно
# BigInteger: телеграмные идентификаторы не помещаются в 32 бита.
BigIntType = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Базовый класс моделей."""

    type_annotation_map = {dict[str, Any]: JSONType, list[str]: JSONType}


class User(Base):
    """Пользователь любой платформы.

    Ключ суррогатный, а не Telegram ID: с версии 4.2 бот работает сразу
    в двух мессенджерах, и один и тот же числовой идентификатор может
    принадлежать разным людям в Telegram и MAX. Пара (platform, external_id)
    уникальна и служит естественным ключом.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntType, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), default="telegram", index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    weather_mode: Mapped[str] = mapped_column(String(16), default="interval")
    weather_interval: Mapped[int] = mapped_column(Integer, default=0)
    weather_time: Mapped[str] = mapped_column(String(8), default="08:00")
    weather_format: Mapped[str] = mapped_column(String(8), default="text")  # text | image
    last_weather: Mapped[int] = mapped_column(BigIntType, default=0)
    last_fixed_date: Mapped[str] = mapped_column(String(16), default="")

    # Задел под 4.1: тихие часы и антиспам.
    quiet_from: Mapped[str] = mapped_column(String(8), default="")
    quiet_to: Mapped[str] = mapped_column(String(8), default="")

    # Доверенные контакты для кнопки SOS: список словарей, см. radar/sos.py
    sos_contacts: Mapped[list[str]] = mapped_column(JSONType, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    locations: Mapped[list["Location"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_user_identity"),
    )


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[int] = mapped_column(
        BigIntType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lon: Mapped[float] = mapped_column(Float, default=0.0)
    street: Mapped[str] = mapped_column(String(160), default="")
    house: Mapped[str] = mapped_column(String(32), default="")
    city: Mapped[str] = mapped_column(String(120), default="", index=True)
    district: Mapped[str] = mapped_column(String(120), default="")
    region: Mapped[str] = mapped_column(String(120), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    added_by: Mapped[int] = mapped_column(BigIntType, default=0)  # кто добавил, 0 — сам

    user: Mapped[User] = relationship(back_populates="locations")

    __table_args__ = (UniqueConstraint("user_id", "public_id", name="uq_location_public"),)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), default="tg")  # tg | rss | vk
    ref: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    added_by: Mapped[int] = mapped_column(BigIntType, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    fail_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("kind", "ref", name="uq_source_ref"),)


class Event(Base):
    """Разобранное сообщение источника. Основа истории по адресу."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    digest: Mapped[str] = mapped_column(String(40), unique=True, index=True)

    source: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(8), default="tg")
    link: Mapped[str] = mapped_column(Text, default="")

    categories: Mapped[list[str]] = mapped_column(JSONType, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    scope: Mapped[str] = mapped_column(String(16), default="city")
    all_clear: Mapped[bool] = mapped_column(Boolean, default=False)

    city: Mapped[str] = mapped_column(String(120), default="", index=True)
    region: Mapped[str] = mapped_column(String(120), default="")
    districts: Mapped[list[str]] = mapped_column(JSONType, default=list)
    streets: Mapped[dict[str, Any]] = mapped_column(JSONType, default=list)

    summary: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(16), default="ai")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    __table_args__ = (Index("ix_events_city_created", "city", "created_at"),)


class Delivery(Base):
    """Кому и по какой локации событие было отправлено.

    Нужна для истории «что приходило по этому адресу» и для антиспама:
    повторную отправку того же события той же локации легко отсечь.
    """

    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigIntType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("locations.id", ondelete="SET NULL"), default=None
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    delivered: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("event_id", "user_id", "location_id", name="uq_delivery"),
    )


class Feature(Base):
    """Переключатели возможностей, доступные суперадминистратору в боте.

    Значение по умолчанию задаётся в коде, а запись в этой таблице его
    переопределяет — так функцию можно включить или выключить без обновления
    версии и без перезапуска контейнера.
    """

    __tablename__ = "features"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    changed_by: Mapped[int] = mapped_column(BigIntType, default=0)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Meta(Base):
    """Служебные пары ключ-значение: версия анонса, флаги миграций."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
RADAR_FILE_19
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/engine.py"
cat > "radar/db/engine.py" <<'RADAR_FILE_20'
"""Подключение к PostgreSQL: движок, фабрика сессий, ожидание готовности базы.

Функция называется `get_engine`, а не `engine`, намеренно: имя `engine`
занято самим модулем `radar.db.engine`, и экспорт одноимённой функции
из `radar/db/__init__.py` затенял бы модуль. Тогда `from radar.db import
engine` возвращал бы функцию, а обращение к `engine.wait_ready()` падало бы
с AttributeError уже в рантайме.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .. import config

log = logging.getLogger("radar.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        url = config.database_url()
        if config.is_sqlite():
            # У SQLite нет сетевого пула: соединение одно, поэтому pool_size
            # неприменим. WAL и увеличенный таймаут снимают блокировки при
            # одновременной записи из фонового цикла и обработчиков.
            _engine = create_async_engine(
                url,
                echo=config.DB_ECHO,
                connect_args={"timeout": 30},
            )

            @event.listens_for(_engine.sync_engine, "connect")
            def _tune_sqlite(dbapi_connection, _record):  # noqa: ANN001
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA cache_size=-8000")   # 8 МБ, экономно
                cursor.close()
        else:
            _engine = create_async_engine(
                url,
                echo=config.DB_ECHO,
                pool_size=config.DB_POOL_SIZE,
                max_overflow=config.DB_MAX_OVERFLOW,
                pool_pre_ping=True,
                pool_recycle=1800,
            )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """Сессия с автоматическим commit и откатом при ошибке."""
    factory = session_factory()
    async with factory() as active:
        try:
            yield active
            await active.commit()
        except Exception:
            await active.rollback()
            raise


class AuthenticationError(RuntimeError):
    """Пароль не подошёл — ждать бессмысленно, нужно вмешательство."""


def _is_auth_error(exc: BaseException) -> bool:
    """Отличает «пароль не тот» от «база ещё не поднялась».

    Различие принципиально: во втором случае надо ждать, в первом ожидание
    бесполезно — PostgreSQL запоминает пароль при первой инициализации тома,
    и правка .env на уже созданную базу ничего не меняет.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "invalidpassword", "password authentication failed",
        "invalidauthorizationspecification", "role \"", "не пройдена проверка подлинности",
        "authentication failed", "invalidcatalogname", "does not exist",
    )
    return any(marker in text for marker in markers)


async def wait_ready(attempts: int = 30, delay: float = 2.0) -> None:
    """Ждёт, пока PostgreSQL примет подключение.

    На слабом железе контейнер базы поднимается дольше бота, поэтому без
    ожидания первый запуск падал бы на ровном месте. Но причина неудачи
    печатается в лог: молчаливое ожидание не даёт понять, база не успела
    подняться или пароль не подошёл.
    """
    from sqlalchemy import text

    if config.is_sqlite():
        # Файловая база готова сразу: ждать нечего.
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        log.info("База SQLite готова: %s", config.DB_FILE)
        return

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
            if attempt > 1:
                log.info("База ответила с попытки %d", attempt)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            reason = f"{type(exc).__name__}: {exc}"

            if _is_auth_error(exc):
                log.critical("PostgreSQL отклонил подключение: %s", reason)
                log.critical(
                    "Пароль в .env не совпадает с тем, который база запомнила "
                    "при первом запуске. PostgreSQL задаёт пароль только при "
                    "инициализации тома — правка .env на существующую базу "
                    "ничего не меняет."
                )
                log.critical(
                    "Решение: либо верните прежний пароль в .env, либо пересоздайте "
                    "базу — docker compose down && rm -rf data/postgres — "
                    "и запустите установщик заново. Данные из data/db.json "
                    "перенесутся повторно."
                )
                raise AuthenticationError(reason) from exc

            if attempt == 1:
                log.info("Жду готовности PostgreSQL… (%s)", reason[:160])
            elif attempt % 5 == 0:
                log.info("Попытка %d/%d: %s", attempt, attempts, reason[:160])
            await asyncio.sleep(delay)

    log.critical("PostgreSQL не ответил за %.0f секунд", attempts * delay)
    raise RuntimeError(f"PostgreSQL недоступен: {last}")


async def create_schema() -> tuple[bool, int]:
    """Создаёт недостающие таблицы напрямую из моделей.

    Почему не Alembic при старте: его `command.upgrade` синхронный, и запуск
    из рабочего потока приводил к вложенному `asyncio.run()` поверх уже
    работающего цикла событий. На ARM это зависало наглухо — контейнер
    перезапускался по кругу, не оставляя даже трассировки.

    `create_all` идемпотентен: существующие таблицы не трогает. Alembic
    остаётся для настоящих изменений схемы и запускается отдельной командой,
    а не на каждом старте.

    Возвращает (создавалось ли что-то, сколько таблиц в базе).
    """
    from sqlalchemy import inspect

    from .models import Base

    async with get_engine().begin() as connection:
        before = await connection.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        await connection.run_sync(Base.metadata.create_all)
        after = await connection.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )

    created = sorted(after - before)
    if created:
        log.info("Созданы таблицы: %s", ", ".join(created))
    return bool(created), len(after)


async def ensure_schema() -> tuple[bool, int, bool]:
    """Создаёт схему и чинит её, если она осталась от версии с ошибкой.

    Возвращает (создавалось ли что-то, число таблиц, была ли починка).
    """
    created, tables = await create_schema()

    compatible, reason = await check_schema_compatible()
    if compatible:
        return created, tables, False

    log.warning("Обнаружена несовместимая схема: %s", reason)
    await repair_schema()
    _created, tables = await create_schema()
    return created, tables, True


async def _sqlite_pk_type(connection, table: str, column: str) -> str:
    """Объявленный тип столбца в SQLite — из PRAGMA table_info."""
    from sqlalchemy import text

    result = await connection.execute(text(f"PRAGMA table_info({table})"))
    for row in result:
        if row[1] == column:
            return str(row[2] or "").upper()
    return ""


async def check_schema_compatible() -> tuple[bool, str]:
    """Совместима ли существующая схема с текущими моделями.

    Нужно потому, что `create_all` только досоздаёт недостающие таблицы
    и никогда не меняет существующие. База, созданная версией с ошибкой
    в типе первичного ключа, так и осталась бы нерабочей: таблицы на месте,
    а вставка падает.
    """
    from sqlalchemy import inspect, text

    if not config.is_sqlite():
        return True, ""

    async with get_engine().connect() as connection:
        tables = await connection.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        if "users" not in tables:
            return True, ""

        pk_type = await _sqlite_pk_type(connection, "users", "id")
        if pk_type and pk_type != "INTEGER":
            return False, (
                f"первичный ключ users.id объявлен как {pk_type}; "
                "SQLite подставляет автоинкремент только для INTEGER"
            )

        for table, column in (("locations", "user_id"), ("deliveries", "user_id")):
            if table not in tables:
                continue
            column_type = await _sqlite_pk_type(connection, table, column)
            if column_type and column_type != "INTEGER":
                return False, f"тип {table}.{column} = {column_type}, ожидается INTEGER"

    return True, ""


async def repair_schema() -> dict[str, int]:
    """Пересоздаёт схему, сохраняя данные.

    Содержимое читается обычными запросами — чтение из «сломанной» схемы
    работает, падает только вставка, — затем таблицы создаются заново
    и данные возвращаются на место. История событий не переносится:
    она восстановима из источников и не стоит усложнения.
    """
    from sqlalchemy import select

    from .models import Base, Feature, Location, Meta, Source, User

    users: list[dict] = []
    locations: list[dict] = []
    sources: list[dict] = []
    features: list[dict] = []
    meta: list[dict] = []

    async with session() as active:
        for row in (await active.scalars(select(User))).all():
            users.append({
                "old_id": row.id,
                "platform": row.platform, "external_id": row.external_id,
                "role": row.role, "username": row.username,
                "settings": row.settings or {},
                "weather_mode": row.weather_mode, "weather_interval": row.weather_interval,
                "weather_time": row.weather_time, "weather_format": row.weather_format,
                "last_weather": row.last_weather, "last_fixed_date": row.last_fixed_date,
                "quiet_from": row.quiet_from, "quiet_to": row.quiet_to,
            })
        for row in (await active.scalars(select(Location))).all():
            locations.append({
                "old_user_id": row.user_id,
                "public_id": row.public_id, "name": row.name,
                "lat": row.lat, "lon": row.lon, "street": row.street, "house": row.house,
                "city": row.city, "district": row.district, "region": row.region,
                "added_by": row.added_by,
            })
        for row in (await active.scalars(select(Source))).all():
            sources.append({
                "kind": row.kind, "ref": row.ref, "title": row.title, "city": row.city,
                "enabled": row.enabled, "pending": row.pending, "added_by": row.added_by,
            })
        for row in (await active.scalars(select(Feature))).all():
            features.append({"key": row.key, "enabled": row.enabled,
                             "changed_by": row.changed_by})
        for row in (await active.scalars(select(Meta))).all():
            meta.append({"key": row.key, "value": row.value})

    log.warning(
        "Схема несовместима — пересоздаю. Сохранено: пользователей %d, "
        "локаций %d, источников %d",
        len(users), len(locations), len(sources),
    )

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    restored_locations = 0
    async with session() as active:
        # Старый идентификатор → новый: связь локаций с владельцами
        # восстанавливается именно по нему, а не по порядку строк.
        id_map: dict[int, int] = {}
        for item in users:
            old_id = item.pop("old_id")
            row = User(**item)
            active.add(row)
            await active.flush()
            id_map[old_id] = row.id

        for item in locations:
            old_user = item.pop("old_user_id")
            new_user = id_map.get(old_user)
            if new_user is None:
                log.warning("Локация «%s» пропущена: владелец не найден", item.get("name"))
                continue
            active.add(Location(user_id=new_user, **item))
            restored_locations += 1

        for item in sources:
            active.add(Source(**item))
        for item in features:
            active.add(Feature(**item))
        for item in meta:
            active.add(Meta(**item))

    log.info(
        "Схема пересоздана: пользователей %d, локаций %d, источников %d",
        len(users), restored_locations, len(sources),
    )
    return {
        "users": len(users),
        "locations": restored_locations,
        "sources": len(sources),
        "features": len(features),
        "meta": len(meta),
    }


async def stamp_alembic(revision: str = "0001_initial") -> None:
    """Отмечает версию схемы, чтобы будущие миграции знали точку отсчёта."""
    from sqlalchemy import text

    try:
        async with get_engine().begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version ("
                    "version_num VARCHAR(32) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
            current = await connection.execute(text("SELECT version_num FROM alembic_version"))
            if current.first() is None:
                await connection.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                    {"rev": revision},
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось отметить версию схемы: %s", exc)


async def dispose() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
RADAR_FILE_20
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/repo.py"
cat > "radar/db/repo.py" <<'RADAR_FILE_21'
"""Репозиторий: чтение и запись данных в PostgreSQL.

Стратегия
---------
Пользователи и локации при старте загружаются в память и остаются рабочим
набором — обработчики продолжают обращаться к обычным словарям, как в 3.x,
а изменения пишутся сквозь в базу. Это оставляет диффы прежних модулей
минимальными и держит отклик интерфейса мгновенным.

Ограничение честное: подход рассчитан на тысячи пользователей, не на сотни
тысяч. Когда объём вырастет, `save_user` уже пишет точечно, и переход
на выборку по запросу сведётся к замене чтений из кэша на запросы к базе.

События и доставки в память не грузятся никогда: они только пишутся
и читаются точечными запросами.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, func, select

from .. import config
from ..matching import CATEGORY_TITLES
from ..roles import SUPERADMIN, USER
from .engine import session
from ..identity import parse as parse_identity
from .models import Delivery, Event, Feature, Location, Meta, Source, User

log = logging.getLogger("radar.repo")


# --------------------------------------------------------------------------
#  Значения по умолчанию (совместимы с 3.x)
# --------------------------------------------------------------------------

def default_settings() -> dict[str, bool]:
    return {key: True for key in CATEGORY_TITLES}


def default_user(role: str = USER, username: str = "") -> dict[str, Any]:
    return {
        "role": role,
        "username": username,
        "locs": [],
        "settings": default_settings(),
        "weather_mode": "interval",
        "weather_interval": 0,
        "weather_time": "08:00",
        "weather_format": "text",
        "last_weather": 0,
        "last_fixed_date": "",
        "quiet_from": "",
        "quiet_to": "",
        "sos_contacts": [],
        "created": int(datetime.now(timezone.utc).timestamp()),
    }


def new_location(name: str, lat: float, lon: float, **extra: Any) -> dict[str, Any]:
    location = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "city": "",
        "district": "",
        "region": "",
        "street": "",
        "house": "",
        "added_by": 0,
    }
    location.update({key: value for key, value in extra.items() if value is not None})
    return location


# --------------------------------------------------------------------------
#  Преобразование модель ↔ словарь
# --------------------------------------------------------------------------

def location_to_dict(row: Location) -> dict[str, Any]:
    return {
        "id": row.public_id,
        "name": row.name,
        "lat": row.lat,
        "lon": row.lon,
        "street": row.street,
        "house": row.house,
        "city": row.city,
        "district": row.district,
        "region": row.region,
        "added_by": row.added_by,
    }


def user_to_dict(row: User) -> dict[str, Any]:
    settings = dict(row.settings or {})
    for key in CATEGORY_TITLES:
        settings.setdefault(key, True)
    return {
        "role": row.role,
        "username": row.username or "",
        "locs": [location_to_dict(item) for item in row.locations],
        "settings": settings,
        "weather_mode": row.weather_mode,
        "weather_interval": row.weather_interval,
        "weather_time": row.weather_time,
        "weather_format": row.weather_format,
        "last_weather": row.last_weather,
        "last_fixed_date": row.last_fixed_date,
        "quiet_from": row.quiet_from,
        "quiet_to": row.quiet_to,
        "sos_contacts": list(row.sos_contacts or []),
        "created": int(row.created_at.timestamp()) if row.created_at else 0,
    }


# --------------------------------------------------------------------------
#  Пользователи
# --------------------------------------------------------------------------

async def load_users() -> dict[str, dict[str, Any]]:
    from ..identity import make as make_identity

    async with session() as active:
        rows = (await active.scalars(select(User))).all()
        return {
            make_identity(row.platform, row.external_id).key: user_to_dict(row)
            for row in rows
        }


async def _find_user(active, key: str | int) -> User | None:
    identity = parse_identity(key)
    return await active.scalar(
        select(User).where(
            User.platform == identity.platform,
            User.external_id == identity.external_id,
        )
    )


async def save_user(uid: str | int, data: dict[str, Any]) -> None:
    """Сохраняет пользователя целиком вместе с локациями."""
    identity = parse_identity(uid)
    async with session() as active:
        row = await _find_user(active, uid)
        if row is None:
            row = User(platform=identity.platform, external_id=identity.external_id)
            active.add(row)

        row.role = data.get("role", USER)
        row.username = (data.get("username") or "")[:64]
        row.settings = dict(data.get("settings") or default_settings())
        row.weather_mode = data.get("weather_mode", "interval")
        row.weather_interval = int(data.get("weather_interval") or 0)
        row.weather_time = data.get("weather_time", "08:00")
        row.weather_format = data.get("weather_format", "text")
        row.last_weather = int(data.get("last_weather") or 0)
        row.last_fixed_date = data.get("last_fixed_date", "")
        row.quiet_from = data.get("quiet_from", "")
        row.quiet_to = data.get("quiet_to", "")
        row.sos_contacts = list(data.get("sos_contacts") or [])
        row.seen_at = datetime.now(timezone.utc)

        await active.flush()
        user_id = row.id

        # Локации читаем запросом, а не через row.locations: обращение
        # к отношению у уже сохранённого объекта запускает ленивую подгрузку,
        # а она в async-контексте падает с MissingGreenlet.
        current = (
            await active.scalars(select(Location).where(Location.user_id == user_id))
        ).all()
        existing = {item.public_id: item for item in current}
        wanted = {item["id"]: item for item in (data.get("locs") or [])}

        for public_id, item in wanted.items():
            target = existing.get(public_id)
            if target is None:
                target = Location(public_id=public_id, user_id=user_id)
                active.add(target)
            target.name = str(item.get("name") or "")[:200]
            target.lat = float(item.get("lat") or 0.0)
            target.lon = float(item.get("lon") or 0.0)
            target.street = str(item.get("street") or "")[:160]
            target.house = str(item.get("house") or "")[:32]
            target.city = str(item.get("city") or "")[:120]
            target.district = str(item.get("district") or "")[:120]
            target.region = str(item.get("region") or "")[:120]
            target.added_by = int(item.get("added_by") or 0)

        for public_id, target in existing.items():
            if public_id not in wanted:
                await active.delete(target)


async def delete_user(uid: str | int) -> None:
    async with session() as active:
        row = await _find_user(active, uid)
        if row is not None:
            await active.delete(row)


async def internal_id(uid: str | int) -> int | None:
    """Суррогатный идентификатор пользователя — нужен для связей."""
    async with session() as active:
        row = await _find_user(active, uid)
        return int(row.id) if row is not None else None


async def save_users(users: dict[str, dict[str, Any]]) -> None:
    for uid, data in users.items():
        await save_user(uid, data)


# --------------------------------------------------------------------------
#  Источники
# --------------------------------------------------------------------------

async def load_sources() -> tuple[list[str], list[str], list[str], list[str]]:
    """Возвращает (telegram, rss, vk, очередь модерации)."""
    async with session() as active:
        rows = (await active.scalars(select(Source))).all()
    channels = [row.ref for row in rows if row.kind == "tg" and row.enabled and not row.pending]
    feeds = [row.ref for row in rows if row.kind == "rss" and row.enabled and not row.pending]
    vk = [row.ref for row in rows if row.kind == "vk" and row.enabled and not row.pending]
    pending = [row.ref for row in rows if row.pending]
    return channels, feeds, vk, pending


async def upsert_source(
    kind: str, ref: str, *, pending: bool = False, added_by: int = 0, city: str = ""
) -> None:
    # Без диалектного ON CONFLICT: одинаково работает в SQLite и PostgreSQL.
    async with session() as active:
        row = await active.scalar(
            select(Source).where(Source.kind == kind, Source.ref == ref)
        )
        if row is None:
            active.add(
                Source(kind=kind, ref=ref, pending=pending, added_by=added_by, city=city)
            )
        else:
            row.pending = pending
            row.enabled = True


async def remove_source(kind: str, ref: str) -> None:
    async with session() as active:
        await active.execute(delete(Source).where(Source.kind == kind, Source.ref == ref))


async def sync_sources(
    channels: Sequence[str], feeds: Sequence[str], vk: Sequence[str], pending: Sequence[str]
) -> None:
    """Приводит таблицу источников в соответствие со списками в памяти."""
    async with session() as active:
        rows = (await active.scalars(select(Source))).all()
        current = {(row.kind, row.ref): row for row in rows}

        wanted: dict[tuple[str, str], bool] = {}
        for ref in channels:
            wanted[("tg", ref)] = False
        for ref in feeds:
            wanted[("rss", ref)] = False
        for ref in vk:
            wanted[("vk", ref)] = False
        for ref in pending:
            wanted.setdefault(("tg", ref), True)

        for key, is_pending in wanted.items():
            row = current.get(key)
            if row is None:
                active.add(Source(kind=key[0], ref=key[1], pending=is_pending))
            else:
                row.pending = is_pending
                row.enabled = True

        for key, row in current.items():
            if key not in wanted:
                await active.delete(row)


async def mark_source(kind: str, ref: str, *, error: str = "") -> None:
    """Отмечает результат опроса источника — для отчёта о мёртвых каналах."""
    async with session() as active:
        row = await active.scalar(
            select(Source).where(Source.kind == kind, Source.ref == ref)
        )
        if row is None:
            return
        if error:
            row.fail_count += 1
            row.last_error = error[:300]
        else:
            row.fail_count = 0
            row.last_error = ""
            row.last_seen = datetime.now(timezone.utc)


async def broken_sources(threshold: int = 5) -> list[Source]:
    async with session() as active:
        return list(
            (await active.scalars(
                select(Source).where(Source.fail_count >= threshold)
            )).all()
        )


# --------------------------------------------------------------------------
#  События и доставки
# --------------------------------------------------------------------------

def event_digest(source: str, raw: str) -> str:
    return hashlib.sha1(f"{source}\n{raw}".encode("utf-8")).hexdigest()


async def store_event(analysis: Any) -> int | None:
    """Сохраняет разобранное событие, возвращает его id.

    Повторное сохранение того же текста не создаёт дубликат: сработает
    уникальный индекс по digest и вернётся существующая запись.
    """
    if not getattr(analysis, "relevant", False):
        return None

    digest = event_digest(analysis.source, analysis.raw or analysis.summary)
    async with session() as active:
        existing = await active.scalar(select(Event.id).where(Event.digest == digest))
        if existing:
            return int(existing)
        row = Event(
            digest=digest,
            source=(analysis.source or "")[:200],
            kind="rss" if analysis.link else "tg",
            link=analysis.link or "",
            categories=list(analysis.categories),
            severity=analysis.severity,
            scope=analysis.scope,
            all_clear=bool(analysis.all_clear),
            city=(analysis.city or "")[:120],
            region=(analysis.region or "")[:120],
            districts=list(analysis.districts),
            streets=list(analysis.streets),
            summary=analysis.summary or "",
            raw=(analysis.raw or "")[:8000],
            engine=analysis.engine,
        )
        active.add(row)
        await active.flush()
        return int(row.id)


async def record_delivery(
    event_id: int, user_id: int | str, location_public_id: str | None
) -> bool:
    """Отмечает доставку. False — событие этой локации уже отправляли."""
    async with session() as active:
        row = await _find_user(active, user_id)
        if row is None:
            return False
        location_id = None
        if location_public_id:
            location_id = await active.scalar(
                select(Location.id).where(
                    Location.user_id == row.id,
                    Location.public_id == location_public_id,
                )
            )
        existing = await active.scalar(
            select(Delivery.id).where(
                Delivery.event_id == event_id,
                Delivery.user_id == row.id,
                Delivery.location_id == location_id,
            )
        )
        if existing is not None:
            return False
        active.add(
            Delivery(
                event_id=event_id,
                user_id=row.id,
                location_id=location_id,
                sent_at=datetime.now(timezone.utc),
            )
        )
        return True


async def was_delivered(event_id: int, user_id: int | str, location_public_id: str | None) -> bool:
    async with session() as active:
        row = await _find_user(active, user_id)
        if row is None:
            return False
        location_id = None
        if location_public_id:
            location_id = await active.scalar(
                select(Location.id).where(
                    Location.user_id == row.id,
                    Location.public_id == location_public_id,
                )
            )
        found = await active.scalar(
            select(Delivery.id).where(
                Delivery.event_id == event_id,
                Delivery.user_id == row.id,
                Delivery.location_id == location_id,
            )
        )
        return found is not None


async def history(
    user_id: int | str,
    location_public_id: str | None = None,
    *,
    days: int = 30,
    limit: int = 20,
    categories: Iterable[str] | None = None,
) -> list[Event]:
    """История событий, приходивших пользователю (опционально по одной локации)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with session() as active:
        row = await _find_user(active, user_id)
        if row is None:
            return []
        query = (
            select(Event)
            .join(Delivery, Delivery.event_id == Event.id)
            .where(Delivery.user_id == row.id, Delivery.sent_at >= since)
            .order_by(Event.created_at.desc())
            .limit(limit)
        )
        if location_public_id:
            location_id = await active.scalar(
                select(Location.id).where(
                    Location.user_id == row.id,
                    Location.public_id == location_public_id,
                )
            )
            query = query.where(Delivery.location_id == location_id)
        rows = (await active.scalars(query)).all()

    wanted = set(categories or [])
    if wanted:
        rows = [row for row in rows if wanted & set(row.categories or [])]
    return list(rows)


async def event_stats(days: int = 30) -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with session() as active:
        events = await active.scalar(
            select(func.count(Event.id)).where(Event.created_at >= since)
        )
        deliveries = await active.scalar(
            select(func.count(Delivery.id)).where(Delivery.sent_at >= since)
        )
    return {"events": int(events or 0), "deliveries": int(deliveries or 0)}


async def purge_old_events(days: int | None = None) -> int:
    """Чистка истории. Возвращает число удалённых событий."""
    keep = config.EVENT_RETENTION_DAYS if days is None else days
    if keep <= 0:
        return 0
    edge = datetime.now(timezone.utc) - timedelta(days=keep)
    async with session() as active:
        result = await active.execute(delete(Event).where(Event.created_at < edge))
        return int(result.rowcount or 0)


# --------------------------------------------------------------------------
#  Служебные значения
# --------------------------------------------------------------------------

async def get_meta(key: str, default: Any = None) -> Any:
    async with session() as active:
        row = await active.get(Meta, key)
        return row.value if row is not None else default


async def set_meta(key: str, value: Any) -> None:
    async with session() as active:
        row = await active.get(Meta, key)
        if row is None:
            active.add(Meta(key=key, value=value))
        else:
            row.value = value


# --------------------------------------------------------------------------
#  Переключатели возможностей
# --------------------------------------------------------------------------

async def load_features() -> dict[str, bool]:
    async with session() as active:
        rows = (await active.scalars(select(Feature))).all()
        return {row.key: bool(row.enabled) for row in rows}


async def set_feature(key: str, enabled_value: bool, changed_by: int | str = 0) -> None:
    identity = parse_identity(changed_by) if changed_by else None
    actor = 0
    if identity is not None and identity.external_id.isdigit():
        actor = int(identity.external_id)
    async with session() as active:
        row = await active.get(Feature, key)
        if row is None:
            active.add(Feature(key=key, enabled=enabled_value, changed_by=actor))
        else:
            row.enabled = enabled_value
            row.changed_by = actor
RADAR_FILE_21
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/importer.py"
cat > "radar/db/importer.py" <<'RADAR_FILE_22'
"""Импорт данных из JSON-хранилища версии 3.x в PostgreSQL.

Запускается автоматически при первом старте 4.x, если база пуста, а файл
`data/db.json` на месте. Исходный файл не удаляется, а переименовывается
в `db.json.migrated` — путь назад остаётся.

Поддерживается только формат 3.x. Базы версий 2.x напрямую не читаются:
сначала обновитесь до 3.3.5, дайте боту один раз запуститься — он приведёт
файл к текущему виду, — и только потом переходите на 4.x. Промежуточный
шаг занимает минуту и избавляет импортёр от ветвлений, которые невозможно
проверить на живых данных.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .. import config, presets
from ..matching import CATEGORY_TITLES
from ..roles import SUPERADMIN, USER
from . import repo

log = logging.getLogger("radar.import")

MARKER = "json_import"


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Приводит структуру версии 3.x к виду репозитория."""
    users: dict[str, dict[str, Any]] = {}
    raw_users = raw.get("users")
    if not isinstance(raw_users, dict):
        raw_users = {}
    for uid, item in raw_users.items():
        if not isinstance(item, dict):
            continue
        record = repo.default_user(item.get("role", USER), item.get("username", ""))
        for key in (
            "weather_mode", "weather_interval", "weather_time",
            "last_weather", "last_fixed_date", "weather_format",
        ):
            if item.get(key) is not None:
                record[key] = item[key]

        settings = item.get("settings")
        if isinstance(settings, dict):
            record["settings"] = {
                key: bool(settings.get(key, True)) for key in CATEGORY_TITLES
            }

        locations: list[dict[str, Any]] = []
        raw_locs = item.get("locs")
        if not isinstance(raw_locs, (list, tuple)):
            raw_locs = []
        for entry in raw_locs:
            if not isinstance(entry, dict) or not entry.get("name"):
                # Строки вместо объектов — формат 2.x, он больше не поддерживается.
                if isinstance(entry, str):
                    log.warning(
                        "Локация «%s» в формате 2.x пропущена: обновитесь сначала до 3.3.5",
                        entry[:60],
                    )
                continue
            location = repo.new_location(
                str(entry["name"]),
                float(entry.get("lat") or 0.0),
                float(entry.get("lon") or 0.0),
            )
            for key in ("city", "district", "region", "street", "house"):
                if entry.get(key):
                    location[key] = str(entry[key])
            if entry.get("id"):
                location["id"] = str(entry["id"])[:16]
            locations.append(location)
        record["locs"] = locations
        users[str(uid)] = record

    superadmin = str(config.SUPERADMIN_ID)
    if superadmin not in users:
        users[superadmin] = repo.default_user(SUPERADMIN)
        users[superadmin]["weather_interval"] = 60
    else:
        users[superadmin]["role"] = SUPERADMIN

    def as_list(value: Any) -> list[str]:
        """Терпимо читает список: в повреждённом файле там может быть что угодно."""
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if item]
        return []

    channels = as_list(raw.get("channels"))
    feeds = as_list(raw.get("rss"))
    vk = as_list(raw.get("vk"))
    pending = as_list(raw.get("pending"))

    cities = config.SOURCE_CITIES or ([config.DEFAULT_CITY] if config.DEFAULT_CITY else [])
    for name in presets.channels_for(cities):
        if name not in channels:
            channels.append(name)
    for url in presets.rss_for(cities):
        if url not in feeds:
            feeds.append(url)

    return {
        "users": users,
        "channels": channels,
        "rss": feeds,
        "vk": vk,
        "pending": pending,
        "meta": raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
    }


async def is_empty() -> bool:
    users = await repo.load_users()
    return not users


async def run(path: str | None = None) -> dict[str, int]:
    """Переносит JSON в базу. Возвращает счётчики перенесённого."""
    source = path or config.DATA_FILE
    raw: dict[str, Any] = {}

    if os.path.exists(source):
        try:
            with open(source, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            raw = loaded if isinstance(loaded, dict) else {}
            log.info("Найден файл прежней версии: %s", source)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Файл %s не прочитан (%s) — начинаю с пустой базы", source, exc)
            raw = {}
    else:
        log.info("Файла %s нет — создаю базу с нуля", source)

    data = _normalize(raw)

    await repo.save_users(data["users"])
    await repo.sync_sources(data["channels"], data["rss"], data["vk"], data["pending"])

    for key, value in (data["meta"] or {}).items():
        await repo.set_meta(str(key), value if isinstance(value, (dict, list)) else {"value": value})

    counters = {
        "users": len(data["users"]),
        "locations": sum(len(item["locs"]) for item in data["users"].values()),
        "channels": len(data["channels"]),
        "rss": len(data["rss"]),
        "pending": len(data["pending"]),
    }
    await repo.set_meta(MARKER, {"done": True, **counters})

    if os.path.exists(source):
        backup = f"{source}.migrated"
        try:
            os.replace(source, backup)
            log.info("Исходный файл сохранён как %s", backup)
        except OSError as exc:
            log.warning("Не удалось переименовать %s: %s", source, exc)

    log.info(
        "Перенос завершён: пользователей %d, локаций %d, каналов %d, лент %d",
        counters["users"], counters["locations"], counters["channels"], counters["rss"],
    )
    return counters
RADAR_FILE_22
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/doctor.py"
cat > "radar/doctor.py" <<'RADAR_FILE_23'
#!/usr/bin/env python3
"""Проверка готовности системы до запуска бота.

Запускается внутри контейнера, где установлены все зависимости, и проверяет
то, что нельзя проверить снаружи: конфигурацию, подключение к базе, создание
схемы, запись и чтение данных, разбор старого `db.json`, доступность Telegram.

Смысл в том, чтобы ошибка обнаруживалась один раз и с понятным объяснением,
а не превращалась в цикл перезапусков контейнера.

    python -m radar.doctor            # полная проверка
    python -m radar.doctor --quick    # без обращений к сети
    python -m radar.doctor --json     # машиночитаемый отчёт
    python -m radar.doctor --stream   # с метками прогресса для установщика

Модуль лежит внутри пакета, а не в tools/, намеренно: tools исключён
из контекста сборки образа, и попытка скопировать оттуда файл ломала build.

Код возврата: 0 — всё в порядке, 1 — есть ошибки, 2 — только предупреждения.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK = "ok"
WARN = "warn"
ERROR = "error"

MARKS = {OK: "✓", WARN: "!", ERROR: "✗"}


@dataclass
class Result:
    name: str
    status: str
    message: str = ""
    hint: str = ""
    detail: str = ""


@dataclass
class Report:
    checks: list[Result] = field(default_factory=list)

    def add(self, name: str, status: str, message: str = "", hint: str = "", detail: str = "") -> None:
        self.checks.append(Result(name, status, message, hint, detail))

    @property
    def errors(self) -> list[Result]:
        return [item for item in self.checks if item.status == ERROR]

    @property
    def warnings(self) -> list[Result]:
        return [item for item in self.checks if item.status == WARN]

    def code(self) -> int:
        if self.errors:
            return 1
        return 2 if self.warnings else 0


report = Report()

# Порядок и подписи проверок: установщик показывает по ним шкалу.
STAGES = (
    ("imports", "зависимости"),
    ("resources", "память и диск"),
    ("config", "конфигурация"),
    ("database", "подключение к базе"),
    ("schema", "схема и запись данных"),
    ("import_file", "данные прежней версии"),
    ("telegram", "доступ к Telegram"),
)

STREAM = False
_stage_index = 0


def announce(key: str) -> None:
    """Сообщает установщику, какая проверка началась.

    Метка машиночитаемая: установщик по ней рисует шкалу, а человек
    в обычном режиме её не видит.
    """
    global _stage_index
    if not STREAM:
        return
    titles = dict(STAGES)
    _stage_index += 1
    print(f"##STAGE {_stage_index} {len(STAGES)} {titles.get(key, key)}", flush=True)


# --------------------------------------------------------------------------
#  Проверки
# --------------------------------------------------------------------------

def check_imports() -> bool:
    """Все ли зависимости на месте и импортируются."""
    announce("imports")
    modules = {
        "aiogram": "Telegram-клиент",
        "aiohttp": "HTTP-клиент",
        "sqlalchemy": "работа с базой",
        "bs4": "разбор веб-страниц",
        "dotenv": "чтение .env",
    }
    missing: list[str] = []
    for name, purpose in modules.items():
        try:
            __import__(name)
        except ImportError as exc:
            missing.append(f"{name} ({purpose}): {exc}")

    if missing:
        report.add(
            "Зависимости", ERROR,
            f"не установлены: {len(missing)}",
            "Пересоберите образ: docker compose build --no-cache",
            "\n".join(missing),
        )
        return False
    report.add("Зависимости", OK, f"проверено модулей: {len(modules)}")
    return True


def check_config() -> bool:
    """Обязательные параметры и типичные ошибки в них."""
    announce("config")
    try:
        from radar import config
    except Exception as exc:  # noqa: BLE001
        report.add("Конфигурация", ERROR, str(exc),
                   "Проверьте .env и переменные окружения", traceback.format_exc())
        return False

    problems: list[str] = []
    if not config.BOT_TOKEN:
        problems.append("BOT_TOKEN не задан")
    elif ":" not in config.BOT_TOKEN:
        problems.append("BOT_TOKEN не похож на токен (нет двоеточия)")
    if not config.SUPERADMIN_ID:
        problems.append("SUPERADMIN_ID не задан или равен нулю")

    if problems:
        report.add("Конфигурация", ERROR, "; ".join(problems),
                   "Откройте .env и заполните недостающее")
        return False

    backend = "SQLite" if config.is_sqlite() else "PostgreSQL"
    report.add("Конфигурация", OK, f"версия {config.VERSION}, база {backend}")

    if not config.GEMINI_API_KEY:
        report.add("Ключ Gemini", WARN, "не задан",
                   "Бот будет работать на эвристическом разборе без ИИ")
    else:
        report.add("Ключ Gemini", OK, "задан")
    return True


async def check_database() -> bool:
    """Подключение, создание схемы и полный цикл записи-чтения."""
    announce("database")
    from radar import config
    from radar.db import engine as db_engine

    try:
        await db_engine.wait_ready(attempts=15, delay=2.0)
    except Exception as exc:  # noqa: BLE001
        hint = (
            "Проверьте DB_FILE и права на каталог data/"
            if config.is_sqlite()
            else "Проверьте, что контейнер radar_db поднят, и совпадает ли DB_PASSWORD"
        )
        report.add("Подключение к базе", ERROR, str(exc)[:200], hint, traceback.format_exc())
        return False
    report.add("Подключение к базе", OK, config.database_url().split("@")[-1][:60])

    try:
        created, tables, repaired = await db_engine.ensure_schema()
        await db_engine.stamp_alembic()
    except Exception as exc:  # noqa: BLE001
        report.add("Схема базы", ERROR, str(exc)[:200],
                   "Возможна несовместимость версии базы", traceback.format_exc())
        return False

    if repaired:
        report.add("Схема базы", WARN,
                   f"была несовместима и пересоздана, таблиц: {tables}",
                   "Данные пользователей сохранены, история событий очищена")
    else:
        report.add("Схема базы", OK,
                   f"{'создана' if created else 'актуальна'}, таблиц: {tables}")

    # Полный цикл: запись, чтение, удаление. Именно здесь всплывали ошибки
    # ленивой подгрузки, которых не видно при простом подключении.
    announce("schema")
    from radar.db import repo

    probe_id = "doctor:0"
    try:
        sample = repo.default_user("user", "doctor")
        sample["locs"] = [repo.new_location("Проверочная улица, 1", 51.5, 46.0, city="Тест")]
        await repo.save_user(probe_id, sample)

        loaded = await repo.load_users()
        if probe_id not in loaded:
            raise RuntimeError("записанный пользователь не читается обратно")
        if len(loaded[probe_id]["locs"]) != 1:
            raise RuntimeError("локация не сохранилась")

        sample["locs"] = []
        await repo.save_user(probe_id, sample)          # проверка удаления локаций
        await repo.set_feature("history", True, 0)      # проверка таблицы флагов
        await repo.set_meta("doctor", {"value": "ok"})  # проверка служебной таблицы
    except Exception as exc:  # noqa: BLE001
        report.add("Запись и чтение", ERROR, str(exc)[:200],
                   "Схема или модели несовместимы с базой", traceback.format_exc())
        return False
    finally:
        try:
            await repo.delete_user(probe_id)
        except Exception:  # noqa: BLE001
            pass

    report.add("Запись и чтение", OK, "полный цикл пройден")
    return True


async def check_import_file() -> None:
    """Читается ли файл прежней версии, если он есть."""
    announce("import_file")
    from radar import config
    from radar.db import importer

    path = config.DATA_FILE
    if not os.path.exists(path):
        report.add("Данные прежней версии", OK, "файла нет, начинаем с чистой базы")
        return

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        data = importer._normalize(raw if isinstance(raw, dict) else {})
    except Exception as exc:  # noqa: BLE001
        report.add("Данные прежней версии", ERROR, str(exc)[:200],
                   f"Файл {path} повреждён; переименуйте его, чтобы начать с нуля",
                   traceback.format_exc())
        return

    users = len(data["users"])
    locations = sum(len(item["locs"]) for item in data["users"].values())
    report.add("Данные прежней версии", OK,
               f"готово к переносу: пользователей {users}, локаций {locations}, "
               f"источников {len(data['channels'])}")


async def check_telegram() -> None:
    """Принимает ли Telegram наш токен."""
    announce("telegram")
    import aiohttp

    from radar import config

    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getMe"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.get(url) as response:
                payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        report.add("Telegram", WARN, f"сеть недоступна: {exc}",
                   "Проверьте подключение или настройте выход через прокси")
        return

    if payload.get("ok"):
        name = (payload.get("result") or {}).get("username", "?")
        report.add("Telegram", OK, f"токен принят, бот @{name}")
    else:
        report.add("Telegram", ERROR,
                   str(payload.get("description", "неизвестная ошибка"))[:160],
                   "Проверьте BOT_TOKEN в .env — возможно, он отозван")


def check_resources() -> None:
    """Хватит ли памяти и места."""
    announce("resources")
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            info = {
                line.split(":")[0]: int(line.split()[1])
                for line in handle if ":" in line
            }
        total = info.get("MemTotal", 0) // 1024
        available = info.get("MemAvailable", 0) // 1024
        if available < 150:
            report.add("Память", ERROR, f"доступно {available} МБ из {total} МБ",
                       "Освободите память или добавьте файл подкачки")
        elif available < 300:
            report.add("Память", WARN, f"доступно {available} МБ из {total} МБ",
                       "Работать будет, но без запаса")
        else:
            report.add("Память", OK, f"доступно {available} МБ из {total} МБ")
    except Exception:  # noqa: BLE001
        pass

    try:
        stat = os.statvfs("/app/data")
        free = stat.f_bavail * stat.f_frsize // (1024 * 1024)
        if free < 200:
            report.add("Диск", ERROR, f"свободно {free} МБ", "Освободите место")
        else:
            report.add("Диск", OK, f"свободно {free} МБ")
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
#  Запуск
# --------------------------------------------------------------------------

async def run(quick: bool) -> None:
    if not check_imports():
        return
    check_resources()
    if not check_config():
        return
    if not await check_database():
        return
    await check_import_file()
    if not quick:
        await check_telegram()

    from radar.db import engine as db_engine

    await db_engine.dispose()


def render(as_json: bool) -> None:
    if as_json:
        print(json.dumps([asdict(item) for item in report.checks],
                         ensure_ascii=False, indent=2))
        return

    print()
    for item in report.checks:
        print(f"  {MARKS[item.status]} {item.name}: {item.message}")
        if item.hint and item.status != OK:
            print(f"      → {item.hint}")

    print()
    if report.errors:
        print(f"  Ошибок: {len(report.errors)}, предупреждений: {len(report.warnings)}")
        print("\n  Подробности:")
        for item in report.errors:
            print(f"\n  ── {item.name} ──")
            print(f"  {item.message}")
            if item.detail:
                tail = item.detail.strip().splitlines()[-6:]
                for line in tail:
                    print(f"    {line}")
    elif report.warnings:
        print(f"  Всё работает, предупреждений: {len(report.warnings)}")
    else:
        print("  Все проверки пройдены")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Диагностика системы «Радар»")
    parser.add_argument("--quick", action="store_true", help="без обращений к сети")
    parser.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    parser.add_argument("--stream", action="store_true",
                        help="печатать метки прогресса для установщика")
    args = parser.parse_args()

    global STREAM
    STREAM = args.stream

    try:
        asyncio.run(run(args.quick))
    except Exception as exc:  # noqa: BLE001
        report.add("Диагностика", ERROR, str(exc)[:200],
                   "Непредвиденная ошибка проверки", traceback.format_exc())

    render(args.json)
    return report.code()


if __name__ == "__main__":
    sys.exit(main())
RADAR_FILE_23
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "migrations/env.py"
cat > "migrations/env.py" <<'RADAR_FILE_24'
"""Окружение Alembic: берёт строку подключения из конфигурации проекта."""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import config as app_config  # noqa: E402
from radar.db.models import Base  # noqa: E402

alembic_config = context.config
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

alembic_config.set_main_option("sqlalchemy.url", app_config.database_url())
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(
        url=app_config.database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online_async() -> None:
    engine = async_engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online_async())
RADAR_FILE_24
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "migrations/script.py.mako"
cat > "migrations/script.py.mako" <<'RADAR_FILE_25'
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
RADAR_FILE_25
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "migrations/versions/0001_initial.py"
cat > "migrations/versions/0001_initial.py" <<'RADAR_FILE_26'
"""Начальная схема версии 4.0

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False, server_default="telegram"),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("username", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("weather_mode", sa.String(length=16), nullable=False, server_default="interval"),
        sa.Column("weather_interval", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weather_time", sa.String(length=8), nullable=False, server_default="08:00"),
        sa.Column("weather_format", sa.String(length=8), nullable=False, server_default="text"),
        sa.Column("last_weather", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_fixed_date", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("quiet_from", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("quiet_to", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_user_identity"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_platform", "users", ["platform"])
    op.create_index("ix_users_external_id", "users", ["external_id"])

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False, server_default="0"),
        sa.Column("lon", sa.Float(), nullable=False, server_default="0"),
        sa.Column("street", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("house", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("district", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("region", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("added_by", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "public_id", name="uq_location_public"),
    )
    op.create_index("ix_locations_user_id", "locations", ["user_id"])
    op.create_index("ix_locations_public_id", "locations", ["public_id"])
    op.create_index("ix_locations_city", "locations", ["city"])

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="tg"),
        sa.Column("ref", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("added_by", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "ref", name="uq_source_ref"),
    )
    op.create_index("ix_sources_pending", "sources", ["pending"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("digest", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="tg"),
        sa.Column("link", sa.Text(), nullable=False, server_default=""),
        sa.Column("categories", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="city"),
        sa.Column("all_clear", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("region", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("districts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("streets", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("engine", sa.String(length=16), nullable=False, server_default="ai"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("digest"),
    )
    op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_index("ix_events_city", "events", ["city"])
    op.create_index("ix_events_city_created", "events", ["city", "created_at"])

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", "location_id", name="uq_delivery"),
    )
    op.create_index("ix_deliveries_event_id", "deliveries", ["event_id"])
    op.create_index("ix_deliveries_user_id", "deliveries", ["user_id"])
    op.create_index("ix_deliveries_sent_at", "deliveries", ["sent_at"])

    op.create_table(
        "features",
        sa.Column("key", sa.String(length=48), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("changed_by", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "meta",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("meta")
    op.drop_table("features")
    op.drop_table("deliveries")
    op.drop_table("events")
    op.drop_table("sources")
    op.drop_table("locations")
    op.drop_table("users")
RADAR_FILE_26
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/platforms/__init__.py"
cat > "radar/platforms/__init__.py" <<'RADAR_FILE_27'
"""Адаптеры мессенджеров: единый формат событий поверх разных API."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from .base import (
    Button,
    EventKind,
    InboundEvent,
    Keyboard,
    OutboundMessage,
    Transport,
)

__all__ = [
    "Button", "EventKind", "InboundEvent", "Keyboard", "OutboundMessage", "Transport",
]
RADAR_FILE_27
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/platforms/base.py"
cat > "radar/platforms/base.py" <<'RADAR_FILE_28'
"""Единый формат событий и ответов, общий для всех мессенджеров.

Ядро системы — разбор новостей, сопоставление с локациями, роли, погода —
не должно знать, откуда пришло сообщение. Адаптер каждой платформы приводит
входящее событие к `InboundEvent`, а исходящий ответ `OutboundMessage`
переводит в вызовы своего API.

Соответствие понятий, из-за которого абстракция и нужна:

| Понятие          | Telegram (aiogram)      | MAX Bot API              |
|------------------|-------------------------|--------------------------|
| Чат              | message.chat.id (int)   | chat_id (str/int)        |
| Текст            | message.text            | message.text             |
| Кнопки           | InlineKeyboardMarkup    | массив массивов keyboard |
| Данные кнопки    | callback_data           | payload                  |
| Событие          | Update                  | update с полем type      |
| Разметка         | HTML / MarkdownV2       | ограниченная, см. адаптер|
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence

from ..identity import Identity


class EventKind(str, Enum):
    MESSAGE = "message"      # обычное текстовое сообщение
    COMMAND = "command"      # сообщение, начинающееся со слэша
    CALLBACK = "callback"    # нажатие кнопки
    LOCATION = "location"    # геопозиция
    DOCUMENT = "document"    # присланный файл
    JOINED = "joined"        # бот добавлен в чат
    OTHER = "other"


@dataclass
class InboundEvent:
    """Входящее событие в платформенно-независимом виде."""

    platform: str
    identity: Identity
    chat_id: str
    kind: EventKind = EventKind.OTHER
    text: str = ""
    command: str = ""
    args: str = ""
    payload: str = ""                 # данные нажатой кнопки
    latitude: float | None = None
    longitude: float | None = None
    document_name: str = ""
    document_size: int = 0
    username: str = ""
    message_id: str = ""
    raw: Any = None                   # исходный объект платформы

    @property
    def key(self) -> str:
        return self.identity.key


@dataclass
class Button:
    """Кнопка, не привязанная к платформе."""

    text: str
    payload: str = ""     # для callback-кнопок
    url: str = ""         # для кнопок-ссылок

    @property
    def is_link(self) -> bool:
        return bool(self.url)


Keyboard = Sequence[Sequence[Button]]


@dataclass
class OutboundMessage:
    """Ответ бота в платформенно-независимом виде."""

    text: str = ""
    keyboard: Keyboard = field(default_factory=list)
    persistent: Keyboard = field(default_factory=list)  # закреплённые кнопки
    image: bytes | None = None
    image_name: str = "image.png"
    document: bytes | None = None
    document_name: str = "file.bin"
    edit: bool = False                # заменить предыдущее сообщение
    disable_preview: bool = True
    silent: bool = False              # без звука: тихие часы


class Transport(Protocol):
    """Контракт адаптера мессенджера.

    Реализации: `telegram.TelegramTransport` (4.0) и `max.MaxTransport` (4.2).
    Новый мессенджер добавляется реализацией этого протокола — ядро не меняется.
    """

    name: str

    async def start(self) -> None:
        """Подключиться и начать получать события."""

    async def stop(self) -> None:
        """Корректно завершить работу."""

    async def send(self, chat_id: str, message: OutboundMessage) -> bool:
        """Отправить сообщение. False — доставить не удалось."""

    async def set_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        """Установить список команд в интерфейсе мессенджера."""

    def render(self, text: str) -> str:
        """Привести общую HTML-разметку к возможностям платформы."""
RADAR_FILE_28
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/storage.py"
cat > "radar/storage.py" <<'RADAR_FILE_29'
"""Рабочий набор данных: словари в памяти поверх PostgreSQL.

Обработчики работают с обычными словарями, как в версиях 3.x, — сигнатуры
функций сохранены намеренно, чтобы переход на базу не потребовал правки
интерфейсных модулей. Изменения пишутся сквозь: `save()` отправляет в базу
только тех пользователей, кто действительно менялся.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .db import repo
from .roles import USER

log = logging.getLogger("radar.storage")

DB: dict[str, Any] = {"users": {}, "channels": [], "rss": [], "vk": [], "pending": [], "meta": {}}

_lock = asyncio.Lock()
# Снимки состояния: позволяют сохранять только реально изменившихся
# пользователей, не требуя от обработчиков помечать изменения вручную.
_snapshots: dict[str, str] = {}
_sources_snapshot: str = ""


def _fingerprint(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)

# Прежние имена сохранены: на них ссылаются обработчики и тесты.
default_settings = repo.default_settings
default_user = repo.default_user
new_location = repo.new_location


# --------------------------------------------------------------------------
#  Загрузка и сохранение
# --------------------------------------------------------------------------

async def load() -> None:
    """Читает всё содержимое базы в память."""
    global _sources_snapshot
    users = await repo.load_users()
    channels, feeds, vk, pending = await repo.load_sources()

    DB["users"] = users
    DB["channels"] = channels
    DB["rss"] = feeds
    DB["vk"] = vk
    DB["pending"] = pending
    DB["meta"] = {}
    _snapshots.clear()
    _snapshots.update({uid: _fingerprint(data) for uid, data in users.items()})
    _sources_snapshot = _fingerprint([channels, feeds, vk, pending])

    log.info(
        "Загружено: пользователей %d, каналов %d, лент %d, VK %d",
        len(users), len(channels), len(feeds), len(vk),
    )


async def save(uid: str | int | None = None) -> None:
    """Пишет в базу то, что изменилось с прошлого сохранения.

    Без аргумента проверяет всех пользователей и списки источников;
    с аргументом — только указанного пользователя. Сравнение идёт
    по снимку в памяти, поэтому обработчикам не нужно ничего помечать.
    """
    global _sources_snapshot
    async with _lock:
        if uid is not None:
            key = str(uid)
            data = DB["users"].get(key)
            if data is not None:
                mark = _fingerprint(data)
                if _snapshots.get(key) != mark:
                    await repo.save_user(key, data)
                    _snapshots[key] = mark
            return

        for user_id, data in list(DB["users"].items()):
            mark = _fingerprint(data)
            if _snapshots.get(user_id) != mark:
                await repo.save_user(user_id, data)
                _snapshots[user_id] = mark

        for stale in set(_snapshots) - set(DB["users"]):
            _snapshots.pop(stale, None)

        sources = [DB["channels"], DB["rss"], DB.get("vk", []), DB["pending"]]
        mark = _fingerprint(sources)
        if mark != _sources_snapshot:
            await repo.sync_sources(*sources)
            _sources_snapshot = mark


# --------------------------------------------------------------------------
#  Доступ к данным (сигнатуры из 3.x)
# --------------------------------------------------------------------------

def users() -> dict[str, Any]:
    return DB["users"]


def get_user(uid: int | str) -> dict[str, Any] | None:
    return DB["users"].get(str(uid))


def exists(uid: int | str) -> bool:
    return str(uid) in DB["users"]


def role_of(uid: int | str) -> str | None:
    user = get_user(uid)
    return user.get("role") if user else None


def register(uid: int | str, username: str = "") -> dict[str, Any]:
    user = repo.default_user(USER, username)
    DB["users"][str(uid)] = user
    return user


def find_location(uid: int | str, loc_id: str) -> dict[str, Any] | None:
    user = get_user(uid)
    if not user:
        return None
    for location in user["locs"]:
        if location.get("id") == loc_id:
            return location
    return None


def remove_location(uid: int | str, loc_id: str) -> bool:
    user = get_user(uid)
    if not user:
        return False
    before = len(user["locs"])
    user["locs"] = [item for item in user["locs"] if item.get("id") != loc_id]
    return len(user["locs"]) != before


async def drop_user(uid: int | str) -> None:
    """Полное удаление пользователя вместе с локациями."""
    DB["users"].pop(str(uid), None)
    _snapshots.pop(str(uid), None)
    await repo.delete_user(uid)


def channels() -> list[str]:
    return DB["channels"]


def rss_feeds() -> list[str]:
    return DB["rss"]


def vk_groups() -> list[str]:
    return DB.setdefault("vk", [])


def pending() -> list[str]:
    return DB["pending"]


def meta() -> dict[str, Any]:
    return DB["meta"]


async def meta_get(key: str, default: Any = None) -> Any:
    return await repo.get_meta(key, default)


async def meta_set(key: str, value: Any) -> None:
    await repo.set_meta(key, value)
RADAR_FILE_29
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/exporting.py"
cat > "radar/exporting.py" <<'RADAR_FILE_30'
"""Обмен списками источников: экспорт в файл и импорт обратно.

Формат намеренно простой и версионированный, чтобы файл, выгруженный сегодня,
читался будущими версиями бота. Правила совместимости:

* `schema` — номер формата. Импортёр принимает всё, что не новее известного ему,
  и честно отказывается читать файл из более новой версии.
* Неизвестные поля игнорируются, отсутствующие берутся по умолчанию —
  добавление полей в будущем не ломает старые файлы.
* Принимаются также «сырые» варианты: массив строк, файл `db.json` целиком
  или список каналов текстом — так можно перенести настройки из версий 2.x.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

FORMAT = "radar-sources"
SCHEMA = 1

CHANNEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
URL_RE = re.compile(r"^https?://", re.I)
TELEGRAM_RE = re.compile(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/", re.I)

def is_feed_url(value: str) -> bool:
    """Ссылка на ленту, а не на Telegram-канал."""
    return bool(URL_RE.match(value)) and not TELEGRAM_RE.match(value)


def normalize_channel(raw: str) -> str:
    value = re.sub(r"^(https?://)?(t\.me/|telegram\.me/)?@?", "", (raw or "").strip(), flags=re.I)
    return value.strip("/ ").split("/")[0].split("?")[0]


@dataclass
class Bundle:
    """Разобранный набор источников."""

    channels: list[str] = field(default_factory=list)
    rss: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    origin: str = ""      # версия бота, из которой выгружено
    schema: int = SCHEMA
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.channels) + len(self.rss)


class ImportError_(ValueError):
    """Файл не удалось прочитать."""


def export_bundle(
    channels: list[str], rss: list[str], pending: list[str], version: str
) -> bytes:
    """Собирает файл выгрузки."""
    payload = {
        "format": FORMAT,
        "schema": SCHEMA,
        "generator": f"radar/{version}",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {"channels": len(channels), "rss": len(rss), "pending": len(pending)},
        "channels": sorted(set(channels)),
        "rss": sorted(set(rss)),
        "pending": sorted(set(pending)),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def export_filename(version: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"radar-sources-{version}-{stamp}.json"


def _clean(values: Any, kind: str, warnings: list[str]) -> list[str]:
    result: list[str] = []
    if not isinstance(values, (list, tuple)):
        return result
    for item in values:
        if isinstance(item, dict):  # запас на будущее: {"ref": ..., "type": ...}
            item = item.get("ref") or item.get("url") or item.get("name") or ""
        text = str(item).strip()
        if not text:
            continue
        if kind == "rss":
            if is_feed_url(text):
                result.append(text)
            elif TELEGRAM_RE.match(text):
                warnings.append(
                    f"«{text[:40]}» — Telegram-канал, а не лента: перенесите в channels"
                )
            else:
                warnings.append(f"пропущена лента «{text[:40]}»: не похоже на адрес")
            continue
        channel = normalize_channel(text)
        if CHANNEL_RE.match(channel):
            result.append(channel)
        else:
            warnings.append(f"пропущен канал «{text[:40]}»: некорректный юзернейм")
    # порядок сохраняем, дубликаты убираем
    return list(dict.fromkeys(result))


def parse_bundle(raw: bytes | str) -> Bundle:
    """Читает файл выгрузки, db.json версии 2.x или простой список строк."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ImportError_("файл не в кодировке UTF-8") from exc

    text = raw.strip()
    if not text:
        raise ImportError_("файл пуст")

    warnings: list[str] = []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Не JSON — принимаем простой список каналов текстом.
        parts = [part for part in re.split(r"[,\s\n;]+", text) if part]
        # Ссылка на t.me — это канал, а не лента.
        channels = _clean([p for p in parts if not is_feed_url(p)], "channel", warnings)
        feeds = _clean([p for p in parts if is_feed_url(p)], "rss", warnings)
        if not channels and not feeds:
            raise ImportError_("не найдено ни одного источника")
        return Bundle(channels=channels, rss=feeds, warnings=warnings, origin="текстовый список")

    if isinstance(data, list):
        return Bundle(
            channels=_clean(
                [item for item in data if not is_feed_url(str(item))], "channel", warnings
            ),
            rss=_clean([item for item in data if is_feed_url(str(item))], "rss", warnings),
            warnings=warnings,
            origin="массив",
        )

    if not isinstance(data, dict):
        raise ImportError_("неподдерживаемая структура файла")

    schema = data.get("schema")
    if isinstance(schema, int) and schema > SCHEMA:
        raise ImportError_(
            f"файл формата версии {schema}, а бот понимает до {SCHEMA} — обновите бота"
        )

    if data.get("format") and data.get("format") != FORMAT:
        warnings.append(f"неизвестный формат «{data['format']}», читаю как смогу")

    channels = _clean(data.get("channels"), "channel", warnings)
    rss = _clean(data.get("rss") or data.get("feeds"), "rss", warnings)
    pending = _clean(data.get("pending"), "channel", warnings)

    if not channels and not rss:
        raise ImportError_("в файле нет ни каналов, ни лент")

    return Bundle(
        channels=channels,
        rss=rss,
        pending=pending,
        origin=str(data.get("generator") or "неизвестно"),
        schema=schema if isinstance(schema, int) else 0,
        warnings=warnings,
    )


def merge(
    bundle: Bundle,
    channels: list[str],
    rss: list[str],
    *,
    replace: bool = False,
) -> tuple[int, int]:
    """Вливает набор в текущие списки. Возвращает (добавлено каналов, лент)."""
    if replace:
        channels.clear()
        rss.clear()

    added_channels = 0
    for name in bundle.channels:
        if name not in channels:
            channels.append(name)
            added_channels += 1

    added_rss = 0
    for url in bundle.rss:
        if url not in rss:
            rss.append(url)
            added_rss += 1

    return added_channels, added_rss
RADAR_FILE_30
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/ai.py"
cat > "radar/ai.py" <<'RADAR_FILE_31'
"""Слой Google Gemini: автовыбор модели, совместимость поколений, экономия квоты.

Устойчивость к отключению моделей
---------------------------------
Google выводит модели из обращения быстрее объявленных дат: `gemini-2.5-flash`
закрыт для новых ключей до наступления официальной даты отключения. Поэтому
имя модели не зашито намертво: при старте список кандидатов сверяется с тем,
что реально доступно ключу (`models.list`), а при ответе 404 модель на лету
понижается и берётся следующая из списка.

Различия поколений
------------------
Начиная с Gemini 3.x: `temperature`/`top_p`/`top_k` устарели и игнорируются,
`thinking_budget` заменён строковым `thinking_level`, запрос не должен
заканчиваться ходом роли `model`. Всё это учитывается в `_build_config`.

Экономия квоты
--------------
  1. предфильтр по ключевым словам — заведомо нерелевантное не уходит в модель;
  2. пакетный разбор — до AI_BATCH_SIZE новостей одним запросом;
  3. кэш результатов по хэшу текста — повтор не оплачивается;
  4. учёт RPM/RPD с резервом суточных запросов под живой диалог.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import OrderedDict
from dataclasses import replace
from typing import Any, Sequence

from google import genai
from google.genai import types

from . import config
from .matching import Analysis, heuristic_analysis
from .ratelimit import QuotaExceeded, RateLimiter

log = logging.getLogger("radar.ai")

_client: genai.Client | None = None
if config.AI_ENABLED:
    try:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    except Exception as exc:  # noqa: BLE001
        log.error("Не удалось создать клиент Gemini: %s", exc)
        _client = None

ENABLED = _client is not None
_semaphore = asyncio.Semaphore(config.AI_CONCURRENCY)
limiter = RateLimiter(
    rpm=config.AI_RPM,
    rpd=config.AI_RPD,
    reserve=config.AI_RESERVE,
    cooldown=config.AI_COOLDOWN,
)

# Возможности отключаются автоматически, если SDK или модель их не принимают.
_features = {"thinking": True, "safety": True, "search": config.AI_SEARCH}

ASSISTANT = "assistant"
ANALYSIS = "analysis"

# Порядок предпочтения. Первым идёт значение из .env, если оно задано.
_CANDIDATES: dict[str, list[str]] = {
    ASSISTANT: [
        config.GEMINI_MODEL,
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    ANALYSIS: [
        config.GEMINI_MODEL_ANALYSIS,
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-flash-latest",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    ],
}

def _dedup(names: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for name in names:
        clean = (name or "").strip().removeprefix("models/")
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


_chain: dict[str, list[str]] = {role: _dedup(names) for role, names in _CANDIDATES.items()}
_current: dict[str, str] = {role: chain[0] for role, chain in _chain.items() if chain}
_available: list[str] = []      # что реально видит ключ
_unavailable: set[str] = set()  # модели, ответившие 404


class AIError(RuntimeError):
    """Ошибка обращения к модели с понятным пользователю текстом."""


# --------------------------------------------------------------------------
#  Выбор модели
# --------------------------------------------------------------------------

def is_gen3(model: str) -> bool:
    """Модель поколения 3.x и новее: другой набор параметров запроса."""
    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", model or "")
    return bool(match) and int(match.group(1)) >= 3


def current_model(role: str) -> str:
    return _current.get(role) or config.GEMINI_MODEL


def _demote(role: str, model: str) -> str | None:
    """Помечает модель недоступной и переходит к следующей из цепочки."""
    _unavailable.add(model)
    for candidate in _chain.get(role, []):
        if candidate not in _unavailable:
            _current[role] = candidate
            log.warning("Модель «%s» недоступна — перехожу на «%s»", model, candidate)
            return candidate
    log.error("Ни одна модель из списка не доступна для роли «%s»", role)
    return None


async def discover_models() -> list[str]:
    """Спрашивает у API, какие модели доступны ключу, и подбирает рабочие."""
    global _available
    if not ENABLED:
        return []
    names: list[str] = []
    try:
        pager = await _client.aio.models.list()
        async for item in pager:
            raw = getattr(item, "name", "") or ""
            actions = (
                getattr(item, "supported_actions", None)
                or getattr(item, "supported_generation_methods", None)
                or []
            )
            if actions and not any("generateContent" in str(a) for a in actions):
                continue
            names.append(raw.removeprefix("models/"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось получить список моделей (%s) — работаю по умолчанию", exc)
        return []

    _available = sorted(names)
    log.info("Ключу доступно моделей: %d", len(_available))

    for role, chain in _chain.items():
        picked = next((name for name in chain if name in _available), None)
        if picked:
            if picked != _current.get(role):
                log.info("Модель для роли «%s»: %s", role, picked)
            _current[role] = picked
        else:
            log.warning(
                "Ни один кандидат для роли «%s» не найден среди доступных; оставляю «%s»",
                role, _current.get(role),
            )
    return _available


def models_report() -> dict[str, Any]:
    return {
        "assistant": current_model(ASSISTANT),
        "analysis": current_model(ANALYSIS),
        "available": list(_available),
        "unavailable": sorted(_unavailable),
    }


# --------------------------------------------------------------------------
#  Сборка запроса
# --------------------------------------------------------------------------

def _thinking_config(model: str):
    """Минимальное «мышление»: у 3.x — thinking_level, у 2.5 — thinking_budget."""
    if not _features["thinking"]:
        return None
    try:
        if is_gen3(model):
            return types.ThinkingConfig(thinking_level="minimal")
        return types.ThinkingConfig(thinking_budget=0)
    except Exception as exc:  # noqa: BLE001 — старый SDK не знает поле
        log.warning("ThinkingConfig не поддерживается SDK (%s) — отключаю", exc)
        _features["thinking"] = False
        return None


def _build_config(
    model: str,
    system: str | None,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
    search: bool,
):
    kwargs: dict[str, Any] = {"max_output_tokens": max_tokens}

    # У Gemini 3.x параметры сэмплирования устарели: игнорируются сейчас
    # и вернут 400 в следующих поколениях.
    if not is_gen3(model):
        kwargs["temperature"] = temperature

    if system:
        kwargs["system_instruction"] = system
    if json_mode:
        kwargs["response_mime_type"] = "application/json"

    thinking = _thinking_config(model)
    if thinking is not None:
        kwargs["thinking_config"] = thinking

    if _features["safety"]:
        try:
            kwargs["safety_settings"] = [
                types.SafetySetting(category=category, threshold="BLOCK_ONLY_HIGH")
                for category in (
                    "HARM_CATEGORY_HARASSMENT",
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_DANGEROUS_CONTENT",
                )
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("SafetySetting не поддерживается (%s) — отключаю", exc)
            _features["safety"] = False

    if search and _features["search"] and not json_mode:
        # Поиск несовместим со строгим JSON-режимом, поэтому только для диалога.
        try:
            kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        except Exception as exc:  # noqa: BLE001
            log.warning("Поиск в интернете не поддерживается SDK (%s)", exc)
            _features["search"] = False

    return types.GenerateContentConfig(**kwargs)


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text.strip()
    chunks: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "thought", False):
                continue
            piece = getattr(part, "text", None)
            if piece:
                chunks.append(piece)
    return "\n".join(chunks).strip()


def _finish_reason(response: Any) -> str:
    for candidate in getattr(response, "candidates", None) or []:
        reason = getattr(candidate, "finish_reason", None)
        if reason:
            return str(reason)
    return "UNKNOWN"


def _strip_trailing_model_turn(contents: Any) -> Any:
    """Gemini 3.x отвергает запрос, если последний ход — роли model (400)."""
    if not isinstance(contents, list):
        return contents
    trimmed = list(contents)
    while trimmed and str(getattr(trimmed[-1], "role", "")) == "model":
        trimmed.pop()
    return trimmed


async def generate(
    contents: Any,
    *,
    system: str | None = None,
    json_mode: bool = False,
    max_tokens: int = 2048,
    temperature: float = 0.4,
    retries: int = 3,
    role: str = ASSISTANT,
    priority: bool = True,
    search: bool = False,
) -> str:
    """Запрос к модели с учётом квот и автоподменой недоступной модели.

    priority=True — живой диалог: ждём свободный слот в пределах таймаута.
    priority=False — фоновая задача: при нехватке квоты сразу QuotaExceeded.
    """
    if not ENABLED:
        raise AIError("Gemini недоступен: не задан GEMINI_API_KEY.")

    if priority:
        try:
            await limiter.wait_acquire(priority=True)
        except QuotaExceeded as exc:
            raise AIError(
                f"Квота Gemini исчерпана ({exc}). Суточный лимит бесплатного тарифа "
                "обнуляется в полночь по тихоокеанскому времени — около 10–11 утра по Москве."
            ) from exc
    elif not await limiter.try_acquire(priority=False):
        raise QuotaExceeded("нет свободной квоты для фонового анализа")

    payload = _strip_trailing_model_turn(contents)
    last: AIError | None = None

    for attempt in range(retries):
        model = current_model(role)
        cfg = _build_config(model, system, json_mode, max_tokens, temperature, search)
        try:
            async with _semaphore:
                response = await asyncio.wait_for(
                    _client.aio.models.generate_content(
                        model=model, contents=payload, config=cfg
                    ),
                    timeout=config.AI_TIMEOUT,
                )
        except asyncio.TimeoutError:
            last = AIError(f"Таймаут запроса к Gemini ({config.AI_TIMEOUT} с).")
            await asyncio.sleep(2 * (attempt + 1))
            continue
        except Exception as exc:  # noqa: BLE001 — SDK бросает разнородные типы
            detail = f"{type(exc).__name__}: {exc}"
            low = detail.lower()
            last = AIError(detail)

            # Модель отключена или недоступна ключу — берём следующую из цепочки.
            if "404" in low or "not found" in low or "no longer available" in low:
                replacement = _demote(role, model)
                if replacement:
                    continue
                raise AIError(
                    f"Модель «{model}» недоступна для этого ключа, и запасных не осталось. "
                    "Укажите актуальную модель в GEMINI_MODEL — список доступных: /models"
                ) from exc

            if "thinking" in low and _features["thinking"]:
                _features["thinking"] = False
                log.warning("Отключаю thinking-параметры: %s", detail)
                continue
            if "safety" in low and _features["safety"]:
                _features["safety"] = False
                log.warning("Отключаю safety_settings: %s", detail)
                continue
            if ("tool" in low or "google_search" in low) and _features["search"]:
                _features["search"] = False
                log.warning("Отключаю поиск в интернете: %s", detail)
                continue
            if any(key in low for key in ("temperature", "top_p", "top_k", "candidate_count")):
                # Параметр устарел в новом поколении — повторяем без него.
                log.warning("Параметр отвергнут моделью: %s", detail)
                continue
            if any(key in low for key in ("429", "resource_exhausted", "quota", "rate limit")):
                limiter.note_rejection()
                raise AIError(
                    "Превышена квота Gemini (429). Суточный лимит бесплатного тарифа "
                    "обнуляется в полночь по тихоокеанскому времени — около 10–11 утра "
                    "по Москве. Расход: /quota"
                ) from exc
            if any(key in low for key in ("500", "503", "unavailable", "internal", "deadline")):
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if any(key in low for key in ("api key", "401", "403", "permission", "unauthenticated")):
                raise AIError("Неверный или неактивный GEMINI_API_KEY.") from exc
            raise last from exc

        answer = _extract_text(response)
        if answer:
            return answer

        reason = _finish_reason(response)
        last = AIError(f"Модель вернула пустой ответ (finish_reason={reason}).")
        if "MAX_TOKENS" in reason:
            max_tokens = min(max_tokens * 2, 8192)
        elif any(key in reason for key in ("SAFETY", "RECITATION", "BLOCK")):
            raise last
        await asyncio.sleep(1.5 * (attempt + 1))

    raise last or AIError("Неизвестная ошибка Gemini.")


# --------------------------------------------------------------------------
#  Разбор новостей
# --------------------------------------------------------------------------

ANALYST_SYSTEM = (
    "Ты — аналитик оперативных сообщений городских служб, администраций и СМИ. "
    "Ты всегда отвечаешь одним валидным JSON-массивом без пояснений и без Markdown. "
    "Работаешь строго по правилам из запроса, ничего не додумывая."
)

ANALYST_PROMPT = """Разбери сообщения из городских источников.

Категории:
- "bpla"      — БПЛА, беспилотники, ракетная опасность, воздушная тревога, работа ПВО, взрывы, угрозы военного характера;
- "mchs"      — экстренные оповещения МЧС: ЧС, штормовое предупреждение, крупные пожары, эвакуация, паводок;
- "jkh"       — ЖКХ: отключения холодной и горячей воды, электричества, газа, отопления, аварии и порывы на сетях, плановые ремонтные работы, лифты;
- "whitelist" — связь: ограничения мобильного интернета, «белые списки» сервисов, восстановление связи.

СООБЩЕНИЯ:
{items}

Верни JSON-массив, по одному объекту на каждое сообщение, в том же порядке:
[{{"index": 1,
   "relevant": true,
   "all_clear": false,
   "categories": ["jkh"],
   "severity": "critical" | "warning" | "info",
   "scope": "region" | "city" | "district" | "street",
   "region": "Саратовская область",
   "city": "Саратов",
   "districts": ["Кировский район"],
   "streets": [{{"street": "улица Чапаева", "houses": ["12", "14", "16-20"]}}],
   "summary": "1-3 предложения: что произошло, где, когда восстановят"}}]

Правила:
1. Реклама, розыгрыши, спорт, культура, политические новости, поздравления → relevant=false, categories=[].
2. Для "bpla" всегда scope="city" или "region": военные угрозы касаются всего города, улицы не указывай.
3. Для "jkh" обязательно вытащи улицы и номера домов, если они названы; диапазон пиши как "12-20".
4. Если ЖКХ-событие затрагивает весь город или район без перечисления улиц — scope="city" либо "district", streets=[].
5. Названия улиц пиши полностью, как в тексте («улица имени Чапаева В.И.» → «улица Чапаева»).
6. Незаполненные поля возвращай пустой строкой или пустым списком, поля не пропускай.
7. summary — по-русски, без эмодзи и разметки.
8. all_clear=true, если сообщение отменяет ранее объявленную опасность: «отбой»,
   «опасность снята», «режим беспилотной опасности отменён», «угроза миновала»,
   «обстановка спокойная». Категорию при этом указывай ту же, что у самой угрозы
   (например, отбой БПЛА → categories=["bpla"], all_clear=true, severity="info").
9. Количество объектов в массиве должно совпадать с количеством сообщений."""

_cache: "OrderedDict[str, Analysis]" = OrderedDict()
_CACHE_LIMIT = 800
_counters = {"ai": 0, "cached": 0, "prefiltered": 0, "heuristic": 0, "requests": 0}


def counters() -> dict[str, int]:
    return dict(_counters)


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _remember(text: str, analysis: Analysis) -> Analysis:
    _cache[_cache_key(text)] = analysis
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return analysis


def _parse_array(raw: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    match = re.search(r"\[.*\]", cleaned, re.S)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return [parsed]
    raise ValueError(f"JSON не найден: {cleaned[:200]}")


def _fallback(text: str, source: str, link: str = "") -> Analysis:
    analysis = heuristic_analysis(
        text, source=source, default_city=config.DEFAULT_CITY, link=link
    )
    if not analysis.city and config.DEFAULT_CITY:
        analysis.city = config.DEFAULT_CITY
    return analysis


async def analyze_batch(items: Sequence[tuple[str, ...]]) -> list[Analysis]:
    """Разбирает список кортежей (текст, источник[, ссылка]).

    Ссылка не участвует в анализе, а только переносится в результат:
    кэш строится по тексту, поэтому одна и та же новость из двух лент
    разбирается один раз.
    """
    results: list[Analysis | None] = [None] * len(items)
    todo: list[int] = []

    for index, item in enumerate(items):
        text, source = item[0], item[1]
        link = item[2] if len(item) > 2 else ""
        key = _cache_key(text)
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            _counters["cached"] += 1
            results[index] = replace(cached, link=link or cached.link)
            continue

        if config.AI_PREFILTER:
            # Дешёвая проверка: если ключевых слов нет вовсе, модель не нужна.
            probe = heuristic_analysis(
                text, source=source, default_city=config.DEFAULT_CITY, link=link
            )
            if not probe.relevant:
                _counters["prefiltered"] += 1
                results[index] = _remember(text, probe)
                continue

        if not ENABLED:
            _counters["heuristic"] += 1
            results[index] = _remember(text, _fallback(text, source, link))
            continue

        todo.append(index)

    for start in range(0, len(todo), config.AI_BATCH_SIZE):
        chunk = todo[start:start + config.AI_BATCH_SIZE]
        listing = "\n\n".join(
            f"[{position + 1}] источник «{items[index][1]}»:\n{items[index][0][:2500]}"
            for position, index in enumerate(chunk)
        )
        try:
            raw = await generate(
                ANALYST_PROMPT.format(items=listing),
                system=ANALYST_SYSTEM,
                json_mode=True,
                max_tokens=700 * len(chunk) + 300,
                temperature=0.1,
                role=ANALYSIS,
                priority=False,
            )
            _counters["requests"] += 1
            payloads = _parse_array(raw)
        except QuotaExceeded:
            log.info("Квота исчерпана — оставшиеся %d сообщений по эвристике", len(chunk))
            for index in chunk:
                _counters["heuristic"] += 1
                results[index] = _remember(items[index][0], _fallback(*items[index][:3]))
            continue
        except (AIError, ValueError, json.JSONDecodeError) as exc:
            log.warning("Пакетный разбор не удался (%s) — эвристика", exc)
            for index in chunk:
                _counters["heuristic"] += 1
                results[index] = _remember(items[index][0], _fallback(*items[index][:3]))
            continue

        by_position: dict[int, dict[str, Any]] = {}
        for position, payload in enumerate(payloads):
            marker = payload.get("index")
            if isinstance(marker, (int, str)) and str(marker).isdigit():
                by_position[int(marker) - 1] = payload
            else:
                by_position.setdefault(position, payload)

        for position, index in enumerate(chunk):
            payload = by_position.get(position)
            text, source = items[index][0], items[index][1]
            link = items[index][2] if len(items[index]) > 2 else ""
            if payload is None:
                _counters["heuristic"] += 1
                results[index] = _remember(text, _fallback(text, source, link))
                continue
            analysis = Analysis.from_payload(payload, source=source, raw=text, link=link)
            if not analysis.city and config.DEFAULT_CITY:
                analysis.city = config.DEFAULT_CITY
            _counters["ai"] += 1
            results[index] = _remember(text, analysis)

    return [item if item is not None else Analysis(relevant=False) for item in results]


async def analyze(text: str, source: str, link: str = "") -> Analysis:
    """Разбор одного сообщения (обёртка над пакетным)."""
    return (await analyze_batch([(text, source, link)]))[0]


def cache_size() -> int:
    return len(_cache)


def quota_snapshot() -> dict[str, int | bool]:
    return limiter.snapshot()


# --------------------------------------------------------------------------
#  ИИ-ассистент
# --------------------------------------------------------------------------

ASSISTANT_SYSTEM = (
    "Ты — ИИ-ассистент системы городского мониторинга «Радар». Помогаешь модераторам "
    "и администраторам: отвечаешь на вопросы, формулируешь оповещения для жителей, "
    "разбираешь ситуации по ЖКХ, ЧС и связи, объясняешь работу самого бота, помогаешь "
    "искать официальные каналы и источники. Если пользуешься поиском — приводи ссылки. "
    "Отвечай по-русски, кратко и по делу. Разметка: **жирный**, `код`, списки. "
    "Не используй заголовки и таблицы: ответ читают в Telegram."
)


def user_turn(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def model_turn(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


async def assistant(history: list[types.Content], question: str) -> str:
    contents = list(history) + [user_turn(question)]
    return await generate(
        contents,
        system=ASSISTANT_SYSTEM,
        max_tokens=2048,
        temperature=0.6,
        role=ASSISTANT,
        priority=True,
        search=True,
    )
RADAR_FILE_31
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/geocode.py"
cat > "radar/geocode.py" <<'RADAR_FILE_32'
"""Обратное геокодирование (Nominatim) с бережным соблюдением лимита 1 запрос/сек."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from . import config

log = logging.getLogger("radar.geocode")

_URL = "https://nominatim.openstreetmap.org/reverse"
_gate = asyncio.Lock()
_last_call = 0.0

async def _throttle() -> None:
    global _last_call
    async with _gate:
        delta = time.monotonic() - _last_call
        if delta < 1.1:
            await asyncio.sleep(1.1 - delta)
        _last_call = time.monotonic()


async def reverse(
    session: aiohttp.ClientSession, lat: float, lon: float
) -> dict[str, str]:
    """Возвращает словарь с ключами name/city/district/region/street/house."""
    await _throttle()
    params = {
        "lat": f"{lat}",
        "lon": f"{lon}",
        "format": "jsonv2",
        "zoom": "18",
        "accept-language": "ru",
        "addressdetails": "1",
    }
    try:
        async with session.get(
            _URL, params=params, headers={"User-Agent": config.USER_AGENT}
        ) as response:
            if response.status != 200:
                log.warning("Nominatim вернул %s", response.status)
                return _fallback(lat, lon)
            payload: dict[str, Any] = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Геокодирование не удалось: %s", exc)
        return _fallback(lat, lon)

    address = payload.get("address") or {}
    street = (
        address.get("road")
        or address.get("pedestrian")
        or address.get("residential")
        or address.get("neighbourhood")
        or ""
    )
    house = address.get("house_number") or ""
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or config.DEFAULT_CITY
    )
    district = (
        address.get("city_district")
        or address.get("district")
        or address.get("suburb")
        or address.get("county")
        or ""
    )
    region = address.get("state") or address.get("region") or ""

    label = ", ".join(part for part in (street, house) if part)
    if not label:
        label = district or city or f"{lat:.5f}, {lon:.5f}"
    if city and city not in label:
        label = f"{label} ({city})"

    return {
        "name": label,
        "street": street,
        "house": house,
        "city": city,
        "district": district,
        "region": region,
    }


def _fallback(lat: float, lon: float) -> dict[str, str]:
    return {
        "name": f"{lat:.5f}, {lon:.5f}",
        "street": "",
        "house": "",
        "city": config.DEFAULT_CITY,
        "district": "",
        "region": "",
    }


_SEARCH_URL = "https://nominatim.openstreetmap.org/search"


async def forward(
    session: aiohttp.ClientSession, query: str, city_hint: str = ""
) -> list[dict[str, str]]:
    """Прямое геокодирование: по строке адреса вернуть варианты с координатами.

    Нужно администрации, чтобы добавлять локации пользователям без геопозиции.
    """
    text = (query or "").strip()
    if len(text) < 3:
        return []
    if city_hint and city_hint.lower() not in text.lower():
        text = f"{text}, {city_hint}"

    await _throttle()
    params = {
        "q": text,
        "format": "jsonv2",
        "addressdetails": "1",
        "accept-language": "ru",
        "limit": "5",
        "countrycodes": "ru",
    }
    try:
        async with session.get(
            _SEARCH_URL, params=params, headers={"User-Agent": config.USER_AGENT}
        ) as response:
            if response.status != 200:
                log.warning("Nominatim search вернул %s", response.status)
                return []
            payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Поиск адреса не удался: %s", exc)
        return []

    results: list[dict[str, str]] = []
    for item in payload if isinstance(payload, list) else []:
        try:
            lat = float(item.get("lat"))
            lon = float(item.get("lon"))
        except (TypeError, ValueError):
            continue
        address = item.get("address") or {}
        street = (
            address.get("road")
            or address.get("pedestrian")
            or address.get("residential")
            or ""
        )
        house = address.get("house_number") or ""
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or ""
        )
        label = ", ".join(part for part in (street, house) if part)
        if not label:
            label = str(item.get("name") or "").strip()
        if not label:
            continue
        if city and city not in label:
            label = f"{label} ({city})"
        results.append(
            {
                "name": label,
                "display": str(item.get("display_name") or label),
                "lat": f"{lat}",
                "lon": f"{lon}",
                "street": street,
                "house": house,
                "city": city,
                "district": address.get("city_district") or address.get("suburb") or "",
                "region": address.get("state") or "",
            }
        )
    return results
RADAR_FILE_32
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/weather.py"
cat > "radar/weather.py" <<'RADAR_FILE_33'
"""Погода Open-Meteo: получение данных и оформление сводки.

Разбор ответа и вёрстка разделены: `fetch` ходит в сеть, `render` — чистая
функция, которую можно покрыть тестами офлайн.

Вёрстка ориентирована на то, как погоду показывают поисковики и мобильные
приложения: крупное текущее значение, строка деталей, почасовая таблица
с колонкой осадков и столбиком температуры, затем прогноз по дням.
Почасовая часть выводится моноширинным блоком — иначе колонки разъезжаются.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

log = logging.getLogger("radar.weather")

_URL = "https://api.open-meteo.com/v1/forecast"

# Коды погоды WMO: описание и значок (день / ночь).
CODES: dict[int, tuple[str, str, str]] = {
    0: ("ясно", "☀️", "🌙"),
    1: ("малооблачно", "🌤", "🌙"),
    2: ("переменная облачность", "⛅️", "☁️"),
    3: ("пасмурно", "☁️", "☁️"),
    45: ("туман", "🌫", "🌫"),
    48: ("изморозь", "🌫", "🌫"),
    51: ("морось", "🌦", "🌧"),
    53: ("морось", "🌦", "🌧"),
    55: ("сильная морось", "🌦", "🌧"),
    56: ("ледяная морось", "🌧", "🌧"),
    57: ("ледяная морось", "🌧", "🌧"),
    61: ("небольшой дождь", "🌦", "🌧"),
    63: ("дождь", "🌧", "🌧"),
    65: ("сильный дождь", "🌧", "🌧"),
    66: ("ледяной дождь", "🌧", "🌧"),
    67: ("ледяной дождь", "🌧", "🌧"),
    71: ("небольшой снег", "🌨", "🌨"),
    73: ("снег", "🌨", "🌨"),
    75: ("сильный снег", "❄️", "❄️"),
    77: ("снежная крупа", "🌨", "🌨"),
    80: ("ливень", "🌦", "🌧"),
    81: ("ливень", "🌧", "🌧"),
    82: ("сильный ливень", "⛈", "⛈"),
    85: ("снегопад", "🌨", "🌨"),
    86: ("сильный снегопад", "❄️", "❄️"),
    95: ("гроза", "⛈", "⛈"),
    96: ("гроза с градом", "⛈", "⛈"),
    99: ("сильная гроза с градом", "⛈", "⛈"),
}

SPARK = "▁▂▃▄▅▆▇█"
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

def describe(code: int | None, day: bool = True) -> tuple[str, str]:
    name, icon_day, icon_night = CODES.get(int(code) if code is not None else -1,
                                          ("", "🌡", "🌡"))
    return name, (icon_day if day else icon_night)


@dataclass
class Hour:
    label: str          # «14ч»
    temp: float
    probability: int
    code: int | None = None
    day: bool = True


@dataclass
class Day:
    label: str          # «сегодня», «завтра», «пт 15»
    low: float
    high: float
    probability: int
    code: int | None = None


@dataclass
class Weather:
    ok: bool = False
    error: str = ""
    temp: float | None = None
    feels: float | None = None
    wind: float | None = None
    gusts: float | None = None
    humidity: int | None = None
    pressure: float | None = None
    code: int | None = None
    is_day: bool = True
    sunrise: str = ""
    sunset: str = ""
    hourly: list[Hour] = field(default_factory=list)
    daily: list[Day] = field(default_factory=list)


# --------------------------------------------------------------------------
#  Получение данных
# --------------------------------------------------------------------------

async def fetch(
    session: aiohttp.ClientSession, lat: float, lon: float, hours: int = 8
) -> Weather:
    if not lat and not lon:
        return Weather(ok=False, error="нет координат — отправьте геопозицию заново")

    params = {
        "latitude": f"{lat}",
        "longitude": f"{lon}",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "wind_speed_10m,wind_gusts_10m,surface_pressure,weather_code,is_day",
        "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,"
                 "weather_code,sunrise,sunset",
        "timezone": "auto",
        "forecast_days": "4",
        "wind_speed_unit": "ms",
    }
    try:
        async with session.get(_URL, params=params) as response:
            if response.status != 200:
                return Weather(ok=False, error=f"сервис погоды вернул код {response.status}")
            data = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Погода недоступна: %s", exc)
        return Weather(ok=False, error="сбой получения погоды")

    return parse(data, hours)


def parse(data: dict, hours: int = 8) -> Weather:
    """Превращает ответ Open-Meteo в структуру. Вынесено ради тестируемости."""
    current = data.get("current") or {}
    weather = Weather(
        ok=True,
        temp=_number(current.get("temperature_2m")),
        feels=_number(current.get("apparent_temperature")),
        wind=_number(current.get("wind_speed_10m")),
        gusts=_number(current.get("wind_gusts_10m")),
        humidity=_integer(current.get("relative_humidity_2m")),
        pressure=_number(current.get("surface_pressure")),
        code=_integer(current.get("weather_code")),
        is_day=bool(current.get("is_day", 1)),
    )

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    probabilities = hourly.get("precipitation_probability") or []
    codes = hourly.get("weather_code") or []
    day_flags = hourly.get("is_day") or []

    now = _now_index(times, current.get("time"))
    for index in range(now, min(now + hours, len(times))):
        temp = _number(temps[index] if index < len(temps) else None)
        if temp is None:
            continue
        stamp = times[index]
        label = stamp.split("T")[1][:2] + "ч" if "T" in stamp else f"+{index - now}ч"
        weather.hourly.append(
            Hour(
                label=label,
                temp=temp,
                probability=_integer(
                    probabilities[index] if index < len(probabilities) else 0
                ) or 0,
                code=_integer(codes[index]) if index < len(codes) else None,
                day=bool(day_flags[index]) if index < len(day_flags) else True,
            )
        )

    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    lows = daily.get("temperature_2m_min") or []
    highs = daily.get("temperature_2m_max") or []
    day_probabilities = daily.get("precipitation_probability_max") or []
    day_codes = daily.get("weather_code") or []
    sunrises = daily.get("sunrise") or []
    sunsets = daily.get("sunset") or []

    if sunrises:
        weather.sunrise = str(sunrises[0]).split("T")[-1][:5]
    if sunsets:
        weather.sunset = str(sunsets[0]).split("T")[-1][:5]

    for index, date in enumerate(dates[:4]):
        low = _number(lows[index] if index < len(lows) else None)
        high = _number(highs[index] if index < len(highs) else None)
        if low is None or high is None:
            continue
        weather.daily.append(
            Day(
                label=_day_label(date, index),
                low=low,
                high=high,
                probability=_integer(
                    day_probabilities[index] if index < len(day_probabilities) else 0
                ) or 0,
                code=_integer(day_codes[index]) if index < len(day_codes) else None,
            )
        )

    return weather


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _now_index(times: list, current_time) -> int:
    """Первый час, который ещё не прошёл."""
    if not times:
        return 0
    marker = str(current_time or "")[:13]
    for index, stamp in enumerate(times):
        if str(stamp)[:13] >= marker:
            return index
    return 0


def _day_label(date: str, index: int) -> str:
    if index == 0:
        return "сегодня"
    if index == 1:
        return "завтра"
    try:
        parsed = datetime.strptime(str(date)[:10], "%Y-%m-%d")
        return f"{WEEKDAYS[parsed.weekday()]} {parsed.day}"
    except ValueError:
        return str(date)[:10]


# --------------------------------------------------------------------------
#  Оформление
# --------------------------------------------------------------------------

def _sparkline(values: list[float]) -> list[str]:
    if not values:
        return []
    low, high = min(values), max(values)
    span = high - low
    if span < 0.5:  # ровная температура — рисуем середину
        return ["▄"] * len(values)
    return [SPARK[min(7, int((value - low) / span * 7.99))] for value in values]


def _temp(value: float | None) -> str:
    return f"{round(value):+d}°".replace("+", "") if value is not None else "—"


def render(weather: Weather, title: str = "") -> str:
    """Собирает готовый HTML-блок сводки."""
    if not weather.ok:
        return f"⚠️ {weather.error or 'нет данных о погоде'}"

    name, icon = describe(weather.code, weather.is_day)
    lines: list[str] = []
    if title:
        lines.append(title)

    head = f"{icon} <b>{_temp(weather.temp)}</b>"
    if name:
        head += f" — {name}"
    lines.append(head)

    details: list[str] = []
    if weather.feels is not None and weather.temp is not None:
        if abs(weather.feels - weather.temp) >= 1:
            details.append(f"ощущается {_temp(weather.feels)}")
    if weather.wind is not None:
        wind = f"💨 {weather.wind:.0f} м/с"
        if weather.gusts and weather.gusts - (weather.wind or 0) >= 3:
            wind += f" (порывы {weather.gusts:.0f})"
        details.append(wind)
    if weather.humidity is not None:
        details.append(f"💧 {weather.humidity}%")
    if weather.pressure:
        details.append(f"{weather.pressure * 0.750062:.0f} мм")
    if details:
        lines.append(" · ".join(details))

    if weather.hourly:
        bars = _sparkline([hour.temp for hour in weather.hourly])
        rows = []
        for hour, bar in zip(weather.hourly, bars):
            _, hour_icon = describe(hour.code, hour.day)
            chance = f"{hour.probability:>3d}%" if hour.probability else "   ·"
            rows.append(f"{hour.label:<4}{hour_icon} {_temp(hour.temp):>4} {bar} {chance}")
        lines.append("")
        lines.append("<pre>" + "\n".join(rows) + "</pre>")

    if weather.daily:
        lines.append("")
        rows = []
        for day in weather.daily[:3]:
            _, day_icon = describe(day.code, True)
            chance = f"  ☔️ {day.probability}%" if day.probability >= 20 else ""
            rows.append(
                f"{day.label:<8}{day_icon} {_temp(day.high):>4} … {_temp(day.low):<4}{chance}"
            )
        lines.append("<pre>" + "\n".join(rows) + "</pre>")

    if weather.sunrise and weather.sunset:
        lines.append(f"🌅 {weather.sunrise}   🌇 {weather.sunset}")

    return "\n".join(lines)


async def forecast(session: aiohttp.ClientSession, lat: float, lon: float) -> str:
    """Совместимость: получить и сразу оформить."""
    return render(await fetch(session, lat, lon))
RADAR_FILE_33
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/sources.py"
cat > "radar/sources.py" <<'RADAR_FILE_34'
"""Сбор сообщений из источников: публичные Telegram-каналы и RSS-ленты СМИ."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from . import config

log = logging.getLogger("radar.sources")

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\u00a0]+")

@dataclass(frozen=True)
class Item:
    """Одно сообщение источника."""

    source: str
    text: str
    kind: str = "tg"  # tg | rss
    link: str = ""    # прямая ссылка на публикацию

    @property
    def key(self) -> str:
        return hashlib.sha1(self.text.encode("utf-8")).hexdigest()


class SeenStore:
    """FIFO-хранилище хэшей уже обработанных сообщений."""

    def __init__(self, maxlen: int = 2000) -> None:
        self._order: deque[str] = deque(maxlen=maxlen)
        self._items: set[str] = set()

    def add(self, key: str) -> bool:
        """True, если сообщение встречено впервые."""
        if key in self._items:
            return False
        if self._order.maxlen and len(self._order) == self._order.maxlen:
            self._items.discard(self._order[0])
        self._order.append(key)
        self._items.add(key)
        return True

    def __len__(self) -> int:
        return len(self._items)


def clean(text: str) -> str:
    text = _TAGS.sub(" ", text)
    text = _SPACES.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


async def fetch_channel(
    session: aiohttp.ClientSession, channel: str, limit: int
) -> list[Item]:
    """Читает веб-превью публичного канала https://t.me/s/<channel>."""
    url = f"https://t.me/s/{channel}"
    try:
        async with session.get(url) as response:
            if response.status != 200:
                log.debug("Канал @%s: HTTP %s", channel, response.status)
                return []
            page = await response.text()
    except Exception as exc:  # noqa: BLE001
        log.debug("Канал @%s недоступен: %s", channel, exc)
        return []

    soup = BeautifulSoup(page, "html.parser")
    blocks = soup.find_all("div", class_="tgme_widget_message_text")
    items: list[Item] = []
    for block in blocks[-limit:]:
        text = clean(block.get_text(separator="\n"))
        if len(text) >= 20:
            items.append(Item(source=channel, text=text, kind="tg"))
    return items


async def fetch_rss(session: aiohttp.ClientSession, url: str, limit: int) -> list[Item]:
    """Читает RSS/Atom-ленту СМИ или официального сайта."""
    try:
        async with session.get(url) as response:
            if response.status != 200:
                log.debug("RSS %s: HTTP %s", url, response.status)
                return []
            body = await response.text()
    except Exception as exc:  # noqa: BLE001
        log.debug("RSS %s недоступен: %s", url, exc)
        return []

    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError as exc:
        log.debug("RSS %s: не разобран (%s)", url, exc)
        return []

    label = urlparse(url).netloc or url
    entries = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    items: list[Item] = []
    for entry in entries[:limit]:
        title = _child_text(entry, "title")
        body_text = _child_text(entry, "description") or _child_text(entry, "summary")
        text = clean(f"{title}\n{body_text}")
        if len(text) >= 20:
            items.append(Item(source=label, text=text, kind="rss", link=_entry_link(entry)))
    return items


def _entry_link(entry: ET.Element) -> str:
    """Ссылка на публикацию: RSS кладёт её в текст, Atom — в атрибут href."""
    node = entry.find("link")
    if node is not None:
        if node.text and node.text.strip():
            return node.text.strip()
        href = node.get("href")
        if href:
            return href.strip()
    for candidate in entry.findall("{http://www.w3.org/2005/Atom}link"):
        rel = candidate.get("rel") or "alternate"
        if rel == "alternate" and candidate.get("href"):
            return candidate.get("href").strip()
    guid = entry.find("guid")
    if guid is not None and guid.text and guid.text.strip().startswith("http"):
        return guid.text.strip()
    return ""


def _child_text(entry: ET.Element, tag: str) -> str:
    for candidate in (tag, f"{{http://www.w3.org/2005/Atom}}{tag}"):
        node = entry.find(candidate)
        if node is not None and node.text:
            return node.text
    return ""


async def collect(
    session: aiohttp.ClientSession,
    channels: list[str],
    feeds: list[str],
    seen: SeenStore,
    limit: int = config.MSG_PER_SOURCE,
    *,
    warmup: bool = False,
) -> list[Item]:
    """Обходит все источники и возвращает только новые сообщения.

    При warmup=True сообщения помечаются прочитанными, но не возвращаются —
    так первый запуск не рассылает всю ленту разом.
    """
    fresh: list[Item] = []

    for channel in list(channels):
        for item in await fetch_channel(session, channel, limit):
            if seen.add(item.key) and not warmup:
                fresh.append(item)

    for url in list(feeds):
        for item in await fetch_rss(session, url, limit):
            if seen.add(item.key) and not warmup:
                fresh.append(item)

    return fresh
RADAR_FILE_34
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/tg.py"
cat > "radar/tg.py" <<'RADAR_FILE_35'
"""Экземпляр бота и безопасные обёртки отправки сообщений."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from . import config
from .textutils import split_text, strip_tags

log = logging.getLogger("radar.tg")

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())

def back_kb(target: str = "menu:main", title: str = "🏠 В главное меню") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=title, callback_data=target)]]
    )


async def send_html(
    chat_id: int | str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Отправляет длинный HTML-текст частями, переживая ошибки разметки и лимиты."""
    chunks = split_text(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        for attempt in range(2):
            try:
                await bot.send_message(int(chat_id), chunk, reply_markup=markup)
                break
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                log.info("Пользователь %s недоступен (бот заблокирован)", chat_id)
                return False
            except TelegramBadRequest as exc:
                log.warning("Ошибка разметки (%s), отправляю обычным текстом", exc)
                try:
                    await bot.send_message(
                        int(chat_id), strip_tags(chunk), parse_mode=None, reply_markup=markup
                    )
                except Exception:  # noqa: BLE001
                    log.exception("Не удалось отправить сообщение %s", chat_id)
                break
            except Exception:  # noqa: BLE001
                log.exception("Сбой отправки сообщения %s", chat_id)
                return False
        await asyncio.sleep(0.05)
    return True


async def safe_edit(
    call: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    """edit_text, устойчивый к «message is not modified» и слишком длинным текстам."""
    chunks = split_text(text)
    try:
        await call.message.edit_text(chunks[0], reply_markup=markup if len(chunks) == 1 else None)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        try:
            await call.message.answer(chunks[0], reply_markup=markup if len(chunks) == 1 else None)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось обновить сообщение")
            return
    for index, chunk in enumerate(chunks[1:], start=1):
        await send_html(
            call.message.chat.id, chunk, markup if index == len(chunks) - 1 else None
        )
RADAR_FILE_35
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/keyboards.py"
cat > "radar/keyboards.py" <<'RADAR_FILE_36'
"""Инлайн-клавиатуры. Формат callback_data: «раздел:действие:аргумент»."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from typing import Any, Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from . import config, features, roles
from .matching import CATEGORY_ICONS, CATEGORY_TITLES

def main_menu(role: str | None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📍 Мои локации", callback_data="loc:list"),
            InlineKeyboardButton(text="⚙️ Оповещения", callback_data="menu:settings"),
        ],
        [
            InlineKeyboardButton(text="🌤 Погода сейчас", callback_data="loc:weather"),
            InlineKeyboardButton(text="📢 Предложить источник", callback_data="src:suggest"),
        ],
    ]
    if features.enabled("sos"):
        rows.append([InlineKeyboardButton(text="🆘 SOS", callback_data="sos:menu")])
    if roles.can_use_assistant(role):
        rows.append([InlineKeyboardButton(text="🧠 ИИ-ассистент", callback_data="menu:ai")])
    if roles.is_moderator(role):
        rows.append([InlineKeyboardButton(text="🛡 Модерация", callback_data="menu:mod")])
    if roles.is_admin(role):
        rows.append([InlineKeyboardButton(text="👥 Пользователи", callback_data="menu:admin")])
    if roles.is_superadmin(role):
        rows.append([
            InlineKeyboardButton(text="⚙️ Возможности", callback_data="feat:list"),
            InlineKeyboardButton(text="📋 Журналы", callback_data="log:list"),
        ])
    rows.append([InlineKeyboardButton(text="ℹ️ О системе", callback_data="menu:about")])
    promo = promo_row()
    if promo:
        rows.append(promo)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_row() -> list[InlineKeyboardButton]:
    """Партнёрская кнопка. Ведёт по внешней ссылке, отключается через .env."""
    if not config.PROMO_ENABLED or not config.PROMO_URL:
        return []
    return [InlineKeyboardButton(text=config.PROMO_TITLE, url=config.PROMO_URL)]


def promo_only() -> InlineKeyboardMarkup | None:
    row = promo_row()
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


# Подписи закреплённых кнопок. Reply-кнопки не умеют открывать ссылки напрямую,
# поэтому «HydraSite» присылает сообщение с обычной inline-кнопкой-ссылкой.
BTN_MENU = "☰ Меню"
BTN_PROMO = "🐙 HydraSite"


def persistent_keyboard() -> ReplyKeyboardMarkup | None:
    """Две кнопки, закреплённые под полем ввода после запуска бота."""
    row = [KeyboardButton(text=BTN_MENU)]
    if config.PROMO_ENABLED and config.PROMO_URL:
        row.append(KeyboardButton(text=BTN_PROMO))
    return ReplyKeyboardMarkup(
        keyboard=[row],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Отправьте геопозицию или задайте вопрос",
    )


def weather_label(user: dict[str, Any]) -> str:
    if user.get("weather_mode") == "time":
        return f"в {user.get('weather_time', '08:00')}"
    minutes = int(user.get("weather_interval") or 0)
    if minutes <= 0:
        return "откл"
    if minutes >= 60 and minutes % 60 == 0:
        return f"каждые {minutes // 60} ч"
    return f"каждые {minutes} мин"


def settings_menu(user: dict[str, Any], target: str = "") -> InlineKeyboardMarkup:
    """target — id редактируемого пользователя (пусто, если правит себя)."""
    settings = user.get("settings") or {}
    suffix = f":{target}" if target else ""
    rows: list[list[InlineKeyboardButton]] = []
    keys = list(CATEGORY_TITLES)
    for index in range(0, len(keys), 2):
        row = []
        for key in keys[index:index + 2]:
            mark = "✅" if settings.get(key) else "❌"
            row.append(
                InlineKeyboardButton(
                    text=f"{mark} {CATEGORY_ICONS[key]} {CATEGORY_TITLES[key].split(' /')[0]}",
                    callback_data=f"set:toggle:{key}{suffix}",
                )
            )
        rows.append(row)
    if not target:
        rows.append(
            [InlineKeyboardButton(
                text=f"🌤 Погода: {weather_label(user)}", callback_data="set:weather"
            )]
        )
        rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    else:
        rows.append(
            [InlineKeyboardButton(text="◀️ К пользователю", callback_data=f"usr:card:{target}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def weather_menu(target: str = "") -> InlineKeyboardMarkup:
    """Меню режима погоды. target — чужой пользователь (правит администрация)."""
    suffix = f":{target}" if target else ""
    back = f"usr:card:{target}" if target else "menu:settings"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отключить", callback_data=f"set:wth:0{suffix}"),
                InlineKeyboardButton(text="Каждый час", callback_data=f"set:wth:60{suffix}"),
            ],
            [
                InlineKeyboardButton(text="Каждые 3 часа", callback_data=f"set:wth:180{suffix}"),
                InlineKeyboardButton(text="Каждые 6 часов", callback_data=f"set:wth:360{suffix}"),
            ],
            [
                InlineKeyboardButton(text="⏰ Точное время", callback_data=f"set:wthtime{suffix}"),
                InlineKeyboardButton(text="⏱ Свой интервал", callback_data=f"set:wthint{suffix}"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=back)],
        ]
    )


def locations_menu(locations: Sequence[dict[str, Any]], owner: str = "") -> InlineKeyboardMarkup:
    """Список локаций с кнопками удаления. owner — чужой пользователь (для модератора)."""
    suffix = f":{owner}" if owner else ""
    rows = [
        [
            InlineKeyboardButton(
                text=f"🗑 {loc.get('name', '')[:40]}",
                callback_data=f"loc:del:{loc.get('id')}{suffix}",
            )
        ]
        for loc in locations
    ]
    if owner:
        rows.append(
            [InlineKeyboardButton(text="➕ Добавить локацию", callback_data=f"usr:addloc:{owner}")]
        )
        rows.append([InlineKeyboardButton(text="◀️ К пользователю", callback_data=f"usr:card:{owner}")])
    else:
        rows.append(
            [
                InlineKeyboardButton(text="🌤 Погода", callback_data="loc:weather"),
                InlineKeyboardButton(text="🗑 Очистить все", callback_data="loc:clear"),
            ]
        )
        rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderation_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Очередь источников", callback_data="src:queue")],
            [InlineKeyboardButton(text="📋 Список источников", callback_data="src:list")],
            [InlineKeyboardButton(text="🔍 Проверить доступность", callback_data="src:check")],
            [InlineKeyboardButton(text="➕ Добавить канал", callback_data="src:add")],
            [InlineKeyboardButton(text="🌐 Добавить RSS СМИ", callback_data="src:addrss")],
            [
                InlineKeyboardButton(text="⬇️ Скачать список", callback_data="src:export"),
                InlineKeyboardButton(text="⬆️ Загрузить список", callback_data="src:import"),
            ],
            [InlineKeyboardButton(text="👥 Пользователи и локации", callback_data="usr:list:0")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
        ]
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список пользователей", callback_data="usr:list:0")],
            [InlineKeyboardButton(text="🔗 Инвайт-ссылка", callback_data="usr:invite")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
        ]
    )


def user_card(target: str, target_role: str, actor_role: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="📍 Локации", callback_data=f"usr:locs:{target}"),
            InlineKeyboardButton(text="⚙️ Оповещения", callback_data=f"usr:sets:{target}"),
        ],
        [InlineKeyboardButton(text="➕ Добавить локацию", callback_data=f"usr:addloc:{target}")],
        [InlineKeyboardButton(text="🌤 Погода пользователя", callback_data=f"usr:wth:{target}")],
    ]
    assignable = [
        role for role in roles.assignable_roles(actor_role)
        if roles.can_assign(actor_role, target_role, role) and role != target_role
    ]
    if assignable:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"→ {roles.title(role)}", callback_data=f"usr:role:{target}:{role}"
                )
                for role in assignable
            ]
        )
    if roles.can_delete_user(actor_role, target_role):
        rows.append(
            [InlineKeyboardButton(text="🔨 Удалить пользователя", callback_data=f"usr:del:{target}")]
        )
    rows.append([InlineKeyboardButton(text="◀️ К списку", callback_data="usr:list:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def users_page(
    items: Sequence[tuple[str, str, int]], page: int, pages: int
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{roles.title(role).split()[0]} {uid} · {count} лок.",
                callback_data=f"usr:card:{uid}",
            )
        ]
        for uid, role, count in items
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"usr:list:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"usr:list:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def geocode_choices(results: list[dict[str, str]], target: str) -> InlineKeyboardMarkup:
    """Варианты найденных адресов: выбор администратором."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{index + 1}. {item['name'][:45]}",
                callback_data=f"usr:pickloc:{target}:{index}",
            )
        ]
        for index, item in enumerate(results)
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"usr:card:{target}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm(action: str, argument: str, back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"{action}:{argument}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=back),
            ]
        ]
    )


def queue_item() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data="src:approve"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data="src:reject"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:mod")],
        ]
    )
RADAR_FILE_36
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/states.py"
cat > "radar/states.py" <<'RADAR_FILE_37'
"""Состояния FSM."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
    suggest_source = State()
    add_channel = State()
    add_rss = State()
    weather_time = State()
    weather_interval = State()
    manual_address = State()
    admin_add_location = State()   # ввод адреса для чужого пользователя
    admin_weather_time = State()   # точное время погоды для чужого пользователя
    admin_weather_interval = State()
    sos_contact = State()          # добавление доверенного контакта
    sos_location = State()         # ожидание геопозиции для сигнала
RADAR_FILE_37
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/middlewares.py"
cat > "radar/middlewares.py" <<'RADAR_FILE_38'
"""Middleware доступа: регистрация по инвайту и отсев посторонних."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import storage

log = logging.getLogger("radar.access")

class AccessMiddleware(BaseMiddleware):
    """Пропускает только зарегистрированных; по /start join регистрирует нового."""

    def __init__(self) -> None:
        self._notified: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        uid = str(user.id)
        text = (getattr(event, "text", "") or "").strip()

        # Доверенный контакт SOS открывает бота по ссылке ?start=sos_<код>.
        # Регистрируем его и отмечаем подтверждённым — иначе Telegram
        # не позволит боту написать ему первым при тревоге.
        if text.startswith("/start") and "sos_" in text:
            from . import sos

            invite = text.split("sos_", 1)[1].split()[0].strip()
            found = sos.find_by_invite(storage.users(), invite)
            if found is not None:
                owner, _contact = found
                if uid not in storage.users():
                    storage.register(uid, user.username or "")
                owner_data = storage.get_user(owner)
                if owner_data is not None:
                    sos.confirm_by_invite(owner_data, invite, uid)
                    await storage.save(owner)
                await storage.save(uid)
                log.info("Контакт SOS подтверждён: %s для %s", uid, owner)

        if uid not in storage.users() and text.startswith("/start") and "join" in text:
            storage.register(uid, user.username or "")
            await storage.save()
            log.info("Регистрация по инвайту: %s (@%s)", uid, user.username)

        record = storage.get_user(uid)
        if record is None:
            now = time.monotonic()
            if now - self._notified.get(user.id, 0) > 600:
                self._notified[user.id] = now
                try:
                    if isinstance(event, Message):
                        await event.answer(
                            "⛔️ Доступ к системе «Радар» закрыт.\n"
                            f"Ваш ID: <code>{user.id}</code> — передайте его администратору."
                        )
                    elif isinstance(event, CallbackQuery):
                        await event.answer("Доступ закрыт.", show_alert=True)
                except TelegramForbiddenError:
                    pass
            return None

        if user.username and record.get("username") != user.username:
            record["username"] = user.username

        data["user"] = record
        data["role"] = record.get("role", "user")
        return await handler(event, data)
RADAR_FILE_38
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/monitor.py"
cat > "radar/monitor.py" <<'RADAR_FILE_39'
"""Фоновый цикл: сбор источников, разбор через ИИ, группировка и рассылка."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import aiohttp

from . import ai, config, features, geocode, sos, sources, storage, weather
from .matching import Analysis, cluster_title, plan_alerts
from .textutils import cluster_center, cluster_locations
from .tg import back_kb, send_html

log = logging.getLogger("radar.monitor")

seen = sources.SeenStore()
_stats = {"cycles": 0, "items": 0, "alerts": 0, "last_cycle": 0}

def stats() -> dict[str, Any]:
    return dict(_stats, seen=len(seen), cache=ai.cache_size(), **ai.counters())


# --------------------------------------------------------------------------
#  Погода: пора ли отправлять
# --------------------------------------------------------------------------

def weather_due(user: dict[str, Any], now_ts: int, now: datetime) -> bool:
    mode = user.get("weather_mode", "interval")
    if mode == "interval":
        interval = int(user.get("weather_interval") or 0)
        if interval <= 0:
            return False
        return now_ts - int(user.get("last_weather") or 0) >= interval * 60

    target = str(user.get("weather_time") or "08:00")
    try:
        hour, minute = (int(part) for part in target.split(":"))
    except ValueError:
        return False
    if user.get("last_fixed_date") == now.strftime("%Y-%m-%d"):
        return False
    # Сравниваем по окну, а не по точной минуте: цикл может длиться дольше минуты.
    return (now.hour, now.minute) >= (hour, minute)


# --------------------------------------------------------------------------
#  Геокодирование «хвостов» из старой базы
# --------------------------------------------------------------------------

async def backfill_geocode(session: aiohttp.ClientSession) -> None:
    """Дозаполняет город/улицу/дом у локаций, перенесённых из версий 2.x."""
    pending: list[dict[str, Any]] = []
    for user in storage.users().values():
        for loc in user.get("locs") or []:
            if loc.get("city") or not (loc.get("lat") or loc.get("lon")):
                continue
            pending.append(loc)
    if not pending:
        return

    log.info("Дозаполняю адреса для %d локаций из старой базы", len(pending))
    for loc in pending:
        info = await geocode.reverse(session, float(loc["lat"]), float(loc["lon"]))
        for key in ("street", "house", "city", "district", "region"):
            if info.get(key):
                loc[key] = info[key]
        if loc.get("name", "").replace(" ", "").replace(",", "").replace(".", "").isdigit():
            loc["name"] = info.get("name") or loc["name"]
    await storage.save()
    log.info("Адреса дозаполнены")


# --------------------------------------------------------------------------
#  Рассылка одному пользователю
# --------------------------------------------------------------------------

async def dispatch_user(
    session: aiohttp.ClientSession,
    uid: str,
    user: dict[str, Any],
    analyses: list[Analysis],
    now_ts: int,
    now: datetime,
) -> bool:
    """Готовит и отправляет сообщения одному пользователю. True — база изменена."""
    locations = user.get("locs") or []
    if not locations:
        return False

    messages = plan_alerts(
        locations,
        user.get("settings") or {},
        analyses,
        config.CLUSTER_RADIUS_M,
        config.DEFAULT_CITY,
    )

    sent = 0
    for _kind, text in messages:
        if await send_html(uid, text, back_kb()):
            sent += 1
        await asyncio.sleep(0.3)

    changed = False
    if weather_due(user, now_ts, now):
        clusters = cluster_locations(locations, config.CLUSTER_RADIUS_M)
        for index, cluster in enumerate(clusters):
            lat, lon = cluster_center(cluster)
            data = await weather.fetch(session, lat, lon)
            markup = back_kb() if index == len(clusters) - 1 else None
            await send_html(uid, weather.render(data, cluster_title(cluster)), markup)
            sent += 1
            await asyncio.sleep(0.2)
        user["last_weather"] = now_ts
        if user.get("weather_mode") == "time":
            user["last_fixed_date"] = now.strftime("%Y-%m-%d")
        changed = True

    _stats["alerts"] += sent
    return changed


# --------------------------------------------------------------------------
#  Цикл
# --------------------------------------------------------------------------

async def repeat_sos() -> None:
    """Повторяет активные сигналы SOS, пока отправитель не дал отбой."""
    if not features.enabled("sos"):
        return

    for alert in sos.due_alerts():
        owner = storage.get_user(alert.owner)
        if owner is None:
            sos.stop_alert(alert.owner)
            continue

        alert.repeats += 1
        alert.last_sent = time.time()
        text = sos.build_alert(
            owner.get("username") or f"ID {alert.owner}",
            "",
            alert.lat,
            alert.lon,
            alert.address,
            alert.note,
            repeat=alert.repeats,
        )
        for contact in sos.confirmed_contacts(owner):
            await send_html(contact.key, text)
        log.info("Повтор сигнала SOS от %s (%d)", alert.owner, alert.repeats)

        if alert.repeats >= sos.MAX_REPEATS:
            sos.stop_alert(alert.owner)
            await send_html(
                alert.owner,
                "🆘 Повторы сигнала прекращены — достигнут предел. "
                "Нажмите SOS заново, если помощь всё ещё нужна.",
            )


async def cycle(session: aiohttp.ClientSession, *, warmup: bool = False) -> None:
    items = await sources.collect(
        session,
        storage.channels(),
        storage.rss_feeds(),
        seen,
        config.MSG_PER_SOURCE,
        warmup=warmup,
    )
    if warmup:
        log.info("Первый проход: %d сообщений помечены прочитанными", len(seen))
        return

    _stats["cycles"] += 1
    _stats["items"] += len(items)
    _stats["last_cycle"] = int(time.time())

    analyses: list[Analysis] = []
    if items:
        try:
            parsed = await ai.analyze_batch(
                [(item.text, item.source, item.link) for item in items]
            )
        except Exception:  # noqa: BLE001
            log.exception("Пакетный разбор сообщений не удался")
            parsed = []
        analyses = [analysis for analysis in parsed if analysis.relevant]
        counters = ai.counters()
        log.info(
            "Новых сообщений: %d, значимых: %d | запросов к ИИ: %d, "
            "отсеяно фильтром: %d, из кэша: %d, эвристикой: %d",
            len(items), len(analyses), counters["requests"],
            counters["prefiltered"], counters["cached"], counters["heuristic"],
        )

    now_ts = int(time.time())
    now = datetime.now()
    changed = False
    for uid, user in list(storage.users().items()):
        try:
            if await dispatch_user(session, uid, user, analyses, now_ts, now):
                changed = True
        except Exception:  # noqa: BLE001
            log.exception("Ошибка рассылки пользователю %s", uid)
    if changed:
        await storage.save()


async def run() -> None:
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "ru,en;q=0.8"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            await backfill_geocode(session)
        except Exception:  # noqa: BLE001
            log.exception("Дозаполнение адресов не удалось")

        await cycle(session, warmup=True)

        while True:
            started = time.monotonic()
            try:
                await repeat_sos()
                await cycle(session)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Сбой цикла мониторинга")
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(15.0, config.POLL_INTERVAL - elapsed))
RADAR_FILE_39
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/__init__.py"
cat > "radar/handlers/__init__.py" <<'RADAR_FILE_40'
"""Роутеры обработчиков. Порядок подключения важен: ассистент — последним."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import Dispatcher

from . import (
    assistant,
    common,
    features,
    locations,
    logs,
    settings,
    sos,
    sources,
    users,
)

def setup(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(locations.router)
    dp.include_router(settings.router)
    dp.include_router(sources.router)
    dp.include_router(users.router)
    dp.include_router(features.router)
    dp.include_router(logs.router)
    dp.include_router(sos.router)
    # Ассистент перехватывает любой оставшийся текст — только в самом конце.
    dp.include_router(assistant.router)


__all__ = ["setup"]
RADAR_FILE_40
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/common.py"
cat > "radar/handlers/common.py" <<'RADAR_FILE_41'
"""Команды /start, /menu, /help, /id, /cancel и главное меню."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from .. import ai, config, keyboards, monitor, roles, storage
from ..textutils import esc
from ..tg import back_kb, safe_edit

router = Router(name="common")

def greeting(role: str) -> str:
    lines = [f"🎛 <b>Система «Радар» v{config.VERSION}</b>", f"Ваша роль: {roles.title(role)}"]
    if roles.can_use_assistant(role):
        lines.append("")
        lines.append(
            "🧠 <i>ИИ-ассистент активен: напишите вопрос в чат или используйте /ai.</i>"
        )
    if not ai.ENABLED and roles.is_admin(role):
        lines.append("")
        lines.append("⚠️ <i>GEMINI_API_KEY не задан — работает эвристический анализ без ИИ.</i>")
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    # Закреплённые кнопки ставятся отдельным сообщением: Telegram не позволяет
    # приложить reply-клавиатуру и inline-меню к одному и тому же сообщению.
    keyboard = keyboards.persistent_keyboard()
    if keyboard is not None:
        await message.answer(
            "Кнопки <b>Меню</b> и <b>HydraSite</b> закреплены под полем ввода.",
            reply_markup=keyboard,
        )
    await message.answer(greeting(role), reply_markup=keyboards.main_menu(role))


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    await message.answer(greeting(role), reply_markup=keyboards.main_menu(role))


@router.message(F.text == keyboards.BTN_MENU)
async def button_menu(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    await message.answer(greeting(role), reply_markup=keyboards.main_menu(role))


@router.message(F.text == keyboards.BTN_PROMO)
async def button_promo(message: Message) -> None:
    if not config.PROMO_ENABLED or not config.PROMO_URL:
        return
    await message.answer(
        config.PROMO_TEXT,
        reply_markup=keyboards.promo_only(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(Command("partner", "vpn"))
async def cmd_partner(message: Message) -> None:
    await button_promo(message)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    await message.answer("✅ Действие отменено.", reply_markup=keyboards.main_menu(role))


@router.message(Command("id"))
async def cmd_id(message: Message, role: str) -> None:
    await message.answer(
        f"🆔 Ваш ID: <code>{message.from_user.id}</code>\nРоль: {roles.title(role)}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message, role: str) -> None:
    lines = [
        "<b>Как это работает</b>",
        "1. Отправьте геопозицию (Скрепка → Геопозиция) — так добавляется локация. "
        "Их может быть сколько угодно.",
        "2. Военные угрозы (БПЛА, ракетная опасность) приходят на весь город одним "
        "сообщением по всем вашим локациям в нём.",
        "3. Аварии ЖКХ ищутся адресно — по улице и дому.",
        "4. Локации ближе 1 км друг к другу объединяются в одну сводку.",
        "",
        "<b>Команды</b>",
        "/menu — меню - /id — ваш ID и роль - /cancel — сбросить ввод",
        "/partner — партнёрский проект",
    ]
    if roles.can_use_assistant(role):
        lines.append("/ai &lt;вопрос&gt; — ИИ-ассистент - /aireset — очистить контекст")
        lines.append("/quota — расход квоты Gemini")
    if roles.is_admin(role):
        lines.append("/stats — статистика системы - /models — модели Gemini")
    if roles.is_superadmin(role):
        lines.append(
            "/features — возможности системы\n"
            "/logs — журналы - /logtail — последние строки - /logclear — очистить"
        )
    await message.answer("\n".join(lines), reply_markup=back_kb())


@router.callback_query(F.data == "menu:main")
async def menu_main(call: CallbackQuery, state: FSMContext, role: str) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(call, greeting(role), keyboards.main_menu(role))


@router.callback_query(F.data == "menu:settings")
async def menu_settings(call: CallbackQuery, state: FSMContext, user: dict[str, Any]) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(
        call,
        "⚙️ <b>Оповещения</b>\nВыберите, какие события присылать, и режим погоды.",
        keyboards.settings_menu(user),
    )


@router.callback_query(F.data == "menu:mod")
async def menu_mod(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_moderator(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, "🛡 <b>Панель модератора</b>", keyboards.moderation_menu())


@router.callback_query(F.data == "menu:admin")
async def menu_admin(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, "👥 <b>Управление пользователями</b>", keyboards.admin_menu())


@router.callback_query(F.data == "menu:about")
async def menu_about(call: CallbackQuery) -> None:
    await call.answer()
    parts = [
        f"ℹ️ <b>Система «Радар» v{config.VERSION}</b>",
        "",
        "Мониторит публичные Telegram-каналы служб ЖКХ, МЧС, администраций города, "
        "района и области, а также ленты СМИ. Сообщения разбирает ИИ Google Gemini, "
        "после чего события сопоставляются с вашими локациями.",
        "",
        "🛸 Военные угрозы — на весь город.",
        "🛠 ЖКХ — адресно, по улице и дому.",
        "📵 При угрозе с воздуха предупреждаем о «белых списках» связи.",
        "🌤 Погода — по каждой группе локаций.",
        "",
        "<i>Система не заменяет официальные каналы оповещения.</i>",
    ]
    if config.PROMO_ENABLED and config.PROMO_TEXT:
        parts += ["", "———", "", config.PROMO_TEXT]
    await safe_edit(call, "\n".join(parts), keyboards.promo_only() or back_kb())


def _quota_line() -> str:
    quota = ai.quota_snapshot()
    state = " ⏸ пауза после 429" if quota["paused"] else ""
    return (
        f"Квота Gemini: <b>{quota['used_today']}/{quota['limit_day']}</b> за сутки, "
        f"<b>{quota['in_minute']}/{quota['limit_minute']}</b> за минуту{state}"
    )


def _stats_text() -> str:
    counters: dict[str, int] = {}
    locations = 0
    for user in storage.users().values():
        counters[user.get("role", "user")] = counters.get(user.get("role", "user"), 0) + 1
        locations += len(user.get("locs") or [])
    data = monitor.stats()
    parts = [
        f"📊 <b>Статистика «Радар» v{config.VERSION}</b>",
        f"Пользователей: <b>{len(storage.users())}</b> "
        f"({', '.join(f'{roles.title(r)}: {c}' for r, c in sorted(counters.items()))})",
        f"Локаций: <b>{locations}</b>",
        f"Каналов: <b>{len(storage.channels())}</b>, RSS: <b>{len(storage.rss_feeds())}</b>, "
        f"в очереди: <b>{len(storage.pending())}</b>",
        f"ИИ: <b>{esc(ai.current_model(ai.ASSISTANT)) if ai.ENABLED else 'выключен (эвристика)'}</b>"
        + (f" | разбор: <b>{esc(ai.current_model(ai.ANALYSIS))}</b>" if ai.ENABLED else ""),
        f"Циклов: <b>{data['cycles']}</b>, сообщений: <b>{data['items']}</b>, "
        f"оповещений: <b>{data['alerts']}</b>",
        f"Кэш анализов: <b>{data['cache']}</b>, помечено прочитанным: <b>{data['seen']}</b>",
        f"Разбор: ИИ <b>{data['ai']}</b>, из кэша <b>{data['cached']}</b>, "
        f"отсеяно фильтром <b>{data['prefiltered']}</b>, эвристикой <b>{data['heuristic']}</b>",
        _quota_line(),
        f"Интервал опроса: <b>{config.POLL_INTERVAL} с</b>",
        f"Время сервера: <b>{datetime.now():%Y-%m-%d %H:%M:%S}</b>",
    ]
    return "\n".join(parts)


@router.message(Command("stats"))
async def cmd_stats(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        return
    await message.answer(_stats_text(), reply_markup=back_kb())


@router.message(Command("quota"))
async def cmd_quota(message: Message, role: str) -> None:
    if not roles.is_moderator(role):
        return
    counters = ai.counters()
    lines = [
        "📉 <b>Расход квоты Gemini</b>",
        _quota_line(),
        f"Запросов к модели: <b>{counters['requests']}</b> "
        f"(разобрано сообщений: {counters['ai']})",
        f"Сэкономлено: фильтр <b>{counters['prefiltered']}</b>, "
        f"кэш <b>{counters['cached']}</b>, эвристика <b>{counters['heuristic']}</b>",
        "",
        f"Анализ: <code>{esc(ai.current_model(ai.ANALYSIS))}</code>, "
        f"ассистент: <code>{esc(ai.current_model(ai.ASSISTANT))}</code>",
        "<i>Суточный лимит обнуляется в полночь по тихоокеанскому времени "
        "(около 10–11 утра по Москве).</i>",
    ]
    await message.answer("\n".join(lines), reply_markup=back_kb())


@router.message(Command("models"))
async def cmd_models(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        return
    report = ai.models_report()
    lines = [
        "🤖 <b>Модели Gemini</b>",
        f"Ассистент: <code>{esc(report['assistant'])}</code>",
        f"Разбор новостей: <code>{esc(report['analysis'])}</code>",
    ]
    if report["unavailable"]:
        lines.append(
            "Отключены ключом: " + ", ".join(f"<code>{esc(m)}</code>" for m in report["unavailable"])
        )
    available = [m for m in report["available"] if "gemini" in m]
    if available:
        lines.append("")
        lines.append(f"<b>Доступно ключу ({len(available)}):</b>")
        lines.extend(f"• <code>{esc(name)}</code>" for name in available[:40])
        if len(available) > 40:
            lines.append(f"…и ещё {len(available) - 40}")
    else:
        lines.append("")
        lines.append("<i>Список моделей получить не удалось — используются значения из .env.</i>")
    lines.append("")
    lines.append(
        "<i>Модель подбирается автоматически. Чтобы закрепить свою — задайте "
        "GEMINI_MODEL в .env и перезапустите контейнер.</i>"
    )
    await message.answer("\n".join(lines), reply_markup=back_kb())


@router.callback_query(F.data == "menu:stats")
async def stats_button(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _stats_text(), back_kb("menu:admin", "◀️ Назад"))
RADAR_FILE_41
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/locations.py"
cat > "radar/handlers/locations.py" <<'RADAR_FILE_42'
"""Локации пользователя: добавление, список, удаление, погода по группам."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from typing import Any

import aiohttp
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from .. import config, geocode, keyboards, roles, storage, weather
from ..matching import cluster_title
from ..textutils import cluster_center, cluster_locations, esc, haversine_m
from ..tg import back_kb, safe_edit, send_html

router = Router(name="locations")

def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=25),
        headers={"User-Agent": config.USER_AGENT},
    )


def locations_text(user: dict[str, Any], owner_label: str = "") -> str:
    locations = user.get("locs") or []
    if not locations:
        body = "— список пуст —"
    else:
        clusters = cluster_locations(locations, config.CLUSTER_RADIUS_M)
        lines = []
        for index, cluster in enumerate(clusters, start=1):
            if len(cluster) > 1:
                lines.append(f"<b>Группа {index}</b> <i>(в пределах 1 км)</i>")
            for loc in cluster:
                extra = ", ".join(
                    part for part in (loc.get("district"), loc.get("city")) if part
                )
                suffix = f" <i>({esc(extra)})</i>" if extra else ""
                lines.append(f"• {esc(loc.get('name'))}{suffix}")
        body = "\n".join(lines)

    head = f"📍 <b>Локации {owner_label}</b>" if owner_label else "📍 <b>Ваши локации</b>"
    tail = (
        "\n\n<i>Добавить: отправьте геопозицию в чат (Скрепка → Геопозиция). "
        "Количество не ограничено.</i>"
    )
    return f"{head}\n{body}{tail if not owner_label else ''}"


# StateFilter(None) обязателен: иначе этот обработчик перехватит геопозицию,
# отправленную администратором при добавлении локации другому пользователю.
@router.message(StateFilter(None), F.location)
async def add_location(message: Message, user: dict[str, Any]) -> None:
    lat = message.location.latitude
    lon = message.location.longitude

    if config.MAX_LOCATIONS and len(user["locs"]) >= config.MAX_LOCATIONS:
        await message.answer(f"❌ Достигнут лимит локаций ({config.MAX_LOCATIONS}).")
        return

    for existing in user["locs"]:
        if existing.get("lat") and haversine_m(
            lat, lon, float(existing["lat"]), float(existing["lon"])
        ) < 40:
            await message.answer(
                f"ℹ️ Эта точка уже сохранена как <b>{esc(existing['name'])}</b>.",
                reply_markup=back_kb(),
            )
            return

    async with _session() as session:
        info = await geocode.reverse(session, lat, lon)

    location = storage.new_location(
        info["name"], lat, lon,
        street=info["street"], house=info["house"],
        city=info["city"], district=info["district"], region=info["region"],
    )
    user["locs"].append(location)
    await storage.save()

    details = ", ".join(
        part for part in (location["district"], location["city"], location["region"]) if part
    )
    text = f"🏠 Локация <b>{esc(location['name'])}</b> добавлена."
    if details:
        text += f"\n<i>{esc(details)}</i>"
    if not location["street"]:
        text += "\n⚠️ <i>Улица не определена — адресные оповещения ЖКХ могут быть неточными.</i>"
    await message.answer(text, reply_markup=back_kb())


@router.callback_query(F.data == "loc:list")
async def list_locations(call: CallbackQuery, user: dict[str, Any]) -> None:
    await call.answer()
    await safe_edit(call, locations_text(user), keyboards.locations_menu(user["locs"]))


@router.callback_query(F.data == "loc:clear")
async def clear_locations(call: CallbackQuery, user: dict[str, Any]) -> None:
    user["locs"] = []
    await storage.save()
    await call.answer("Локации удалены")
    await safe_edit(call, locations_text(user), keyboards.locations_menu([]))


@router.callback_query(F.data.startswith("loc:del:"))
async def delete_location(call: CallbackQuery, user: dict[str, Any], role: str) -> None:
    parts = call.data.split(":")
    loc_id = parts[2]
    owner = parts[3] if len(parts) > 3 else ""

    if owner:
        target = storage.get_user(owner)
        if target is None:
            await call.answer("Пользователь не найден.", show_alert=True)
            return
        if not roles.can_edit_user(role, target.get("role")):
            await call.answer("Недостаточно прав.", show_alert=True)
            return
        storage.remove_location(owner, loc_id)
        await storage.save()
        await call.answer("Локация удалена")
        await safe_edit(
            call,
            locations_text(target, owner_label=f"<code>{owner}</code>"),
            keyboards.locations_menu(target["locs"], owner=owner),
        )
        return

    storage.remove_location(call.from_user.id, loc_id)
    await storage.save()
    await call.answer("Локация удалена")
    await safe_edit(call, locations_text(user), keyboards.locations_menu(user["locs"]))


@router.callback_query(F.data == "loc:weather")
async def show_weather(call: CallbackQuery, user: dict[str, Any]) -> None:
    locations = user.get("locs") or []
    if not locations:
        await call.answer("Сначала добавьте локацию.", show_alert=True)
        return

    await call.answer("Запрашиваю прогноз…")
    clusters = cluster_locations(locations, config.CLUSTER_RADIUS_M)
    async with _session() as session:
        for index, cluster in enumerate(clusters):
            lat, lon = cluster_center(cluster)
            data = await weather.fetch(session, lat, lon)
            markup = back_kb() if index == len(clusters) - 1 else None
            await send_html(
                call.message.chat.id,
                weather.render(data, cluster_title(cluster)),
                markup,
            )
RADAR_FILE_42
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/settings.py"
cat > "radar/handlers/settings.py" <<'RADAR_FILE_43'
"""Настройки: категории оповещений и режим отправки погоды."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards, roles, storage
from ..matching import CATEGORY_TITLES
from ..states import Form
from ..tg import back_kb, safe_edit, send_html

router = Router(name="settings")

@router.callback_query(F.data.startswith("set:toggle:"))
async def toggle_category(call: CallbackQuery, user: dict[str, Any], role: str) -> None:
    parts = call.data.split(":")
    key = parts[2]
    target_id = parts[3] if len(parts) > 3 else ""
    if key not in CATEGORY_TITLES:
        await call.answer()
        return

    subject = user
    if target_id:
        subject = storage.get_user(target_id)
        if subject is None:
            await call.answer("Пользователь не найден.", show_alert=True)
            return
        if not roles.can_edit_user(role, subject.get("role")):
            await call.answer("Недостаточно прав.", show_alert=True)
            return

    settings = subject.setdefault("settings", storage.default_settings())
    settings[key] = not settings.get(key, True)
    await storage.save()
    await call.answer("Включено" if settings[key] else "Выключено")
    try:
        await call.message.edit_reply_markup(
            reply_markup=keyboards.settings_menu(subject, target_id)
        )
    except TelegramBadRequest:
        pass


def _subject(call: CallbackQuery, user: dict[str, Any], role: str,
             target: str) -> dict[str, Any] | None:
    """Чьи настройки правим: свои или чужие (для администрации)."""
    if not target:
        return user
    other = storage.get_user(target)
    if other is None or not roles.can_edit_user(role, other.get("role")):
        return None
    return other


@router.callback_query(F.data == "set:weather")
async def weather_menu(call: CallbackQuery) -> None:
    await call.answer()
    await safe_edit(
        call,
        "⏱ <b>Режим погоды</b>\nВыберите интервал или задайте своё значение.",
        keyboards.weather_menu(),
    )


@router.callback_query(F.data.startswith("usr:wth:"))
async def weather_for_user(call: CallbackQuery, role: str) -> None:
    """Администрация задаёт пользователю режим погоды так же, как он сам."""
    target = call.data.split(":")[2]
    other = storage.get_user(target)
    if other is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_edit_user(role, other.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    await call.answer()
    locations = len(other.get("locs") or [])
    await safe_edit(
        call,
        f"🌤 <b>Погода пользователя</b> <code>{target}</code>\n"
        f"Сейчас: {keyboards.weather_label(other)}, локаций: {locations}\n\n"
        "<i>Настройка применится так же, как если бы её сделал сам пользователь.</i>",
        keyboards.weather_menu(target),
    )


@router.callback_query(F.data.startswith("set:wth:"))
async def set_interval(call: CallbackQuery, user: dict[str, Any], role: str) -> None:
    parts = call.data.split(":")
    try:
        minutes = int(parts[2])
    except (IndexError, ValueError):
        await call.answer()
        return
    target = parts[3] if len(parts) > 3 else ""

    subject = _subject(call, user, role, target)
    if subject is None:
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    subject["weather_mode"] = "interval"
    subject["weather_interval"] = minutes
    subject["last_weather"] = 0
    await storage.save(target or call.from_user.id)
    await call.answer("Погода отключена" if minutes == 0 else f"Интервал: {minutes} мин")

    if target:
        await send_html(
            target,
            "🌤 Администратор изменил режим погоды: "
            f"<b>{keyboards.weather_label(subject)}</b>.",
        )
        await safe_edit(
            call,
            f"✅ Погода пользователя <code>{target}</code>: "
            f"{keyboards.weather_label(subject)}",
            keyboards.weather_menu(target),
        )
    else:
        await safe_edit(call, "⚙️ <b>Оповещения</b>", keyboards.settings_menu(user))


@router.callback_query(F.data.startswith("set:wthtime"))
async def ask_time(call: CallbackQuery, state: FSMContext, role: str) -> None:
    parts = call.data.split(":")
    target = parts[2] if len(parts) > 2 else ""
    if target and not roles.can_edit_user(role, (storage.get_user(target) or {}).get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    await call.answer()
    await state.update_data(weather_target=target)
    await state.set_state(Form.weather_time)
    who = f" для <code>{target}</code>" if target else ""
    await safe_edit(
        call,
        f"⏰ Введите время{who} в формате <code>HH:MM</code> (например, 08:30):",
        back_kb(f"usr:wth:{target}" if target else "set:weather", "Отмена"),
    )


@router.message(Form.weather_time)
async def save_time(message: Message, state: FSMContext, user: dict[str, Any],
                    role: str) -> None:
    value = (message.text or "").strip()
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
        await message.answer("❌ Неверный формат. Пример: <code>08:30</code>. /cancel — отмена.")
        return
    hour, minute = value.split(":")
    value = f"{int(hour):02d}:{minute}"

    target = (await state.get_data()).get("weather_target") or ""
    subject = user
    if target:
        subject = storage.get_user(target)
        if subject is None or not roles.can_edit_user(role, subject.get("role")):
            await state.clear()
            await message.answer("❌ Недостаточно прав или пользователь не найден.")
            return

    subject["weather_mode"] = "time"
    subject["weather_time"] = value
    subject["last_fixed_date"] = ""
    await storage.save(target or message.from_user.id)
    await state.clear()

    if target:
        await send_html(target, f"🌤 Администратор установил доставку погоды в <b>{value}</b>.")
        await message.answer(
            f"✅ Пользователю <code>{target}</code> погода будет приходить в <b>{value}</b>.",
            reply_markup=back_kb(f"usr:card:{target}", "◀️ К пользователю"),
        )
    else:
        await message.answer(
            f"✅ Погода будет приходить ежедневно в <b>{value}</b>.",
            reply_markup=keyboards.settings_menu(user),
        )


@router.callback_query(F.data.startswith("set:wthint"))
async def ask_interval(call: CallbackQuery, state: FSMContext, role: str) -> None:
    parts = call.data.split(":")
    target = parts[2] if len(parts) > 2 else ""
    if target and not roles.can_edit_user(role, (storage.get_user(target) or {}).get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    await call.answer()
    await state.update_data(weather_target=target)
    await state.set_state(Form.weather_interval)
    await safe_edit(
        call,
        "⏱ Введите интервал: <code>45</code> (минут) или <code>2ч</code> (часа):",
        back_kb(f"usr:wth:{target}" if target else "set:weather", "Отмена"),
    )


@router.message(Form.weather_interval)
async def save_interval(message: Message, state: FSMContext, user: dict[str, Any],
                        role: str) -> None:
    raw = (message.text or "").strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)(ч|h|мин|м|min|m)?", raw)
    if not match:
        await message.answer("❌ Введите число минут или, например, <code>2ч</code>.")
        return
    number = int(match.group(1))
    minutes = number * 60 if match.group(2) in ("ч", "h") else number
    if not 15 <= minutes <= 1440:
        await message.answer("❌ Допустимый интервал — от 15 минут до 24 часов.")
        return
    target = (await state.get_data()).get("weather_target") or ""
    subject = user
    if target:
        subject = storage.get_user(target)
        if subject is None or not roles.can_edit_user(role, subject.get("role")):
            await state.clear()
            await message.answer("❌ Недостаточно прав или пользователь не найден.")
            return

    subject["weather_mode"] = "interval"
    subject["weather_interval"] = minutes
    subject["last_weather"] = 0
    await storage.save(target or message.from_user.id)
    await state.clear()

    if target:
        await send_html(target, f"🌤 Администратор установил интервал погоды: <b>{minutes} мин</b>.")
        await message.answer(
            f"✅ Пользователю <code>{target}</code> интервал: <b>{minutes} мин</b>.",
            reply_markup=back_kb(f"usr:card:{target}", "◀️ К пользователю"),
        )
    else:
        await message.answer(
            f"✅ Интервал: <b>{minutes} мин</b>.", reply_markup=keyboards.settings_menu(user)
        )
RADAR_FILE_43
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/sources.py"
cat > "radar/handlers/sources.py" <<'RADAR_FILE_44'
"""Источники: предложение пользователем, очередь модерации, ручное добавление."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import config, exporting, keyboards, roles, sourcecheck, storage
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, safe_edit, send_html

router = Router(name="sources")

CHANNEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")

def normalize_channel(raw: str) -> str:
    value = raw.strip()
    value = re.sub(r"^(https?://)?(t\.me/|telegram\.me/)?@?", "", value, flags=re.I)
    return value.strip("/ ").split("/")[0].split("?")[0]


@router.callback_query(F.data == "src:suggest")
async def suggest(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await safe_edit(
        call,
        "📢 <b>Предложить источник</b>\nПришлите юзернейм публичного канала, например "
        "<code>saratovzhkh</code> или ссылку на него.",
        back_kb("menu:main", "Отмена"),
    )
    await state.set_state(Form.suggest_source)


@router.message(Form.suggest_source)
async def save_suggestion(message: Message, state: FSMContext) -> None:
    channel = normalize_channel(message.text or "")
    await state.clear()
    if not CHANNEL_RE.match(channel):
        await message.answer("❌ Некорректный юзернейм канала.", reply_markup=back_kb())
        return
    if channel in storage.channels() or channel in storage.pending():
        await message.answer("ℹ️ Источник уже в базе или в очереди.", reply_markup=back_kb())
        return
    storage.pending().append(channel)
    await storage.save()
    await message.answer(
        f"✅ Канал @{esc(channel)} отправлен модераторам.", reply_markup=back_kb()
    )


@router.callback_query(F.data == "src:queue")
async def queue(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    items = storage.pending()
    if not items:
        await safe_edit(call, "📥 Очередь пуста.", back_kb("menu:mod", "◀️ Назад"))
        return
    channel = items[0]
    await safe_edit(
        call,
        f"📥 <b>Очередь: {len(items)}</b>\nПроверка: @{esc(channel)}\n"
        f"https://t.me/{esc(channel)}",
        keyboards.queue_item(),
    )


@router.callback_query(F.data.in_({"src:approve", "src:reject"}))
async def decide(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    items = storage.pending()
    if not items:
        await queue(call, role)
        return
    channel = items.pop(0)
    if call.data.endswith("approve") and channel not in storage.channels():
        storage.channels().append(channel)
    await storage.save()
    await call.answer("Принято" if call.data.endswith("approve") else "Отклонено")
    await queue(call, role)


@router.callback_query(F.data == "src:list")
async def show_list(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    channels = "\n".join(f"• @{esc(item)}" for item in storage.channels()) or "— пусто —"
    feeds = "\n".join(f"• {esc(item)}" for item in storage.rss_feeds()) or "— пусто —"
    await safe_edit(
        call,
        f"📋 <b>Telegram-каналы</b>\n{channels}\n\n🌐 <b>RSS-ленты</b>\n{feeds}",
        back_kb("menu:mod", "◀️ Назад"),
    )


@router.callback_query(F.data == "src:add")
async def ask_channel(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        "➕ Пришлите юзернейм канала. Можно несколько через запятую или с новой строки.",
        back_kb("menu:mod", "Отмена"),
    )
    await state.set_state(Form.add_channel)


@router.message(Form.add_channel)
async def add_channel(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    if not roles.can_moderate_sources(role):
        return
    added, skipped = [], []
    for raw in re.split(r"[,\n;]+", message.text or ""):
        if not raw.strip():
            continue
        channel = normalize_channel(raw)
        if CHANNEL_RE.match(channel) and channel not in storage.channels():
            storage.channels().append(channel)
            added.append(channel)
        else:
            skipped.append(raw.strip())
    await storage.save()
    lines = []
    if added:
        lines.append("✅ Добавлены: " + ", ".join(f"@{esc(c)}" for c in added))
    if skipped:
        lines.append("⚠️ Пропущены: " + ", ".join(esc(s) for s in skipped))
    await message.answer("\n".join(lines) or "Ничего не добавлено",
                         reply_markup=back_kb("menu:mod", "◀️ Назад"))


@router.callback_query(F.data == "src:addrss")
async def ask_rss(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        "🌐 Пришлите адрес RSS-ленты СМИ или официального сайта "
        "(например <code>https://example.ru/rss</code>).",
        back_kb("menu:mod", "Отмена"),
    )
    await state.set_state(Form.add_rss)


@router.message(Form.add_rss)
async def add_rss(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    if not roles.can_moderate_sources(role):
        return
    added = []
    for raw in re.split(r"[,\s\n;]+", message.text or ""):
        url = raw.strip()
        if url.startswith(("http://", "https://")) and url not in storage.rss_feeds():
            storage.rss_feeds().append(url)
            added.append(url)
    await storage.save()
    text = (
        "✅ Добавлены ленты:\n" + "\n".join(f"• {esc(u)}" for u in added)
        if added else "⚠️ Корректных адресов не найдено."
    )
    await message.answer(text, reply_markup=back_kb("menu:mod", "◀️ Назад"))


# --------------------------------------------------------------------------
#  Выгрузка и загрузка списка источников
# --------------------------------------------------------------------------

MAX_IMPORT_BYTES = 1_000_000


@router.callback_query(F.data == "src:export")
async def export_sources(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer("Готовлю файл…")

    payload = exporting.export_bundle(
        storage.channels(), storage.rss_feeds(), storage.pending(), config.VERSION
    )
    document = BufferedInputFile(payload, filename=exporting.export_filename(config.VERSION))
    caption = (
        "📦 <b>Источники системы «Радар»</b>\n"
        f"Каналов: <b>{len(storage.channels())}</b>, "
        f"RSS: <b>{len(storage.rss_feeds())}</b>, "
        f"в очереди: <b>{len(storage.pending())}</b>\n\n"
        "<i>Файл читается будущими версиями бота. Чтобы восстановить список — "
        "просто пришлите его сюда.</i>"
    )
    await call.message.answer_document(document, caption=caption, reply_markup=back_kb("menu:mod", "◀️ Назад"))


@router.callback_query(F.data == "src:import")
async def ask_import(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Загрузка доступна администраторам.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        "⬆️ <b>Загрузка источников</b>\n\n"
        "Пришлите файл, выгруженный кнопкой «Скачать список». "
        "Принимаются также простой список каналов текстовым файлом и "
        "<code>db.json</code> от версий 2.x.\n\n"
        "<i>Существующие источники сохраняются — новые добавляются к ним.</i>",
        back_kb("menu:mod", "Отмена"),
    )


@router.message(F.document)
async def import_sources(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        await message.answer("⛔️ Загрузка источников доступна администраторам.")
        return

    document = message.document
    if document.file_size and document.file_size > MAX_IMPORT_BYTES:
        await message.answer("❌ Файл слишком большой (лимит 1 МБ).")
        return

    try:
        buffer = await message.bot.download(document)
        raw = buffer.read()
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"❌ Не удалось скачать файл: {esc(exc)}")
        return

    try:
        bundle = exporting.parse_bundle(raw)
    except exporting.ImportError_ as exc:
        await message.answer(f"❌ {esc(exc)}", reply_markup=back_kb("menu:mod", "◀️ Назад"))
        return

    added_channels, added_rss = exporting.merge(
        bundle, storage.channels(), storage.rss_feeds()
    )
    added_pending = 0
    for name in bundle.pending:
        if name not in storage.channels() and name not in storage.pending():
            storage.pending().append(name)
            added_pending += 1
    await storage.save()

    lines = [
        "✅ <b>Список загружен</b>",
        f"Из файла: каналов {len(bundle.channels)}, лент {len(bundle.rss)}"
        + (f" (источник: {esc(bundle.origin)})" if bundle.origin else ""),
        f"Добавлено: <b>{added_channels}</b> каналов, <b>{added_rss}</b> лент",
    ]
    if added_pending:
        lines.append(f"В очередь модерации: <b>{added_pending}</b>")
    if not (added_channels or added_rss or added_pending):
        lines.append("<i>Все источники из файла уже были в базе.</i>")
    if bundle.warnings:
        lines.append("")
        lines.append("⚠️ " + "\n⚠️ ".join(esc(item) for item in bundle.warnings[:8]))
        if len(bundle.warnings) > 8:
            lines.append(f"…и ещё {len(bundle.warnings) - 8} замечаний")

    await message.answer("\n".join(lines), reply_markup=back_kb("menu:mod", "◀️ Назад"))


# --------------------------------------------------------------------------
#  Проверка доступности источников
# --------------------------------------------------------------------------

# Итог последней проверки на пользователя: нужен, чтобы кнопка «убрать
# недоступные» работала по свежему списку, а не пересканировала всё заново.
_last_check: dict[str, list[tuple[str, str]]] = {}


@router.callback_query(F.data == "src:check")
async def check_sources(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    channels = list(storage.channels())
    feeds = list(storage.rss_feeds())
    vk_groups = list(storage.vk_groups())
    total = len(channels) + len(feeds) + len(vk_groups)
    if not total:
        await call.answer("Источников нет.", show_alert=True)
        return

    await call.answer("Начинаю проверку…")
    estimate = int(total * (sourcecheck.POLITE_PAUSE + 1.2))
    notice = await call.message.answer(
        f"🔍 Проверяю источники: <b>{total}</b>\n"
        f"<i>Займёт примерно {estimate // 60} мин {estimate % 60} с — "
        f"запросы идут с паузой, чтобы не выглядеть перебором.</i>"
    )

    last_shown = 0

    async def progress(done: int, count: int, current: str) -> None:
        # Правим сообщение не чаще, чем раз в 10 источников: Telegram
        # ограничивает частоту редактирования.
        nonlocal last_shown
        if done - last_shown < 10 and done != count:
            return
        last_shown = done
        try:
            await notice.edit_text(
                f"🔍 Проверяю источники: <b>{done}/{count}</b>\n"
                f"<i>сейчас: {esc(current)}</i>"
            )
        except Exception:  # noqa: BLE001
            pass

    report = await sourcecheck.check_all(channels, feeds, vk_groups, progress=progress)

    # Отмечаем результат в базе — по нему потом видно проблемные источники
    for item in report.statuses:
        try:
            await storage_repo_mark(item)
        except Exception:  # noqa: BLE001
            pass

    try:
        await notice.delete()
    except Exception:  # noqa: BLE001
        pass

    text = sourcecheck.render(report)
    if report.dead:
        text += "\n\n<i>Удалить недоступные можно кнопкой ниже.</i>"
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🗑 Убрать недоступные ({len(report.dead)})",
                    callback_data="src:drop_dead",
                )],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:mod")],
            ]
        )
    else:
        markup = back_kb("menu:mod", "◀️ Назад")

    _last_check[str(call.from_user.id)] = [
        (item.kind, item.ref) for item in report.dead
    ]
    await send_html(call.message.chat.id, text, markup)


async def storage_repo_mark(item) -> None:
    """Отмечает результат проверки в таблице источников."""
    from ..db import repo

    await repo.mark_source(item.kind, item.ref, error="" if item.state != "dead" else item.note)


@router.callback_query(F.data == "src:drop_dead")
async def drop_dead(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    dead = _last_check.get(str(call.from_user.id)) or []
    if not dead:
        await call.answer("Список устарел — запустите проверку заново.", show_alert=True)
        return

    removed = 0
    for kind, ref in dead:
        if kind == "tg" and ref in storage.channels():
            storage.channels().remove(ref)
            removed += 1
        elif kind == "rss" and ref in storage.rss_feeds():
            storage.rss_feeds().remove(ref)
            removed += 1
        elif kind == "vk" and ref in storage.vk_groups():
            storage.vk_groups().remove(ref)
            removed += 1

    await storage.save()
    _last_check.pop(str(call.from_user.id), None)
    await call.answer(f"Удалено источников: {removed}")
    await safe_edit(
        call,
        f"🗑 Удалено недоступных источников: <b>{removed}</b>.\n"
        f"Осталось: каналов {len(storage.channels())}, лент {len(storage.rss_feeds())}.",
        back_kb("menu:mod", "◀️ Назад"),
    )


@router.message(Command("checksources"))
async def cmd_check_sources(message: Message, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await message.answer("⛔️ Проверка источников доступна модераторам и выше.")
        return

    channels = list(storage.channels())
    feeds = list(storage.rss_feeds())
    total = len(channels) + len(feeds)
    if not total:
        await message.answer("Источников нет.")
        return

    notice = await message.answer(f"🔍 Проверяю источники: <b>{total}</b>…")
    report = await sourcecheck.check_all(channels, feeds, list(storage.vk_groups()))
    try:
        await notice.delete()
    except Exception:  # noqa: BLE001
        pass
    await send_html(message.chat.id, sourcecheck.render(report), back_kb("menu:mod", "◀️ Назад"))
RADAR_FILE_44
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/users.py"
cat > "radar/handlers/users.py" <<'RADAR_FILE_45'
"""Пользователи: список, карточка, смена роли, удаление, правка локаций и настроек."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import aiohttp
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import config, geocode, keyboards, roles, storage
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, bot, safe_edit, send_html
from .locations import locations_text

router = Router(name="users")

PAGE_SIZE = 8

def _page(page: int) -> tuple[list[tuple[str, str, int]], int]:
    records = sorted(
        storage.users().items(),
        key=lambda item: (-roles.level(item[1].get("role")), item[0]),
    )
    pages = max(1, (len(records) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = records[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    items = [
        (uid, user.get("role", "user"), len(user.get("locs") or []))
        for uid, user in chunk
    ]
    return items, pages


@router.callback_query(F.data.startswith("usr:list:"))
async def list_users(call: CallbackQuery, role: str) -> None:
    if not roles.is_moderator(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    try:
        page = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        page = 0
    items, pages = _page(page)
    page = max(0, min(page, pages - 1))
    lines = [f"👥 <b>Пользователи</b> — всего {len(storage.users())} (стр. {page + 1}/{pages})"]
    for uid, user_role, count in items:
        user = storage.get_user(uid) or {}
        username = f" @{esc(user.get('username'))}" if user.get("username") else ""
        lines.append(f"<code>{uid}</code>{username} — {roles.title(user_role)}, локаций: {count}")
    lines.append("\n<i>Нажмите на пользователя, чтобы открыть карточку.</i>")
    await safe_edit(call, "\n".join(lines), keyboards.users_page(items, page, pages))


def _card_text(uid: str) -> str:
    user = storage.get_user(uid) or {}
    settings = user.get("settings") or {}
    active = ", ".join(key for key, value in settings.items() if value) or "нет"
    username = f"@{esc(user.get('username'))}" if user.get("username") else "—"
    return "\n".join(
        [
            f"👤 <b>Пользователь</b> <code>{uid}</code>",
            f"Ник: {username}",
            f"Роль: {roles.title(user.get('role'))}",
            f"Локаций: <b>{len(user.get('locs') or [])}</b>",
            f"Категории оповещений: {esc(active)}",
            f"Погода: {esc(keyboards.weather_label(user))}",
        ]
    )


@router.callback_query(F.data.startswith("usr:card:"))
async def card(call: CallbackQuery, role: str) -> None:
    if not roles.is_moderator(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call, _card_text(target), keyboards.user_card(target, user.get("role", "user"), role)
    )


@router.callback_query(F.data.startswith("usr:locs:"))
async def user_locations(call: CallbackQuery, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_edit_user(role, user.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        locations_text(user, owner_label=f"<code>{target}</code>"),
        keyboards.locations_menu(user.get("locs") or [], owner=target),
    )


@router.callback_query(F.data.startswith("usr:sets:"))
async def user_settings(call: CallbackQuery, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_edit_user(role, user.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        f"⚙️ <b>Оповещения пользователя</b> <code>{target}</code>",
        keyboards.settings_menu(user, target),
    )


@router.callback_query(F.data.startswith("usr:role:"))
async def change_role(call: CallbackQuery, role: str) -> None:
    parts = call.data.split(":")
    target, new_role = parts[2], parts[3]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if target == str(call.from_user.id):
        await call.answer("Нельзя менять роль самому себе.", show_alert=True)
        return
    if not roles.can_assign(role, user.get("role"), new_role):
        await call.answer("Недостаточно прав для этой роли.", show_alert=True)
        return

    user["role"] = new_role
    await storage.save()
    await call.answer(f"Роль изменена: {new_role}")
    await safe_edit(call, _card_text(target), keyboards.user_card(target, new_role, role))
    await send_html(
        target, f"ℹ️ Ваша роль в системе «Радар» изменена на {roles.title(new_role)}."
    )


@router.callback_query(F.data.startswith("usr:del:"))
async def ask_delete(call: CallbackQuery, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_delete_user(role, user.get("role")):
        await call.answer("Удаление доступно администраторам.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        f"⚠️ Удалить пользователя <code>{target}</code> "
        f"({roles.title(user.get('role'))}) вместе со всеми локациями?",
        keyboards.confirm("usr:delok", target, f"usr:card:{target}"),
    )


@router.callback_query(F.data.startswith("usr:delok:"))
async def confirm_delete(call: CallbackQuery, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_delete_user(role, user.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await storage.drop_user(target)
    await call.answer("Пользователь удалён")
    items, pages = _page(0)
    await safe_edit(
        call,
        f"✅ Пользователь <code>{target}</code> удалён.",
        keyboards.users_page(items, 0, pages),
    )


@router.callback_query(F.data == "usr:invite")
async def invite(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    me = await bot.get_me()
    await safe_edit(
        call,
        "🔗 <b>Инвайт-ссылка</b>\n"
        f"https://t.me/{me.username}?start=join\n\n"
        "<i>Перешедший по ней получает роль «Пользователь».</i>",
        back_kb("menu:admin", "◀️ Назад"),
    )


# --------------------------------------------------------------------------
#  Добавление локации пользователю силами администрации
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("usr:addloc:"))
async def ask_location(call: CallbackQuery, state: FSMContext, role: str) -> None:
    target = call.data.split(":")[2]
    user = storage.get_user(target)
    if user is None:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not roles.can_edit_user(role, user.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    await call.answer()
    await state.set_state(Form.admin_add_location)
    await state.update_data(target_id=target)
    hint = f" Город по умолчанию — {esc(config.DEFAULT_CITY)}." if config.DEFAULT_CITY else ""
    await safe_edit(
        call,
        f"➕ <b>Локация для</b> <code>{target}</code>\n\n"
        f"Пришлите адрес текстом, например <code>улица Чапаева, 12</code>.{hint}\n"
        "Можно также переслать или отправить геопозицию — она будет добавлена "
        "этому пользователю.\n\n<i>/cancel — отмена.</i>",
        back_kb(f"usr:card:{target}", "Отмена"),
    )


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=25),
        headers={"User-Agent": config.USER_AGENT},
    )


async def _attach(target: str, info: dict[str, str], lat: float, lon: float) -> dict:
    location = storage.new_location(
        info.get("name") or f"{lat:.5f}, {lon:.5f}", lat, lon,
        street=info.get("street", ""), house=info.get("house", ""),
        city=info.get("city", ""), district=info.get("district", ""),
        region=info.get("region", ""),
    )
    storage.get_user(target)["locs"].append(location)
    await storage.save()
    return location


async def _report(message: Message, target: str, location: dict) -> None:
    details = ", ".join(
        part for part in (location["district"], location["city"], location["region"]) if part
    )
    text = (
        f"✅ Локация <b>{esc(location['name'])}</b> добавлена пользователю "
        f"<code>{target}</code>."
    )
    if details:
        text += f"\n<i>{esc(details)}</i>"
    if not location["street"]:
        text += "\n⚠️ <i>Улица не определена — адресные оповещения ЖКХ могут быть неточными.</i>"
    await message.answer(text, reply_markup=back_kb(f"usr:card:{target}", "◀️ К пользователю"))
    await send_html(
        target,
        f"📍 Администратор добавил вам локацию <b>{esc(location['name'])}</b>.\n"
        "Оповещения по ней уже включены — управлять можно в разделе «Мои локации».",
    )


@router.message(Form.admin_add_location, F.location)
async def add_by_geo(message: Message, state: FSMContext, role: str) -> None:
    data = await state.get_data()
    target = data.get("target_id", "")
    user = storage.get_user(target)
    if user is None or not roles.can_edit_user(role, user.get("role")):
        await state.clear()
        await message.answer("❌ Пользователь не найден или недостаточно прав.")
        return

    lat, lon = message.location.latitude, message.location.longitude
    async with _session() as session:
        info = await geocode.reverse(session, lat, lon)
    await state.clear()
    await _report(message, target, await _attach(target, info, lat, lon))


@router.message(Form.admin_add_location, F.text)
async def add_by_address(message: Message, state: FSMContext, role: str) -> None:
    query = (message.text or "").strip()
    if query.startswith("/"):
        return

    data = await state.get_data()
    target = data.get("target_id", "")
    user = storage.get_user(target)
    if user is None or not roles.can_edit_user(role, user.get("role")):
        await state.clear()
        await message.answer("❌ Пользователь не найден или недостаточно прав.")
        return

    async with _session() as session:
        found = await geocode.forward(session, query, config.DEFAULT_CITY)

    if not found:
        await message.answer(
            "❌ Адрес не найден. Уточните формулировку — например, "
            "<code>Саратов, улица Чапаева, 12</code>. /cancel — отмена."
        )
        return

    if len(found) == 1:
        await state.clear()
        item = found[0]
        location = await _attach(target, item, float(item["lat"]), float(item["lon"]))
        await _report(message, target, location)
        return

    await state.update_data(candidates=found)
    lines = [f"🔎 <b>Найдено вариантов: {len(found)}</b>", ""]
    lines += [
        f"{index + 1}. {esc(item['display'][:120])}" for index, item in enumerate(found)
    ]
    lines.append("")
    lines.append("<i>Выберите нужный.</i>")
    await message.answer("\n".join(lines), reply_markup=keyboards.geocode_choices(found, target))


@router.callback_query(F.data.startswith("usr:pickloc:"))
async def pick_location(call: CallbackQuery, state: FSMContext, role: str) -> None:
    parts = call.data.split(":")
    target, index = parts[2], int(parts[3])
    user = storage.get_user(target)
    if user is None or not roles.can_edit_user(role, user.get("role")):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    candidates = (await state.get_data()).get("candidates") or []
    if index >= len(candidates):
        await call.answer("Список устарел, начните заново.", show_alert=True)
        await state.clear()
        return

    item = candidates[index]
    await state.clear()
    await call.answer("Добавляю…")
    location = await _attach(target, item, float(item["lat"]), float(item["lon"]))
    await safe_edit(
        call,
        f"✅ Локация <b>{esc(location['name'])}</b> добавлена пользователю "
        f"<code>{target}</code>.",
        keyboards.user_card(target, user.get("role", "user"), role),
    )
    await send_html(
        target,
        f"📍 Администратор добавил вам локацию <b>{esc(location['name'])}</b>.\n"
        "Оповещения по ней уже включены — управлять можно в разделе «Мои локации».",
    )
RADAR_FILE_45
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/features.py"
cat > "radar/handlers/features.py" <<'RADAR_FILE_46'
"""Управление возможностями системы. Доступно только суперадминистратору.

Флаги переключаются на живой системе: изменение сразу попадает в память
и в базу, перезапуск контейнера не нужен.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import features, roles
from ..db import repo
from ..textutils import esc
from ..tg import back_kb, safe_edit

router = Router(name="features")


def _menu(group: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if group is None:
        for name in features.GROUPS:
            items = features.by_group()[name]
            active = sum(1 for flag in items if features.enabled(flag.key))
            rows.append([
                InlineKeyboardButton(
                    text=f"{name} — {active}/{len(items)}",
                    callback_data=f"feat:group:{name}",
                )
            ])
        rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    for flag in features.by_group().get(group, []):
        if flag.locked:
            mark = "🔒"
        else:
            mark = "✅" if features.enabled(flag.key) else "❌"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {flag.title}",
                callback_data=f"feat:toggle:{flag.key}:{group}",
            )
        ])
    rows.append([InlineKeyboardButton(text="◀️ К разделам", callback_data="feat:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _group_text(group: str) -> str:
    lines = [f"⚙️ <b>{esc(group)}</b>", ""]
    for flag in features.by_group().get(group, []):
        state = "🔒 всегда включено" if flag.locked else (
            "✅ включено" if features.enabled(flag.key) else "❌ выключено"
        )
        since = f" <i>(с {flag.since})</i>" if flag.since else ""
        lines.append(f"<b>{esc(flag.title)}</b>{since} — {state}")
        lines.append(f"<i>{esc(flag.description)}</i>")
        lines.append("")
    return "\n".join(lines).strip()


@router.message(Command("features"))
async def cmd_features(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Управление возможностями доступно суперадминистратору.")
        return
    active = sum(1 for flag in features.FLAGS if features.enabled(flag.key))
    await message.answer(
        f"⚙️ <b>Возможности системы</b>\nВключено {active} из {len(features.FLAGS)}.\n\n"
        "<i>Изменения применяются сразу, перезапуск не нужен.</i>",
        reply_markup=_menu(),
    )


@router.callback_query(F.data == "feat:list")
async def show_groups(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    active = sum(1 for flag in features.FLAGS if features.enabled(flag.key))
    await safe_edit(
        call,
        f"⚙️ <b>Возможности системы</b>\nВключено {active} из {len(features.FLAGS)}.",
        _menu(),
    )


@router.callback_query(F.data.startswith("feat:group:"))
async def show_group(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    group = call.data.split(":", 2)[2]
    await call.answer()
    await safe_edit(call, _group_text(group), _menu(group))


@router.callback_query(F.data.startswith("feat:toggle:"))
async def toggle(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    parts = call.data.split(":")
    key, group = parts[2], parts[3]

    flag = features.resolve(key)
    if flag is None:
        await call.answer("Неизвестная возможность.", show_alert=True)
        return
    if flag.locked:
        await call.answer("Это ядро системы, выключить нельзя.", show_alert=True)
        return

    value = not features.enabled(flag.key)
    features.set_local(flag.key, value)
    await repo.set_feature(flag.key, value, call.from_user.id)
    await call.answer(f"{flag.title}: {'включено' if value else 'выключено'}")
    await safe_edit(call, _group_text(group), _menu(group))
RADAR_FILE_46
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/logs.py"
cat > "radar/handlers/logs.py" <<'RADAR_FILE_47'
"""Журналы в интерфейсе бота. Доступно только суперадминистратору.

Журналы содержат идентификаторы пользователей, адреса и внутренние ошибки,
поэтому выдаются исключительно владельцу системы — ни администраторам,
ни модераторам.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import logs, roles
from ..textutils import esc, split_text
from ..tg import back_kb, safe_edit, send_html

log = logging.getLogger("radar.handlers.logs")
router = Router(name="logs")

KIND_TITLES = {
    "bot": "🤖 Журналы бота",
    "installer": "📦 Журналы установки",
    "doctor": "🩺 Отчёты диагностики",
    "other": "📄 Прочее",
}


def _menu() -> InlineKeyboardMarkup:
    grouped = logs.by_kind()
    rows: list[list[InlineKeyboardButton]] = []

    for kind, title in KIND_TITLES.items():
        items = grouped.get(kind)
        if not items:
            continue
        rows.append([
            InlineKeyboardButton(
                text=f"{title} ({len(items)})", callback_data=f"log:kind:{kind}"
            )
        ])

    if grouped:
        rows.append([
            InlineKeyboardButton(text="📥 Скачать всё архивом", callback_data="log:all"),
        ])
        rows.append([
            InlineKeyboardButton(text="🧹 Очистить журналы", callback_data="log:purge"),
        ])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _overview() -> str:
    items = logs.collect()
    if not items:
        return (
            "📋 <b>Журналы</b>\n\nПока пусто. Журнал бота появится после запуска, "
            "журнал установки — после ближайшего обновления."
        )

    total = logs.total_size()
    lines = [
        "📋 <b>Журналы</b>",
        f"Файлов: <b>{len(items)}</b>, общий объём: <b>{total // 1024} КБ</b>",
        "",
    ]
    for item in items[:12]:
        lines.append(
            f"• <code>{esc(item.name)}</code> — {item.size_human}, {item.age_human}"
        )
    if len(items) > 12:
        lines.append(f"…и ещё {len(items) - 12}")
    return "\n".join(lines)


def _files_menu(kind: str) -> InlineKeyboardMarkup:
    items = logs.by_kind().get(kind, [])
    rows = [
        [
            InlineKeyboardButton(
                text=f"📄 {item.name[:38]} ({item.size_human})",
                callback_data=f"log:get:{item.name}",
            )
        ]
        for item in items[:15]
    ]
    rows.append([
        InlineKeyboardButton(text="📥 Скачать группой", callback_data=f"log:pack:{kind}"),
        InlineKeyboardButton(text="🧹 Удалить группу", callback_data=f"log:clear:{kind}"),
    ])
    rows.append([InlineKeyboardButton(text="◀️ К журналам", callback_data="log:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------
#  Команды
# --------------------------------------------------------------------------

@router.message(Command("logs"))
async def cmd_logs(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Журналы доступны только суперадминистратору.")
        return
    await message.answer(_overview(), reply_markup=_menu())


@router.message(Command("logtail"))
async def cmd_logtail(message: Message, role: str) -> None:
    """Последние строки журнала бота прямо в чат — без скачивания файла."""
    if not roles.is_superadmin(role):
        return
    items = logs.by_kind().get("bot", [])
    if not items:
        await message.answer("Журнал бота ещё не создан.")
        return

    parts = (message.text or "").split()
    try:
        count = min(200, max(10, int(parts[1]))) if len(parts) > 1 else 60
    except ValueError:
        count = 60

    text = logs.tail(items[0], count)
    for chunk in split_text(f"<pre>{esc(text)}</pre>"):
        await message.answer(chunk)


@router.message(Command("logclear"))
async def cmd_logclear(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        return
    removed, freed = logs.purge()
    await message.answer(
        f"🧹 Удалено файлов: <b>{removed}</b>, освобождено <b>{freed // 1024} КБ</b>.\n"
        "<i>Текущий журнал бота сохранён — он открыт на запись.</i>"
    )


# --------------------------------------------------------------------------
#  Меню
# --------------------------------------------------------------------------

@router.callback_query(F.data == "log:list")
async def show_logs(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _overview(), _menu())


@router.callback_query(F.data.startswith("log:kind:"))
async def show_kind(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    kind = call.data.split(":")[2]
    items = logs.by_kind().get(kind, [])
    await call.answer()
    lines = [KIND_TITLES.get(kind, kind), ""]
    lines += [
        f"• <code>{esc(item.name)}</code> — {item.size_human}, {item.age_human}"
        for item in items[:15]
    ] or ["— пусто —"]
    await safe_edit(call, "\n".join(lines), _files_menu(kind))


@router.callback_query(F.data.startswith("log:get:"))
async def send_one(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    name = call.data.split(":", 2)[2]
    item = logs.find(name)
    if item is None:
        await call.answer("Файл не найден.", show_alert=True)
        return

    await call.answer("Готовлю файл…")
    payload = logs.read_bytes(item)
    if payload is None:
        await send_html(call.message.chat.id, "❌ Не удалось прочитать файл.")
        return
    await call.message.answer_document(
        BufferedInputFile(payload, filename=item.name),
        caption=f"📄 <code>{esc(item.name)}</code> — {item.size_human}",
        reply_markup=back_kb("log:list", "◀️ К журналам"),
    )


@router.callback_query(F.data.startswith("log:pack:"))
async def send_group(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    kind = call.data.split(":")[2]
    await _send_archive(call, {kind})


@router.callback_query(F.data == "log:all")
async def send_all(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await _send_archive(call, None)


async def _send_archive(call: CallbackQuery, kinds: set[str] | None) -> None:
    await call.answer("Собираю архив…")
    result = logs.archive(kinds)
    if result is None:
        await send_html(call.message.chat.id, "Журналов для выгрузки нет.")
        return
    payload, filename, count = result
    await call.message.answer_document(
        BufferedInputFile(payload, filename=filename),
        caption=(
            f"📥 <b>Журналы системы</b>\nФайлов: {count}, "
            f"размер архива: {len(payload) // 1024} КБ\n\n"
            "<i>Журналы контейнеров Docker сюда не входят — соберите их "
            "на сервере: <code>bash ~/radar_bot/collect-logs.sh</code></i>"
        ),
        reply_markup=back_kb("log:list", "◀️ К журналам"),
    )


@router.callback_query(F.data == "log:purge")
async def confirm_purge(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Удалить", callback_data="log:purgeok"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="log:list"),
            ]
        ]
    )
    await safe_edit(
        call,
        "🧹 <b>Очистка журналов</b>\n\nБудут удалены все файлы, кроме текущего "
        "журнала бота — он открыт на запись.\n\nПродолжить?",
        kb,
    )


@router.callback_query(F.data == "log:purgeok")
async def do_purge(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    removed, freed = logs.purge()
    await call.answer(f"Удалено файлов: {removed}")
    await safe_edit(
        call,
        f"🧹 Удалено: <b>{removed}</b>, освобождено <b>{freed // 1024} КБ</b>.\n\n"
        + _overview(),
        _menu(),
    )


@router.callback_query(F.data.startswith("log:clear:"))
async def clear_kind(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    kind = call.data.split(":")[2]
    removed, freed = logs.purge({kind})
    await call.answer(f"Удалено файлов: {removed}")
    await safe_edit(call, _overview(), _menu())
RADAR_FILE_47
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/sos.py"
cat > "radar/handlers/sos.py" <<'RADAR_FILE_48'
"""Кнопка SOS в интерфейсе бота."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import config, features, geocode, roles, sos, storage
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, bot, safe_edit, send_html

log = logging.getLogger("radar.handlers.sos")
router = Router(name="sos")


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20),
        headers={"User-Agent": config.USER_AGENT},
    )


def _menu(user: dict) -> InlineKeyboardMarkup:
    contacts = sos.contacts_of(user)
    rows: list[list[InlineKeyboardButton]] = []

    for contact in contacts:
        mark = "✅" if contact.confirmed else "⏳"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {contact.title[:30]}",
                callback_data=f"sos:contact:{contact.key}",
            )
        ])

    if len(contacts) < sos.MAX_CONTACTS:
        rows.append([
            InlineKeyboardButton(text="➕ Добавить контакт", callback_data="sos:add")
        ])

    if sos.confirmed_contacts(user) or contacts:
        rows.append([
            InlineKeyboardButton(text="🆘 Отправить сигнал", callback_data="sos:fire")
        ])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _overview(user: dict) -> str:
    contacts = sos.contacts_of(user)
    lines = ["🆘 <b>Экстренная помощь</b>", ""]

    if not contacts:
        lines.append(
            "Доверенные контакты не заданы. Добавьте человека, которому уйдёт "
            "ваша геопозиция, если вы нажмёте кнопку SOS."
        )
    else:
        lines.append("<b>Доверенные контакты:</b>")
        for contact in contacts:
            state = "готов принимать сигнал" if contact.confirmed else (
                "не подтверждён — не открывал бота"
            )
            mark = "✅" if contact.confirmed else "⏳"
            lines.append(f"{mark} {esc(contact.title)} — <i>{state}</i>")

        if not sos.confirmed_contacts(user):
            lines.append("")
            lines.append(
                "⚠️ Ни один контакт не подтверждён. Telegram не даёт боту писать "
                "первым — контакт должен открыть бота по вашей ссылке. Пока этого "
                "не произошло, сигнал уйдёт администраторам системы."
            )

    lines.append("")
    lines.append(
        "<b>Бот не заменяет экстренные службы.</b> При угрозе жизни звоните 112."
    )
    return "\n".join(lines)


@router.callback_query(F.data == "sos:menu")
async def show_menu(call: CallbackQuery, state: FSMContext, user: dict) -> None:
    if not features.enabled("sos"):
        await call.answer("Функция отключена суперадминистратором.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, _overview(user), _menu(user))


@router.message(Command("sos"))
async def cmd_sos(message: Message, state: FSMContext, user: dict) -> None:
    if not features.enabled("sos"):
        await message.answer("Функция SOS отключена.")
        return
    await state.clear()
    await message.answer(_overview(user), reply_markup=_menu(user))


# --------------------------------------------------------------------------
#  Контакты
# --------------------------------------------------------------------------

@router.callback_query(F.data == "sos:add")
async def ask_contact(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(Form.sos_contact)
    await safe_edit(
        call,
        "➕ <b>Доверенный контакт</b>\n\n"
        "Пришлите <b>числовой ID</b> человека в Telegram — его можно узнать "
        "у @userinfobot, — либо перешлите сюда любое его сообщение.\n\n"
        "После этого вы получите ссылку-приглашение: контакт откроет её "
        "и нажмёт «Старт». Без этого шага Telegram не позволит боту "
        "написать ему первым.\n\n<i>/cancel — отмена.</i>",
        back_kb("sos:menu", "Отмена"),
    )


@router.message(Form.sos_contact)
async def save_contact(message: Message, state: FSMContext, user: dict) -> None:
    key = ""
    title = ""

    forwarded = getattr(message, "forward_from", None)
    if forwarded is not None:
        key = str(forwarded.id)
        title = forwarded.full_name or forwarded.username or key
    else:
        text = (message.text or "").strip()
        if text.startswith("/"):
            return
        if text.isdigit() and len(text) >= 5:
            key = text
            title = f"ID {text}"
        else:
            await message.answer(
                "❌ Нужен числовой ID или пересланное сообщение.\n"
                "<i>Если пересылка не сработала — у человека закрыт профиль "
                "в настройках приватности, попросите у него ID через @userinfobot.</i>"
            )
            return

    if key == str(message.from_user.id):
        await message.answer("❌ Нельзя указать самого себя.")
        return

    contact, error = sos.add_contact(user, key, title)
    await state.clear()
    if contact is None:
        await message.answer(f"❌ {esc(error)}", reply_markup=back_kb("sos:menu", "◀️ Назад"))
        return

    await storage.save(message.from_user.id)

    me = await bot.get_me()
    sender = message.from_user.full_name or "Пользователь"
    invite = sos.build_invite_text(sender, me.username, contact.invite)

    await message.answer(
        f"✅ Контакт <b>{esc(contact.title)}</b> добавлен.\n\n"
        "Перешлите ему сообщение ниже — без подтверждения сигнал не дойдёт.",
        reply_markup=back_kb("sos:menu", "◀️ К настройкам"),
    )
    await message.answer(invite)


@router.callback_query(F.data.startswith("sos:contact:"))
async def contact_card(call: CallbackQuery, user: dict) -> None:
    key = call.data.split(":", 2)[2]
    contact = next((item for item in sos.contacts_of(user) if item.key == key), None)
    if contact is None:
        await call.answer("Контакт не найден.", show_alert=True)
        return

    await call.answer()
    me = await bot.get_me()
    lines = [
        f"👤 <b>{esc(contact.title)}</b>",
        f"Состояние: {'подтверждён' if contact.confirmed else 'ожидает подтверждения'}",
    ]
    if not contact.confirmed:
        lines.append("")
        lines.append(
            f"Ссылка-приглашение:\nhttps://t.me/{me.username}?start=sos_{contact.invite}"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить контакт", callback_data=f"sos:drop:{key}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sos:menu")],
    ])
    await safe_edit(call, "\n".join(lines), kb)


@router.callback_query(F.data.startswith("sos:drop:"))
async def drop_contact(call: CallbackQuery, user: dict) -> None:
    key = call.data.split(":", 2)[2]
    if sos.remove_contact(user, key):
        await storage.save(call.from_user.id)
        await call.answer("Контакт удалён")
    else:
        await call.answer("Контакт не найден", show_alert=True)
    await safe_edit(call, _overview(user), _menu(user))


# --------------------------------------------------------------------------
#  Отправка сигнала
# --------------------------------------------------------------------------

@router.callback_query(F.data == "sos:fire")
async def ask_location(call: CallbackQuery, state: FSMContext) -> None:
    if not features.enabled("sos"):
        await call.answer("Функция отключена.", show_alert=True)
        return
    await call.answer()
    await state.set_state(Form.sos_location)
    await safe_edit(
        call,
        "🆘 <b>Отправка сигнала</b>\n\n"
        "Пришлите <b>геопозицию</b>: Скрепка → Геопозиция.\n"
        "Лучше выбрать «Транслировать» — тогда контакт будет видеть перемещение.\n\n"
        "Можно добавить подпись к геопозиции — она уйдёт вместе с сигналом.\n\n"
        "<i>/cancel — отмена. При угрозе жизни звоните 112.</i>",
        back_kb("sos:menu", "Отмена"),
    )


@router.message(Form.sos_location, F.location)
async def fire_alert(message: Message, state: FSMContext, user: dict) -> None:
    await state.clear()
    lat = message.location.latitude
    lon = message.location.longitude
    note = (message.caption or "").strip()

    address = ""
    try:
        async with _session() as session:
            info = await geocode.reverse(session, lat, lon)
            address = ", ".join(
                part for part in (info.get("name"), info.get("city")) if part
            )
    except Exception:  # noqa: BLE001
        log.warning("Адрес для SOS не определён", exc_info=True)

    owner = str(message.from_user.id)
    sender = message.from_user.full_name or "Пользователь"
    link = f"@{message.from_user.username}" if message.from_user.username else ""

    text = sos.build_alert(sender, link, lat, lon, address, note)
    contacts = sos.confirmed_contacts(user)
    failed: list[str] = []

    for contact in contacts:
        delivered = await send_html(contact.key, text)
        if delivered:
            try:
                await bot.send_location(int(contact.key), lat, lon)
            except Exception:  # noqa: BLE001
                pass
        else:
            failed.append(contact.title)

    # Запасной адресат: если подтверждённых контактов нет или не дошло
    if not contacts or len(failed) == len(contacts):
        admins = [
            uid for uid, data in storage.users().items()
            if roles.is_admin(data.get("role")) and uid != owner
        ]
        for uid in admins:
            await send_html(
                uid,
                "⚠️ <b>Сигнал SOS без доверенных контактов</b>\n\n" + text,
            )
        if admins:
            log.warning("SOS от %s ушёл администраторам: контактов нет", owner)

    sos.start_alert(owner, lat, lon, address, note)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я в порядке — отбой", callback_data="sos:cancel")],
    ])
    await message.answer(sos.build_receipt(contacts, failed), reply_markup=kb)


@router.message(Form.sos_location)
async def need_location(message: Message) -> None:
    if (message.text or "").startswith("/"):
        return
    await message.answer(
        "Нужна именно геопозиция: Скрепка → Геопозиция.\n"
        "<i>/cancel — отмена.</i>"
    )


@router.callback_query(F.data == "sos:cancel")
async def cancel_alert(call: CallbackQuery, user: dict) -> None:
    owner = str(call.from_user.id)
    if not sos.stop_alert(owner):
        await call.answer("Активных сигналов нет.")
        return

    await call.answer("Отбой отправлен")
    sender = call.from_user.full_name or "Пользователь"
    notice = sos.build_cancel_notice(sender)
    for contact in sos.confirmed_contacts(user):
        await send_html(contact.key, notice)

    await safe_edit(
        call,
        "✅ <b>Отбой</b>\n\nПовторные сигналы прекращены, контакты уведомлены.",
        back_kb(),
    )
RADAR_FILE_48
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/assistant.py"
cat > "radar/handlers/assistant.py" <<'RADAR_FILE_49'
"""ИИ-ассистент в диалоге. Доступен начиная с роли «модератор».

Роутер подключается последним: перехватывает любой необработанный текст.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from collections import deque

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import ai, keyboards, roles
from ..textutils import esc, md_to_html, split_text, strip_tags
from ..tg import back_kb, safe_edit, send_html

log = logging.getLogger("radar.assistant")
router = Router(name="assistant")

MAX_HISTORY = 8
_history: dict[str, deque] = {}

def history_of(uid: str) -> deque:
    if uid not in _history:
        _history[uid] = deque(maxlen=MAX_HISTORY)
    return _history[uid]


async def run(message: Message, question: str) -> None:
    uid = str(message.from_user.id)
    if not ai.ENABLED:
        await message.answer(
            "❌ ИИ-ассистент недоступен: в <code>.env</code> не задан "
            "<code>GEMINI_API_KEY</code>."
        )
        return

    placeholder = await message.answer("🧠 <i>Думаю…</i>")
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:  # noqa: BLE001
        pass

    history = history_of(uid)
    try:
        answer = await ai.assistant(list(history), question)
    except ai.AIError as exc:
        log.warning("Ассистент: %s", exc)
        try:
            await placeholder.edit_text(f"❌ <b>Ошибка ИИ:</b> {esc(exc)}")
        except TelegramBadRequest:
            pass
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Неожиданная ошибка ассистента")
        try:
            await placeholder.edit_text(f"❌ Неожиданная ошибка: {esc(exc)}")
        except TelegramBadRequest:
            pass
        return

    history.append(ai.user_turn(question))
    history.append(ai.model_turn(answer))

    chunks = split_text(md_to_html(answer))
    try:
        await placeholder.edit_text(chunks[0])
    except TelegramBadRequest:
        try:
            await placeholder.edit_text(strip_tags(chunks[0]), parse_mode=None)
        except TelegramBadRequest:
            pass
    for chunk in chunks[1:]:
        await send_html(message.chat.id, chunk)


@router.callback_query(F.data == "menu:ai")
async def open_assistant(call: CallbackQuery, role: str) -> None:
    if not roles.can_use_assistant(role):
        await call.answer("Ассистент доступен с роли «Модератор».", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        "🧠 <b>ИИ-ассистент</b>\n\nНапишите вопрос обычным сообщением или используйте "
        "<code>/ai вопрос</code>.\n<code>/aireset</code> — очистить контекст диалога.",
        back_kb(),
    )


@router.message(Command("ai"))
async def cmd_ai(message: Message, state: FSMContext, role: str) -> None:
    if not roles.can_use_assistant(role):
        await message.answer("⛔️ Ассистент доступен начиная с роли «Модератор».")
        return
    await state.clear()
    question = re.sub(r"^/ai(@\w+)?\s*", "", message.text or "", flags=re.I).strip()
    if not question:
        await message.answer(
            "Напишите вопрос после команды, например:\n"
            "<code>/ai составь оповещение об отключении воды</code>"
        )
        return
    await run(message, question)


@router.message(Command("aireset"))
async def cmd_reset(message: Message, role: str) -> None:
    if not roles.can_use_assistant(role):
        return
    _history.pop(str(message.from_user.id), None)
    await message.answer("🧹 Контекст диалога очищен.")


@router.message(F.text)
async def free_chat(message: Message, state: FSMContext, role: str) -> None:
    if await state.get_state() is not None:
        await message.answer("⏳ Завершите текущее действие или отправьте /cancel.")
        return

    text = (message.text or "").strip()
    if text.startswith("/"):
        await message.answer("❓ Неизвестная команда. /menu — меню, /help — справка.")
        return

    if not roles.can_use_assistant(role):
        await message.answer(
            "Воспользуйтесь меню — или отправьте геопозицию, чтобы добавить локацию.",
            reply_markup=keyboards.main_menu(role),
        )
        return

    await run(message, text)
RADAR_FILE_49
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
# Проверка нужна только когда PostgreSQL действительно выбран: иначе она
# зря поднимала контейнер базы при работе на SQLite.
if [ "$(get_env_value DB_BACKEND)" = "postgres" ] &&
   [ -d "$APP_DIR/data/postgres" ] &&
   [ -n "$(ls -A "$APP_DIR/data/postgres" 2>/dev/null)" ]; then
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
# Ловушка bash: обработчик ERR срабатывает при ненулевом коде даже когда
# errexit выключен через `set +e`. Единственный надёжный способ получить код
# без обрыва — конструкция `команда || переменная=$?`: она входит в список
# с ||, а для таких команд ERR не вызывается.
DOCTOR_CODE=0
# Читаем вывод построчно: метки ##STAGE дают шкалу и название текущего теста,
# остальное копится в файл и показывается после завершения.
: > "$DOCTOR_OUT"
{
    $COMPOSE $COMPOSE_ARGS run --rm --no-deps radar python -m radar.doctor --stream \
        2>&1 || echo "##CODE $?"
} | while IFS= read -r dline; do
        case "$dline" in
            "##STAGE "*)
                set -- $dline
                progress "$2" "$3" "$(printf '%s ' "${@:4}" | sed 's/ $//')"
                ;;
            "##CODE "*)
                printf '%s\n' "${dline#\#\#CODE }" > "$APP_DIR/.doctor-code"
                ;;
            *)
                printf '%s\n' "$dline" >> "$DOCTOR_OUT"
                ;;
        esac
    done

if [ -f "$APP_DIR/.doctor-code" ]; then
    DOCTOR_CODE="$(cat "$APP_DIR/.doctor-code")"
    rm -f "$APP_DIR/.doctor-code"
fi
progress_done

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
    trap - ERR
    offer_rollback "диагностика не пройдена" || true
    printf "  Полный отчёт с трассировками: %s\n\n" "$LOG_FILE"
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
