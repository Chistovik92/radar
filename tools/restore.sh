#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

#
# Отдельный скрипт, а не флаг установщика. Причина в том, ради чего он
# существует: восстановление нужно тогда, когда установка сломана —
# а установщик в этот момент может не запускаться вовсе. Скрипт нарочно
# простой, без сборки образов и обращений к сети: распаковать, положить
# на место, поднять.
#
# Использование:
#   bash tools/restore.sh                     последняя копия
#   bash tools/restore.sh ФАЙЛ.tar.gz         конкретная
#   bash tools/restore.sh --list              что вообще есть
#
# На сервере репозитория нет — установщик разворачивает только код бота.
# Скрипт самодостаточен и скачивается одной командой:
#   curl -fsSLo restore.sh https://raw.githubusercontent.com/Chistovik92/radar/main/tools/restore.sh
#   bash restore.sh radar-backup-….tar.gz
#
set -Eeuo pipefail

APP_DIR="${RADAR_HOME:-$HOME/radar_bot}"
BACKUPS="$APP_DIR/backups"

C_RESET=""; C_BOLD=""; C_DIM=""; C_GREEN=""; C_RED=""; C_YELLOW=""
if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_YELLOW=$'\033[1;33m'
fi

ok()   { printf "  %s✓%s %s\n" "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf "  %s!%s %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
die()  { printf "\n  %s✗ %s%s\n\n" "$C_RED" "$*" "$C_RESET" >&2; exit 1; }

listing() {
    find "$BACKUPS" -maxdepth 1 -name 'radar-backup-*.tar.gz' 2>/dev/null \
        | sort -r || true
}

if [ "${1:-}" = "--list" ]; then
    printf "\n  %sДоступные копии%s\n\n" "$C_BOLD" "$C_RESET"
    found=false
    while read -r item; do
        [ -n "$item" ] || continue
        found=true
        printf "    %s  %s%s%s\n" "$(basename "$item")" \
            "$C_DIM" "$(du -h "$item" | cut -f1)" "$C_RESET"
    done <<< "$(listing)"
    [ "$found" = true ] || printf "    копий нет\n"
    printf "\n"
    exit 0
fi

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
    ARCHIVE="$(listing | head -1)"
    [ -n "$ARCHIVE" ] || die "Копий не найдено в $BACKUPS"
    printf "  Беру последнюю: %s\n" "$(basename "$ARCHIVE")"
fi
case "$ARCHIVE" in
    /*) : ;;
    *) [ -f "$ARCHIVE" ] || ARCHIVE="$BACKUPS/$ARCHIVE" ;;
esac
[ -f "$ARCHIVE" ] || die "Файл не найден: $ARCHIVE"

printf "\n  %sВосстановление «Радара»%s\n" "$C_BOLD" "$C_RESET"
printf "  Копия:    %s\n" "$(basename "$ARCHIVE")"
printf "  Каталог:  %s\n\n" "$APP_DIR"

# Подтверждение обязательно: восстановление затирает текущие данные,
# и человек, запустивший скрипт наугад, должен успеть остановиться.
if [ -t 0 ] || ( : < /dev/tty ) 2>/dev/null; then
    printf "  %sТекущие данные будут заменены. Продолжить? [д/Н]:%s " \
        "$C_YELLOW" "$C_RESET"
    answer=""
    read -r answer < /dev/tty || answer="n"
    case "$answer" in
        y|Y|д|Д|yes|да) : ;;
        *) die "Отменено" ;;
    esac
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

tar -xzf "$ARCHIVE" -C "$STAGING" || die "Не удалось распаковать копию"
ok "Копия распакована"

if [ -f "$STAGING/manifest.txt" ]; then
    printf "\n  %sСодержимое копии%s\n" "$C_BOLD" "$C_RESET"
    sed 's/^/    /' "$STAGING/manifest.txt"
    printf "\n"
else
    warn "Манифеста нет — возможно, это не копия «Радара»"
fi

mkdir -p "$APP_DIR/data"

if [ -d "$APP_DIR" ] && command -v docker >/dev/null 2>&1; then
    (cd "$APP_DIR" && docker compose down 2>/dev/null) || true
    ok "Контейнеры остановлены"
fi

if [ -f "$STAGING/env.backup" ]; then
    cp "$STAGING/env.backup" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env" 2>/dev/null || true
    ok "Настройки восстановлены"
else
    warn "В копии нет .env — параметры придётся ввести заново"
fi

if [ -d "$STAGING/data" ]; then
    cp -r "$STAGING/data/." "$APP_DIR/data/" 2>/dev/null || true
    ok "Файлы данных восстановлены"
fi

# Копии, снятые самим ботом (radar/backup.py — ночные и из панели),
# кладут файлы базы россыпью в корень архива, без каталога data/.
# До 4.8.2.2 restore.sh, как и установщик, молча их выбрасывал.
found_db=false
for dbfile in radar.db radar.db-wal radar.db-shm db.json; do
    if [ -f "$STAGING/$dbfile" ]; then
        cp "$STAGING/$dbfile" "$APP_DIR/data/"
        found_db=true
    fi
done
if [ "$found_db" = true ]; then
    ok "База из копии бота восстановлена"
fi

if [ -f "$STAGING/database.sql" ]; then
    cp "$STAGING/database.sql" "$APP_DIR/data/restore-database.sql"
fi

# Пустую копию не пропускаем молча: бот поднялся бы с чистой базой,
# и заметно это стало бы только по пропавшим пользователям.
if [ "$found_db" != true ] && [ ! -d "$STAGING/data" ] \
    && [ ! -f "$STAGING/database.sql" ]; then
    warn "В копии нет ни дампа базы, ни файлов данных — бот поднимется с пустой базой"
fi

printf "\n"
ok "Восстановление завершено"

# Подъём. До 4.8.2.3 скрипт останавливался на печати подсказки, хотя
# обещал «поднять»: человеку, восстанавливающемуся после поломки,
# доставалась ещё одна команда руками. Профили собираются из .env
# той же логикой, что в установщике.
if [ ! -f "$APP_DIR/docker-compose.yml" ] || ! command -v docker >/dev/null 2>&1; then
    printf "\n  Дальше:\n"
    printf "    cd %s && docker compose up -d\n" "$APP_DIR"
    printf "\n  Проверьте данные в боте: /stats — пользователи, локации, источники\n\n"
    exit 0
fi

env_value() {   # env_value <переменная> — из .env после восстановления
    grep -E "^$1=" "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- || true
}

COMPOSE="docker compose"
docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"

BACKEND="$(env_value DB_BACKEND)"; : "${BACKEND:=sqlite}"
COMPOSE_ARGS=""
if [ "$BACKEND" = "postgres" ]; then
    COMPOSE_ARGS="--profile postgres"
fi
if [ "$(env_value MEDIA_ENABLED)" = "1" ] \
    && [ -n "$(env_value TELEGRAM_API_ID)" ] \
    && [ -n "$(env_value TELEGRAM_API_HASH)" ]; then
    COMPOSE_ARGS="$COMPOSE_ARGS --profile media"
fi

# Несовпадение носителя данных и выбранной базы — вслух, а не молча:
# бот поднялся бы живым, но с пустой базой, и заметно это стало бы не сразу.
if [ "$BACKEND" = "postgres" ] && [ "$found_db" = true ]; then
    warn "В .env выбран PostgreSQL, а из копии пришли файлы SQLite — бот их не увидит"
    warn "Если копия сделана на SQLite, поправьте DB_BACKEND=sqlite в .env и перезапустите"
fi
if [ "$BACKEND" = "sqlite" ] && [ -f "$APP_DIR/data/restore-database.sql" ]; then
    warn "В копии дамп PostgreSQL, а выбрана SQLite — залить нельзя: это разные диалекты SQL"
fi

# Дамп PostgreSQL заливается ДО старта бота: иначе бот создаст пустую
# схему, и дамп ляжет поверх наполовину — часть таблиц из копии,
# часть новых. Та же логика, что в установщике при переезде.
if [ "$BACKEND" = "postgres" ] && [ -f "$APP_DIR/data/restore-database.sql" ]; then
    (cd "$APP_DIR" && $COMPOSE $COMPOSE_ARGS up -d postgres) || true
    DB_USER="$(env_value DB_USER)"; : "${DB_USER:=radar}"
    DB_NAME="$(env_value DB_NAME)"; : "${DB_NAME:=radar}"
    ready=false
    for _ in $(seq 1 45); do
        if docker exec radar_db pg_isready -U "$DB_USER" >/dev/null 2>&1; then
            ready=true
            break
        fi
        sleep 2
    done
    if [ "$ready" = true ] \
        && docker exec -i radar_db psql -U "$DB_USER" -d "$DB_NAME" \
               < "$APP_DIR/data/restore-database.sql" >/dev/null 2>&1; then
        ok "Дамп базы залит"
        # Переименован, чтобы повторный запуск не заливал дамп поверх базы.
        mv "$APP_DIR/data/restore-database.sql" \
           "$APP_DIR/data/restore-database.sql.applied" 2>/dev/null || true
    else
        warn "Дамп не залился — сделайте это руками и перезапустите бота:"
        printf "    docker exec -i radar_db psql -U %s %s < %s\n" \
            "$DB_USER" "$DB_NAME" "$APP_DIR/data/restore-database.sql"
        printf "    cd %s && docker compose restart radar\n" "$APP_DIR"
    fi
fi

if (cd "$APP_DIR" && $COMPOSE $COMPOSE_ARGS up -d); then
    sleep 5
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^radar_container$'; then
        ok "Бот запущен"
    else
        warn "Контейнер не поднялся — смотрите журнал:"
        printf "    docker logs -f radar_container\n"
    fi
else
    warn "Не удалось запустить — поднимите вручную:"
    printf "    cd %s && docker compose up -d\n" "$APP_DIR"
fi

printf "\n  Проверьте данные в боте: /stats — пользователи, локации, источники\n\n"
