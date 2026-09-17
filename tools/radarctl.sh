#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

#
# Командная строка «Радара»: то же, что умеет веб-панель, только из консоли
# и пригодно для cron.
#
# Команды делятся на две группы, и это не прихоть. Одни работают с данными
# бота — их выполняет сам бот внутри своего контейнера, потому что там
# база, .env и весь код. Другие управляют самой установкой — их выполнять
# внутри контейнера бессмысленно: обновление пересоздаёт этот контейнер,
# а удаление его стирает.
#
# Внутри контейнера:
#   bash radarctl.sh sources list
#   bash radarctl.sh features on digest
#   bash radarctl.sh backup create
#   bash radarctl.sh db size --json
#   bash radarctl.sh rustdesk connections
#   bash radarctl.sh doctor --quick
#
# На хосте:
#   bash radarctl.sh update            обновиться до последнего выпуска
#   bash radarctl.sh wipe --yes        стереть установку целиком
#   bash radarctl.sh restore ФАЙЛ      восстановить из копии
#
# Общее:
#   RADAR_HOME=/путь bash radarctl.sh …   нестандартный каталог установки
#   bash radarctl.sh --help               этот текст
#
set -Eeuo pipefail

APP_DIR="${RADAR_HOME:-$HOME/radar_bot}"
CONTAINER="${RADAR_CONTAINER:-radar_container}"
INSTALLER_URL="https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh"
UNINSTALL_URL="https://raw.githubusercontent.com/Chistovik92/radar/main/tools/uninstall.sh"

die() { printf "\n  ✗ %s\n\n" "$*" >&2; exit 1; }

usage() {
    awk 'NR > 1 && /^# ?/ { sub(/^# ?/, ""); print }' "$0" | head -n 40
}

# Справка обязана работать там, где Docker не установлен вовсе:
# её читают и до установки, и на своей машине.
case "${1:-}" in
    ""|-h|--help|help) usage; exit 0 ;;
esac

command -v docker >/dev/null 2>&1 || die "Docker не найден — управлять нечем"

case "$1" in
    update)
        shift
        # Тот же путь, что у кнопки в панели: установщик берётся свежий,
        # потому что лежащий рядом несёт код своей версии внутри себя.
        cd "$APP_DIR" 2>/dev/null || die "Каталог установки не найден: $APP_DIR"
        curl -fsSLo install.sh.new "$INSTALLER_URL" \
            || die "Не удалось скачать установщик"
        bash -n install.sh.new || { rm -f install.sh.new; die "Установщик повреждён"; }
        mv -f install.sh.new install.sh
        exec env RADAR_HOME="$APP_DIR" bash install.sh --skip-updates "$@"
        ;;

    wipe)
        shift
        if [ -f "$APP_DIR/tools/uninstall.sh" ]; then
            exec env RADAR_HOME="$APP_DIR" bash "$APP_DIR/tools/uninstall.sh" "$@"
        fi
        # Установка могла быть сломана до того, как скрипт лёг на место.
        curl -fsSLo /tmp/radar-uninstall.sh "$UNINSTALL_URL" \
            || die "Не удалось скачать скрипт удаления"
        bash -n /tmp/radar-uninstall.sh || die "Скрипт удаления повреждён"
        exec env RADAR_HOME="$APP_DIR" bash /tmp/radar-uninstall.sh "$@"
        ;;

    restore)
        shift
        [ -f "$APP_DIR/tools/restore.sh" ] \
            || die "Рядом с установкой нет tools/restore.sh"
        exec env RADAR_HOME="$APP_DIR" bash "$APP_DIR/tools/restore.sh" "$@"
        ;;

    *)
        # Всё остальное — внутрь контейнера, к коду и базе бота.
        docker inspect "$CONTAINER" >/dev/null 2>&1 \
            || die "Контейнер $CONTAINER не найден — бот не установлен или остановлен"
        exec docker exec -i "$CONTAINER" python -m radar.cli "$@"
        ;;
esac
