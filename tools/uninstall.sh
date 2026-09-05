#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

#
# Полное удаление «Радара»: контейнеры, образ и каталог установки
# целиком — база, .env, копии, журналы. В отличие от флага установщика
# --uninstall, который данные сохраняет, этот скрипт не оставляет ничего.
#
# Отдельный скрипт, а не флаг: удаление нужно и тогда, когда установка
# сломана и установщик не запускается. Скрипт самодостаточен, без сети
# и без репозитория:
#
#   curl -fsSLo uninstall.sh https://raw.githubusercontent.com/Chistovik92/radar/main/tools/uninstall.sh
#   bash uninstall.sh
#
# Использование:
#   bash tools/uninstall.sh            с подтверждением
#   bash tools/uninstall.sh --yes      без вопросов (автоматизация)
#   RADAR_HOME=/путь bash tools/uninstall.sh   нестандартный каталог
#
set -Eeuo pipefail

APP_DIR="${RADAR_HOME:-$HOME/radar_bot}"

C_RESET=""; C_BOLD=""; C_DIM=""; C_GREEN=""; C_RED=""; C_YELLOW=""
if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_YELLOW=$'\033[1;33m'
fi

ok()   { printf "  %s✓%s %s\n" "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf "  %s!%s %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
die()  { printf "\n  %s✗ %s%s\n\n" "$C_RED" "$*" "$C_RESET" >&2; exit 1; }

ASSUME_YES=false
case "${1:-}" in
    --yes|-y) ASSUME_YES=true ;;
    "") : ;;
    -h|--help)
        awk 'NR > 1 && /^# ?/ { sub(/^# ?/, ""); print }' "$0" | head -n 30
        exit 0
        ;;
    *) die "Неизвестный аргумент: $1 (поддерживается только --yes)" ;;
esac

printf "\n  %sПолное удаление «Радара»%s\n" "$C_BOLD" "$C_RESET"
printf "  Будет удалено безвозвратно:\n"
printf "    контейнеры  radar_container, radar_db, radar_bot_api, radar_singbox\n"
printf "    образ       radar_image\n"
printf "    каталог     %s — база, .env, копии, журналы\n\n" "$APP_DIR"

# Подтверждение сильнее обычного [д/Н]: удаляется всё, включая копии,
# и отменить это нельзя. Требуется явное «да».
if [ "$ASSUME_YES" != true ] && { [ -t 0 ] || ( : < /dev/tty ) 2>/dev/null; }; then
    printf "  %sВведите «да», чтобы удалить всё:%s " "$C_YELLOW" "$C_RESET"
    answer=""
    read -r answer < /dev/tty || answer=""
    printf "\n"
    case "$answer" in
        да|Да|ДА|yes|YES) : ;;
        *) die "Отменено" ;;
    esac
fi

# Последняя копия — по желанию, перед удалением. Кэш Bot API Server
# (может весить гигабайты видео) и журналы в неё не входят.
final_backup=""
if [ "$ASSUME_YES" != true ] && [ -d "$APP_DIR" ] \
    && { [ -t 0 ] || ( : < /dev/tty ) 2>/dev/null; }; then
    printf "  %sСохранить последнюю копию перед удалением? [д/Н]:%s " \
        "$C_YELLOW" "$C_RESET"
    answer=""
    read -r answer < /dev/tty || answer=""
    printf "\n"
    case "$answer" in
        д|Д|y|Y|да|Да|ДА|yes|YES)
            stamp="$(date +%Y%m%d-%H%M%S)"
            final_backup="$HOME/radar-before-uninstall-$stamp.tar.gz"
            if tar -czf "$final_backup" \
                    --exclude="$APP_DIR/data/bot-api" \
                    --exclude="$APP_DIR/data/logs" \
                    -C "$(dirname "$APP_DIR")" "$(basename "$APP_DIR")" 2>/dev/null; then
                ok "Копия сохранена: $final_backup ($(du -h "$final_backup" | cut -f1))"
            else
                rm -f "$final_backup" 2>/dev/null || true
                die "Копию снять не удалось — удаление остановлено, данные не тронуты"
            fi
            ;;
        *) : ;;
    esac
fi

# Останавливаем раздачу переезда, если она жива: процесс держит файлы
# в каталоге установки и пережил бы rm -rf.
if command -v pkill >/dev/null 2>&1; then
    pkill -f "$APP_DIR/.migrate-serve.py" 2>/dev/null || true
fi

if command -v docker >/dev/null 2>&1; then
    if [ -f "$APP_DIR/docker-compose.yml" ]; then
        (cd "$APP_DIR" && docker compose down --remove-orphans 2>/dev/null) \
            || (cd "$APP_DIR" && docker-compose down --remove-orphans 2>/dev/null) \
            || true
    fi
    docker rm -f radar_container radar_db radar_bot_api radar_singbox \
        2>/dev/null || true
    docker rmi -f radar_image 2>/dev/null || true
    ok "Контейнеры и образ удалены"
else
    warn "Docker не найден — контейнеры и образ, если они есть, останутся"
    warn "Удалите их вручную: docker rm -f radar_container radar_db; docker rmi radar_image"
fi

if [ -d "$APP_DIR" ]; then
    rm -rf "$APP_DIR"
    ok "Каталог удалён: $APP_DIR"
else
    warn "Каталог не найден: $APP_DIR — нечего удалять"
fi

printf "\n"
ok "«Радар» полностью удалён"
if [ -n "$final_backup" ]; then
    printf "\n  Осталась одна копия: %s\n" "$final_backup"
    printf "  Когда она станет не нужна: rm %s\n" "$final_backup"
fi
printf "\n"
