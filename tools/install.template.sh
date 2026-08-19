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

# Анимация возможна только при живом терминале. При `curl … | bash`, в CI
# и при перенаправлении в файл его нет, и «бегущие» полосы превратились бы
# в мусор из escape-последовательностей посреди лога. Поэтому всё, что
# движется, спрашивает разрешения у этой переменной.
HAS_TTY=false
[ -t 1 ] && [ -z "${NO_ANIMATION:-}" ] && HAS_TTY=true

SPIN_CHARS='|/-\\'
SPIN_PID=""
STEP_STARTED=0
STEP_TITLE=""
STEP_TIMES=""          # накопленный отчёт: «название<TAB>секунды»
INSTALL_STARTED=$(date +%s)

server_time() { date "+%H:%M:%S"; }

human_time() {         # human_time <секунд>
    local total=$1
    if [ "$total" -ge 60 ]; then
        printf "%d мин %02d с" $((total / 60)) $((total % 60))
    else
        printf "%d с" "$total"
    fi
}

# Полоса этапа. Крутится, пока идёт длинная операция, и стирает себя за собой.
spinner_start() {      # spinner_start <подпись>
    [ "$HAS_TTY" = true ] || return 0
    local caption="$1"
    (
        local frame=0 width=22 position=0 direction=1
        while :; do
            local bar="" index=0
            while [ "$index" -lt "$width" ]; do
                if [ "$index" -eq "$position" ]; then bar="$bar#"; else bar="$bar."; fi
                index=$((index + 1))
            done
            printf "\r  %s%s%s [%s] %s" \
                "$C_CYAN" "${SPIN_CHARS:frame:1}" "$C_RESET" "$bar" "$caption"
            frame=$(( (frame + 1) % 4 ))
            position=$((position + direction))
            [ "$position" -ge $((width - 1)) ] && direction=-1
            [ "$position" -le 0 ] && direction=1
            sleep 0.12
        done
    ) &
    SPIN_PID=$!
    # Отключаем уведомление оболочки о завершении фоновой задачи: иначе
    # в конце этапа посреди вывода появляется «Terminated».
    disown "$SPIN_PID" 2>/dev/null || true
}

spinner_stop() {
    [ -n "$SPIN_PID" ] || return 0
    kill "$SPIN_PID" 2>/dev/null || true
    wait "$SPIN_PID" 2>/dev/null || true
    SPIN_PID=""
    # Стираем строку целиком: остатки полосы иначе перемешаются с отчётом.
    printf "\r%s\r" "$(repeat ' ' "$COLS")"
}

# Полосу нельзя оставить крутиться, если установка оборвалась.
trap 'spinner_stop' EXIT

step_finish() {
    [ -n "$STEP_TITLE" ] || return 0
    spinner_stop
    local spent=$(( $(date +%s) - STEP_STARTED ))
    printf "  %s└%s %sзавершено за %s%s\n" \
        "$C_DIM" "$C_RESET" "$C_DIM" "$(human_time "$spent")" "$C_RESET"
    STEP_TIMES="${STEP_TIMES}${STEP_TITLE}\t${spent}\n"
    log_raw "TIME  шаг «$STEP_TITLE»: ${spent} с"
    STEP_TITLE=""
}

step()  {
    step_finish
    STEP_CURRENT=$((STEP_CURRENT + 1))
    STEP_STARTED=$(date +%s)
    STEP_TITLE="$*"
    printf "\n%s[%d/%d]%s %s%s%s %s(%s)%s\n" "$C_BLUE" "$STEP_CURRENT" "$STEP_TOTAL" \
        "$C_RESET" "$C_BOLD" "$*" "$C_RESET" "$C_DIM" "$(server_time)" "$C_RESET"
    overall
    log_raw "=== ШАГ $STEP_CURRENT/$STEP_TOTAL: $* (время сервера $(server_time)) ==="
}

# Итоговая таблица: где именно ушло время. На слабом одноплатнике сборка
# образа занимает больше, чем всё остальное вместе, и это надо видеть.
timing_report() {
    step_finish
    local total=$(( $(date +%s) - INSTALL_STARTED ))
    printf "\n%sЗатраченное время%s\n" "$C_BOLD" "$C_RESET"
    # Без выравнивания колонкой: printf считает ширину в байтах, а кириллица
    # занимает по два — таблица разъехалась бы ровно на русских названиях.
    printf "%b" "$STEP_TIMES" | while IFS="$(printf '\t')" read -r name spent; do
        [ -n "$name" ] || continue
        printf "  %s%s%s — %s\n" "$C_DIM" "$name" "$C_RESET" "$(human_time "$spent")"
    done
    line
    printf "  %sВСЕГО%s — %s%s%s\n" "$C_BOLD" "$C_RESET" \
        "$C_BOLD" "$(human_time "$total")" "$C_RESET"
    printf "  %sвремя на сервере: %s%s\n" "$C_DIM" "$(date "+%d.%m.%Y %H:%M:%S %Z")" "$C_RESET"
    log_raw "TIME  установка заняла ${total} с"
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
# То же, что run, но с бегущей полосой и отчётом о затраченном времени.
# Для операций, которые заметно длятся: apt, сборка образа, запуск стека.
run_slow() {   # run_slow <подпись> <команда...>
    local caption="$1"; shift
    local started status=0
    started=$(date +%s)
    spinner_start "$caption"
    run "$@" || status=$?
    spinner_stop
    local spent=$(( $(date +%s) - started ))
    if [ "$status" -eq 0 ]; then
        printf "  %s✓%s %s %s(%s)%s\n" "$C_GREEN" "$C_RESET" "$caption" \
            "$C_DIM" "$(human_time "$spent")" "$C_RESET"
        log_raw "OK    $caption — $(human_time "$spent")"
    else
        printf "  %s✗%s %s %s(%s)%s\n" "$C_RED" "$C_RESET" "$caption" \
            "$C_DIM" "$(human_time "$spent")" "$C_RESET"
        log_raw "FAIL  $caption — код $status"
    fi
    return $status
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

# --- анимированная шкала для операций без известного прогресса --------------
# Docker не сообщает, сколько осталось, поэтому вместо ложных процентов
# показываем движение: видно, что процесс жив, а не завис.
SPIN_FRAMES='|/-\\'
SPINNER_PID=""

spinner_start() {     # spinner_start <подпись>
    local label="$1"
    ( 
        local index=0 pos=0 dir=1 width=24
        while :; do
            local bar="" i
            for (( i = 0; i < width; i++ )); do
                if [ "$i" -eq "$pos" ]; then bar="${bar}#"; else bar="${bar}."; fi
            done
            printf "\r  %s[%s]%s %s %-30s" \
                "$C_CYAN" "$bar" "$C_RESET" \
                "${SPIN_FRAMES:index:1}" "$label"
            index=$(( (index + 1) % 4 ))
            pos=$(( pos + dir ))
            if [ "$pos" -ge $((width - 1)) ]; then dir=-1; fi
            if [ "$pos" -le 0 ]; then dir=1; fi
            sleep 0.2
        done
    ) &
    SPINNER_PID=$!
    return 0
}

spinner_stop() {      # spinner_stop [подпись завершения]
    if [ -n "$SPINNER_PID" ]; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    fi
    progress_done
    [ -n "${1:-}" ] && ok "$1"
    return 0
}

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
    spinner_start "упаковка архива…"
    tar -czf "$archive" -C "$staging" . 2>>"$LOG_FILE"
    rm -rf "$staging"
    spinner_stop

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

    # База входит в снимок целиком: восстановление без данных бесполезно.
    # SQLite копируется вместе с журналами WAL, иначе часть записей теряется.
    for entry in data/radar.db data/radar.db-wal data/radar.db-shm data/db.json; do
        [ -e "$APP_DIR/$entry" ] && items="$items $entry"
    done
    if [ -d "$APP_DIR/data/postgres" ]; then
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^radar_db$'; then
            local dump="$APP_DIR/data/postgres-dump.sql"
            if docker exec radar_db pg_dump -U radar radar > "$dump" 2>>"$LOG_FILE"; then
                items="$items data/postgres-dump.sql"
            fi
        else
            items="$items data/postgres"
        fi
    fi

    [ -z "$items" ] && return 0

    spinner_start "снимок установки и базы…"
    if tar -czf "$archive" -C "$APP_DIR" $items 2>>"$LOG_FILE"; then
        spinner_stop
        ROLLBACK_SNAPSHOT="$archive"
        SNAPSHOT_READY=true
        printf '%s\n' "$PREVIOUS_VERSION" > "$dir/.last-version"
        ok "Снимок: $(basename "$archive") ($(du -h "$archive" | cut -f1))"
        rm -f "$APP_DIR/data/postgres-dump.sql" 2>/dev/null || true
        # Оставляем последние 5 снимков
        ls -1t "$dir"/rollback-*.tar.gz 2>/dev/null | tail -n +6 | xargs -r rm -f || true
    else
        spinner_stop
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
    spinner_start "распаковка снимка…"
    if ! tar -xzf "$archive" -C "$APP_DIR" 2>>"$LOG_FILE"; then
        spinner_stop
        fail "Распаковать снимок не удалось"
        return 1
    fi
    spinner_stop "Файлы и база восстановлены"

    # Дамп PostgreSQL из снимка заливается после подъёма контейнера
    if [ -f "$APP_DIR/data/postgres-dump.sql" ]; then
        info "В снимке есть дамп PostgreSQL — залейте его после запуска:"
        info "  docker exec -i radar_db psql -U radar radar < data/postgres-dump.sql"
    fi

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
        printf "    %s1) Восстановить из резервной копии%s\n" "$C_BOLD" "$C_RESET"
        printf "       %s%s%s\n" "$C_DIM" "$(basename "$archive")" "$C_RESET"
        printf "       %sвернутся файлы и настройки, база не трогается%s\n" \
            "$C_DIM" "$C_RESET"
    else
        printf "    %s1) (копии нет — восстановление недоступно)%s\n" "$C_DIM" "$C_RESET"
    fi
    printf "    %s2) Восстановить и файлы, и базу данных%s\n" "$C_BOLD" "$C_RESET"
    printf "       %sполный откат к состоянию до запуска установщика%s\n" \
        "$C_DIM" "$C_RESET"
    printf "    %s3) Ничего не делать — разберусь сам%s\n\n" "$C_BOLD" "$C_RESET"
    printf "  Выбор [1]: "

    local answer=""
    read -r answer < /dev/tty || answer="3"
    : "${answer:=1}"
    log_raw "Действие после сбоя ($reason): $answer"

    case "$answer" in
        1)
            [ -z "$archive" ] && { warn "Копии нет, восстановление невозможно"; return 1; }
            do_rollback "$archive" && return 0
            return 1
            ;;
        2)
            [ -z "$archive" ] && { warn "Копии нет, восстановление невозможно"; return 1; }
            restore_database || warn "Базу восстановить не удалось"
            do_rollback "$archive" && return 0
            return 1
            ;;
        *)
            printf "\n  Полный журнал: %s\n" "$LOG_FILE"
            printf "  Восстановить позже: bash %s/install.sh --rollback\n\n" "$APP_DIR"
            return 1
            ;;
    esac
}

# Обрыв установки после того, как файлы уже перезаписаны. Обычный die здесь
# оставляет систему в полуобновлённом виде: старая версия затёрта, новая
# не поднялась, а снимок лежит рядом — и человек о нём не знает.
# До make_snapshot ведёт себя как die: откатываться ещё не на что.
SNAPSHOT_READY=false

die_or_rollback() {   # die_or_rollback <сообщение>
    # Ловушку снимаем сразу: do_rollback внутри сам вызывает docker и tar,
    # и любая их ошибка иначе вернулась бы сюда же — бесконечным кругом.
    trap - ERR
    [ "${DYING:-false}" = true ] && exit 1
    DYING=true

    printf "\n%s✗ %s%s\n" "$C_RED" "$*" "$C_RESET" >&2
    log_raw "ERROR $*"
    [ -n "$LOG_FILE" ] && printf "  Полный лог: %s\n" "$LOG_FILE" >&2

    if [ "$SNAPSHOT_READY" != true ]; then
        exit 1
    fi
    offer_rollback "$*" || true
    exit 1
}

trap 'die_or_rollback "Установка прервана (строка $LINENO)"' ERR

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
    if run_slow "Список пакетов" apt-get update; then
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
    printf "    %s1) Обновление%s\n" "$C_BOLD" "$C_RESET"
    printf "       %sтекущая версия обновится до новой из репозитория,%s\n" "$C_DIM" "$C_RESET"
    printf "       %sбаза, настройки и собранный образ сохраняются%s\n" "$C_DIM" "$C_RESET"
    printf "    %s2) Переустановка%s\n" "$C_BOLD" "$C_RESET"
    printf "       %sобраз и файлы проекта соберутся заново,%s\n" "$C_DIM" "$C_RESET"
    printf "       %sбаза данных и .env сохраняются%s\n" "$C_DIM" "$C_RESET"
    printf "    %s3) С чистого листа%s\n" "$C_BOLD" "$C_RESET"
    printf "       %sудаление всех данных и установка с настройкой заново%s\n" "$C_DIM" "$C_RESET"
    printf "    %s4) Только резервная копия%s\n" "$C_BOLD" "$C_RESET"
    printf "       %sснять копию и выйти, ничего не меняя%s\n" "$C_DIM" "$C_RESET"
    printf "\n  %sПеред любым из вариантов снимается резервная копия.%s\n\n" "$C_DIM" "$C_RESET"

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
        *) info "Обновление поверх существующей установки" ;;
    esac

    # Копия снимается при любом варианте: при обновлении и переустановке
    # тоже есть чему ломаться, а восстановление без копии невозможно.
    if [ "$FULL_RESET" != true ]; then
        make_backup "перед установкой" || warn "Продолжаю без резервной копии"
    fi
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

# --- обслуживание базы данных ---------------------------------------------
# Отдельная копия только базы: она нужна чаще полной и восстанавливается
# быстрее. Полная копия проекта делается выше, при выборе способа установки.
database_menu() {
    local backend db_file
    backend="$(get_env_value DB_BACKEND)"
    : "${backend:=sqlite}"
    db_file="$APP_DIR/data/radar.db"

    local has_db=false
    if [ "$backend" = "sqlite" ] && [ -f "$db_file" ]; then has_db=true; fi
    if [ "$backend" = "postgres" ] && [ -d "$APP_DIR/data/postgres" ]; then has_db=true; fi

    local snapshots
    snapshots="$(ls -1 "$APP_DIR/backups"/db-*.tar.gz 2>/dev/null | wc -l || echo 0)"

    if [ "$has_db" != true ] && [ "$snapshots" -eq 0 ]; then
        return 0
    fi

    echo
    printf "  %sОбслуживание базы данных%s\n\n" "$C_BOLD" "$C_RESET"
    printf "    1) Ничего не делать %s(по умолчанию)%s\n" "$C_DIM" "$C_RESET"
    printf "    2) Снять копию базы\n"
    printf "    3) Снять копию, удалить базу и создать заново\n"
    printf "    4) Восстановить базу из копии %s(доступно: %s)%s\n" \
        "$C_DIM" "$snapshots" "$C_RESET"
    printf "  Выбор [1]: "

    local answer=""
    read -r answer < /dev/tty || answer="1"
    : "${answer:=1}"
    log_raw "Обслуживание базы: вариант $answer"

    case "$answer" in
        2) backup_database ;;
        3)
            backup_database || { warn "Копия не создана — база не тронута"; return 0; }
            info "Удаляю базу"
            (cd "$APP_DIR" && run $COMPOSE down) || true
            rm -f "$db_file" "$db_file-wal" "$db_file-shm" 2>/dev/null || true
            rm -rf "$APP_DIR/data/postgres" 2>/dev/null || true
            ok "База удалена, будет создана заново при запуске"
            ;;
        4) restore_database ;;
        *) : ;;
    esac
    return 0
}

backup_database() {
    local stamp archive backend
    backend="$(get_env_value DB_BACKEND)"
    : "${backend:=sqlite}"
    stamp="$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$APP_DIR/backups"
    archive="$APP_DIR/backups/db-${backend}-${stamp}.tar.gz"

    spinner_start "копирую базу данных…"
    local ok_flag=false
    if [ "$backend" = "postgres" ]; then
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^radar_db$'; then
            local dump="$APP_DIR/backups/.dump-$stamp.sql"
            if docker exec radar_db pg_dump -U radar radar > "$dump" 2>>"$LOG_FILE"; then
                tar -czf "$archive" -C "$APP_DIR/backups" "$(basename "$dump")" 2>>"$LOG_FILE"
                rm -f "$dump"
                ok_flag=true
            fi
        else
            # Контейнер не поднят — копируем сам том
            tar -czf "$archive" -C "$APP_DIR/data" postgres 2>>"$LOG_FILE" && ok_flag=true
        fi
    else
        if [ -f "$APP_DIR/data/radar.db" ]; then
            tar -czf "$archive" -C "$APP_DIR/data" radar.db 2>>"$LOG_FILE" && ok_flag=true
        fi
    fi
    spinner_stop

    if [ "$ok_flag" = true ] && [ -f "$archive" ]; then
        ok "Копия базы: $(basename "$archive") ($(du -h "$archive" | cut -f1))"
        ls -1t "$APP_DIR/backups"/db-*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm -f || true
        return 0
    fi
    rm -f "$archive" 2>/dev/null || true
    warn "Копию базы создать не удалось"
    return 1
}

restore_database() {
    local archives count choice archive
    mapfile -t archives < <(ls -1t "$APP_DIR/backups"/db-*.tar.gz 2>/dev/null || true)
    count=${#archives[@]}
    if [ "$count" -eq 0 ]; then
        warn "Копий базы не найдено"
        return 1
    fi

    echo
    printf "  %sДоступные копии:%s\n" "$C_BOLD" "$C_RESET"
    local index=1
    for item in "${archives[@]}"; do
        printf "    %d) %s  %s%s%s\n" "$index" "$(basename "$item")" \
            "$C_DIM" "$(du -h "$item" | cut -f1)" "$C_RESET"
        index=$((index + 1))
    done
    printf "  Выбор [1]: "
    read -r choice < /dev/tty || choice="1"
    : "${choice:=1}"

    if ! printf '%s' "$choice" | grep -qE '^[0-9]+$' || [ "$choice" -lt 1 ] ||
       [ "$choice" -gt "$count" ]; then
        warn "Неверный выбор — восстановление отменено"
        return 1
    fi
    archive="${archives[$((choice - 1))]}"

    warn "Текущая база будет заменена содержимым копии"
    printf "  Продолжить? (y/N): "
    local confirm=""
    read -r confirm < /dev/tty || confirm="n"
    case "${confirm:-n}" in [Yy]*) : ;; *) info "Восстановление отменено"; return 1 ;; esac

    (cd "$APP_DIR" && run $COMPOSE down) || true
    spinner_start "восстанавливаю базу…"
    local restored=false
    if tar -tzf "$archive" 2>/dev/null | grep -q '\.sql$'; then
        # Дамп PostgreSQL: распаковываем, зальётся при первом старте вручную
        tar -xzf "$archive" -C "$APP_DIR/backups" 2>>"$LOG_FILE" && restored=true
        spinner_stop
        ok "Дамп распакован в $APP_DIR/backups"
        info "Залейте его после запуска:"
        info "  docker exec -i radar_db psql -U radar radar < <файл>.sql"
        return 0
    fi
    tar -xzf "$archive" -C "$APP_DIR/data" 2>>"$LOG_FILE" && restored=true
    spinner_stop

    if [ "$restored" = true ]; then
        ok "База восстановлена из $(basename "$archive")"
        return 0
    fi
    warn "Восстановить не удалось — подробности в журнале"
    return 1
}

# Базу выбираем всегда: и при новом .env, и при использовании существующего.
# Раньше выбор молча наследовался из старого файла, где строки DB_BACKEND
# могло не быть вовсе — пользователь о базе даже не знал.
choose_database
database_menu

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
    die_or_rollback "DB_PASSWORD содержит символ \$ — Compose примет его за переменную. Смените пароль в .env"
fi

info "Останавливаю прежние контейнеры"
run $COMPOSE down --remove-orphans || true
run docker rm -f "$CONTAINER_NAME" || true   # наследие версий 3.x

info "Собираю образ (первый раз это занимает 5–15 минут)"
spinner_start "сборка образа…"
if ! run_slow "Сборка образа" $COMPOSE build $NO_CACHE_FLAG; then
    spinner_stop
    trap - ERR
    fail "Сборка образа не удалась"
    offer_rollback "сборка образа" || true
    printf "  Полный журнал: %s\n\n" "$LOG_FILE"
    exit 1
fi
spinner_stop "Образ собран"

# PostgreSQL запоминает пароль при инициализации тома. Если .env изменился,
# а том остался прежним, бот будет молча биться в отказ авторизации.
# Проверка нужна только когда PostgreSQL действительно выбран: иначе она
# зря поднимала контейнер базы при работе на SQLite.
if [ "$(get_env_value DB_BACKEND)" = "postgres" ] &&
   [ -d "$APP_DIR/data/postgres" ] &&
   [ -n "$(ls -A "$APP_DIR/data/postgres" 2>/dev/null)" ]; then
    info "Проверяю пароль существующей базы"
    run_slow "Запуск PostgreSQL" $COMPOSE up -d postgres \
        || die_or_rollback "Не удалось запустить PostgreSQL"

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
                die_or_rollback "Верните прежний пароль в .env и запустите установщик заново"
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
    run_slow "Запуск PostgreSQL" $COMPOSE $COMPOSE_ARGS up -d postgres \
        || die_or_rollback "Не удалось запустить PostgreSQL"
    for _ in $(seq 1 45); do
        docker exec radar_db pg_isready -U radar >/dev/null 2>&1 && break
        sleep 2
    done
else
    info "База данных: SQLite (файл data/radar.db, отдельный контейнер не нужен)"
fi

# Профиль media поднимает собственный Bot API Server: он снимает предел
# отправки с 50 МБ до 2 ГБ, но требует ключей с my.telegram.org.
MEDIA_VALUE="$(get_env_value MEDIA_ENABLED)"
if [ "$MEDIA_VALUE" = "1" ]; then
    API_ID_VALUE="$(get_env_value TELEGRAM_API_ID)"
    API_HASH_VALUE="$(get_env_value TELEGRAM_API_HASH)"
    if [ -n "$API_ID_VALUE" ] && [ -n "$API_HASH_VALUE" ]; then
        COMPOSE_ARGS="$COMPOSE_ARGS --profile media"
        info "Загрузка видео: свой Bot API Server (файлы до 2 ГБ)"
        mkdir -p "$APP_DIR/data/bot-api"
    else
        warn "MEDIA_ENABLED=1, но TELEGRAM_API_ID или TELEGRAM_API_HASH не заданы"
        info "Загрузка видео будет работать с пределом 50 МБ"
        info "Ключи берутся на my.telegram.org → API development tools"
    fi
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

run_slow "Запуск контейнеров" $COMPOSE $COMPOSE_ARGS up -d \
    || die_or_rollback "Не удалось запустить контейнеры"

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
timing_report
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
if [ "${DB_BACKEND_VALUE:-sqlite}" = "postgres" ]; then
    printf "    Логи базы     docker logs -f radar_db\n"
else
    printf "    %sБаза — файл data/radar.db, отдельного контейнера нет%s\n" \
        "$C_DIM" "$C_RESET"
fi
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
