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

if [ -f "$STAGING/database.sql" ]; then
    cp "$STAGING/database.sql" "$APP_DIR/data/restore-database.sql"
    warn "В копии дамп PostgreSQL — залейте его после запуска:"
    printf "    docker exec -i radar_db psql -U radar radar < %s\n" \
        "$APP_DIR/data/restore-database.sql"
fi

printf "\n"
ok "Восстановление завершено"
printf "\n  Дальше:\n"
printf "    cd %s && docker compose up -d\n" "$APP_DIR"
printf "    затем проверьте целостность в боте: Управление → Копии\n\n"
