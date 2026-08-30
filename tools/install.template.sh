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
#   --lang=ru|en     язык установщика (по умолчанию русский)
#   --version=ТЕГ    поставить конкретный релиз (в том числе откатиться назад)
#   --versions       показать доступные версии
#   --restore-url=…  развернуть систему по ссылке со старого сервера
#   --migrate        собрать всё для переезда на другую машину
#   --restore        развернуть систему из копии рядом с установщиком
#   --restore=ФАЙЛ   развернуть систему из копии (переезд, часть вторая)
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
MIGRATE_OUT=false
TARGET_VERSION=""
LIST_VERSIONS=false
RESTORE_FROM=""
RESTORE_AUTO=false
RESTORE_URL=""
RESTORED=false
INSTALLER_URL="https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh"
LOG_FILE=""
START_TS=$(date +%s)

ORIGINAL_ARGS="$*"

# Абсолютный путь к файлу запущенного установщика. При `bash <(curl …)`
# это поток, и пути нет. Захватывается ДО любых переходов в другие
# каталоги: нужен для сборки самодостаточного пакета переезда.
SELF_PATH=""
if [ -f "$0" ]; then
    case "$0" in
        /*) SELF_PATH="$0" ;;
        *)  SELF_PATH="$(pwd)/$0" ;;
    esac
fi

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
  --lang=ru|en     язык установщика (по умолчанию русский)
  --version=ТЕГ    поставить конкретный релиз (в том числе откатиться назад)
  --versions       показать доступные версии
  --restore-url=…  развернуть систему по ссылке со старого сервера
  --migrate        собрать всё для переезда на другую машину
  --restore        развернуть систему из копии рядом с установщиком
  --restore=ФАЙЛ   развернуть систему из копии (переезд, часть вторая)
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
        --migrate)      MIGRATE_OUT=true ;;
        --version=*)    TARGET_VERSION="${arg#*=}" ;;
        --versions)     LIST_VERSIONS=true ;;
        --lang=*)       RADAR_LANG="${arg#*=}" ;;
        --restore-url=*) RESTORE_URL="${arg#*=}" ;;
        --restore)      RESTORE_AUTO=true ;;
        --restore=*)    RESTORE_FROM="${arg#*=}" ;;
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

# --------------------------------------------------------------------------
#  Язык установщика (с 4.7.2)
# --------------------------------------------------------------------------
#
# Русский по умолчанию. Английский включается флагом --lang=en, переменной
# RADAR_LANG или наследуется из LANG системы. Выбор запоминается в .env,
# чтобы при следующем запуске не спрашивать снова.
#
# Переведены сообщения, которые человек читает при обычной работе:
# заголовки шагов, переезд, итоги, подсказки. Внутренние технические
# строки в журнале остаются на русском — их читает автор, а не пользователь,
# и переводить их значило бы удваивать поддержку без выигрыша.

LANG_CODE="ru"

detect_language() {
    local stored=""
    [ -f "$APP_DIR/.env" ] && stored="$(grep -E '^INSTALLER_LANG=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
    if [ -n "${RADAR_LANG:-}" ]; then
        LANG_CODE="$RADAR_LANG"
    elif [ -n "$stored" ]; then
        LANG_CODE="$stored"
    elif printf '%s' "${LANG:-}" | grep -qi '^en'; then
        LANG_CODE="en"
    fi
    case "$LANG_CODE" in
        en|ru) : ;;
        *) LANG_CODE="ru" ;;
    esac
}

# Словарь. Ключ — строка, значения через разделитель, который не встречается
# в текстах. Ассоциативные массивы не используем: bash 3 их не знает,
# а установщик должен работать и на старых системах.
t() {                  # t <ключ> [подстановка]
    local key="$1" value="" extra="${2:-}"
    if [ "$LANG_CODE" = "en" ]; then
        case "$key" in
            step_prepare)        value="Preparing directory and install log" ;;
            step_check)          value="Checking system components" ;;
            step_update)         value="Updating system components" ;;
            step_previous)       value="Checking previous installation" ;;
            step_deploy)         value="Deploying project files" ;;
            step_settings)       value="Configuring parameters" ;;
            step_build)          value="Building image and starting containers" ;;
            step_diagnose)       value="Checking the system before start" ;;
            step_start)          value="Starting the bot" ;;
            time_report)         value="Time spent" ;;
            time_total)          value="TOTAL" ;;
            time_server)         value="server time" ;;
            done_running)        value="Radar v%s is running" ;;
            tls_botfather_title) value="One more step — in Telegram, not on the server:" ;;
            tls_botfather_open)  value="Open" ;;
            tls_botfather_pick)  value="Pick your bot from the list" ;;
            tls_botfather_send)  value="Send the address:" ;;
            tls_botfather_note)  value="Without this the login widget says «Bot domain invalid»." ;;
            tls_ask)             value="Publish the panel with a domain and HTTPS? [y/N]" ;;
            tls_domain_ask)      value="Domain (for example radar.example.com):" ;;
            tls_domain_empty)    value="No domain entered — skipping" ;;
            tls_domain_bad)      value="That does not look like a domain:" ;;
            tls_found)           value="Certificate already set up for" ;;
            tls_found_no_domain) value="A certificate exists, but no domain is configured" ;;
            tls_short_missing)   value="Short links do not know the address yet — fixing" ;;
            tls_short_differs)   value="Short link address differs from the certificate domain — left as is" ;;
            tls_short_url)       value="Short links will use" ;;
            tls_salt_created)    value="Salt for short codes generated" ;;
            tls_salt_kept)       value="Existing salt kept: changing it would break links already sent" ;;
            tls_script_missing)  value="tls.sh not found next to the installation" ;;
            tls_failed)          value="Certificate was not issued — see the output above" ;;
            tls_restart_hint)    value="Restart the bot to pick up the new settings: docker compose restart" ;;
            updates_ask)         value="Update system packages? [Y/n]" ;;
            updates_skipped)     value="System packages will not be updated" ;;
            migrate_ask)         value="Move this installation to another server? [y/N]" ;;
            migrate_making_copy) value="Making a copy for the move" ;;
            migrate_copy_ready)  value="Copy ready" ;;
            migrate_port_busy)   value="Port is already in use:" ;;
            action_title)        value="What are we doing?" ;;
            action_main)         value="Install the latest code (main) — default" ;;
            action_release)      value="Install a specific release" ;;
            action_backup)       value="Only make a full backup and exit" ;;
            action_migrate)      value="Move to another server" ;;
            action_choice)       value="Choice" ;;
            versions_loading)    value="Fetching the list of releases…" ;;
            versions_pick)       value="Number or tag" ;;
            versions_fallback_main) value="Continuing with the latest code from main" ;;
            version_selected)    value="Selected:" ;;
            backup_before)       value="Full backup before installing" ;;
            backup_done)         value="Backup saved:" ;;
            versions_title)      value="Available versions" ;;
            versions_main)       value="latest code, may be unreleased" ;;
            versions_failed)     value="Could not fetch the list of releases from GitHub" ;;
            versions_howto)      value="To install a specific one:" ;;
            step_fetch_version)  value="Fetching the requested version" ;;
            version_unknown)     value="No such release:" ;;
            version_download_failed) value="Could not download that version" ;;
            version_broken)      value="The downloaded installer is damaged" ;;
            version_ready)       value="Installer ready:" ;;
            version_handoff)     value="Handing over to that version's installer…" ;;
            rollback_offer)      value="Roll back to a previous release?" ;;
            step_migrate)        value="Collecting data for migration" ;;
            migrate_no_install)  value="Installation not found in $APP_DIR" ;;
            migrate_backup_failed) value="Could not create the copy" ;;
            migrate_ready)       value="Run this on the NEW server:" ;;
            migrate_note_once)   value="The link works ONCE and shuts down right after the download." ;;
            migrate_note_time)   value="It expires in $extra minutes even if unused." ;;
            migrate_note_port)   value="Port $extra must be reachable from the new server." ;;
            migrate_note_secret) value="The copy contains your bot token and passwords — do not share this link." ;;
            migrate_note_stop)   value="When the new bot answers in Telegram, stop the old one:" ;;
            migrate_note_nat)    value="Cannot connect? Forward port $extra on the old server's router to this machine — without forwarding the link will not open." ;;
            migrate_bundle_ok)   value="Self-contained bundle built: code and data in one file" ;;
            migrate_downloaded)  value="The copy has been downloaded by the new server — transfer complete" ;;
            migrate_expired)     value="The link has expired, the copy was not downloaded" ;;
            migrate_stopped)     value="The serving stopped before its time" ;;
            migrate_cancelled)   value="Waiting cancelled, serving stopped" ;;
            migrate_waiting_left) value="Waiting for the download… time left" ;;
            db_title)            value="Which database should be used?" ;;
            db_sqlite_note)      value="(recommended)" ;;
            db_sqlite_line1)     value="a data/radar.db file next to the bot, no separate container," ;;
            db_sqlite_line2)     value="no password, no waiting for startup — fits 1–2 GB of RAM" ;;
            db_postgres_line)    value="a separate container, +300–500 MB of memory; for a beefier machine" ;;
            db_current)          value="Currently selected:" ;;
            db_switch_confirm)   value="Continue switching the database?" ;;
            dbmaint_title)       value="Database maintenance" ;;
            dbmaint_nothing)     value="Do nothing (default)" ;;
            dbmaint_backup)      value="Back up the database" ;;
            dbmaint_recreate)    value="Back up, drop and recreate the database" ;;
            dbmaint_restore)     value="Restore the database from a backup (available:" ;;
            existing_title)      value="What should happen to the existing installation?" ;;
            existing_update)     value="Update" ;;
            existing_update_note1) value="the current version updates to the new one from the repository," ;;
            existing_update_note2) value="database, settings and the built image are kept" ;;
            existing_reinstall)  value="Reinstall" ;;
            existing_reinstall_note1) value="the image and project files are rebuilt from scratch," ;;
            existing_reinstall_note2) value="the database and .env are kept" ;;
            existing_clean)      value="Clean slate" ;;
            existing_clean_note) value="wipe all data and install with fresh setup" ;;
            existing_backup)     value="Backup only" ;;
            existing_backup_note) value="make a copy and exit without changing anything" ;;
            existing_note)       value="A backup is taken before any of these." ;;
            existing_diagnosis)  value="Diagnostics" ;;
            existing_recommended) value="suggested option" ;;
            botapi_title)        value="Own Bot API Server" ;;
            botapi_why)          value="Raises the sending limit from 50 MB to 2 GB." ;;
            botapi_cost)         value="Needs api_id and api_hash from my.telegram.org, and caches files on disk." ;;
            botapi_ask)          value="Set it up now? [y/N]" ;;
            botapi_skip)         value="Skipped — the limit stays at 50 MB. The question returns on the next run." ;;
            botapi_where)        value="Get the keys at: my.telegram.org -> API development tools" ;;
            botapi_id_ask)       value="api_id (digits only):" ;;
            botapi_hash_ask)     value="api_hash (32 characters):" ;;
            botapi_id_bad)       value="api_id must be digits — skipping" ;;
            botapi_hash_bad)     value="api_hash does not look right — skipping" ;;
            botapi_ready)        value="Own Bot API Server configured: the limit is now 2 GB" ;;
            botapi_have)         value="Own Bot API Server already configured" ;;
            botapi_disk)         value="Note: it caches files locally and needs noticeably more disk." ;;
            env_exists)          value="The .env file already exists" ;;
            env_reuse_ask)       value="Use the current settings? (Y/n):" ;;
            migrate_serve_failed) value="Could not start the temporary server — falling back to manual copying" ;;
            migrate_manual)      value="Copy the files by hand:" ;;
            migrate_manual_old)  value="On the OLD server:" ;;
            migrate_manual_new)  value="On the NEW server:" ;;
            migrate_manual_host) value="user@new-server" ;;
            migrate_manual_note) value="--restore without a filename picks the archive from the current directory; Docker is required on the new server" ;;
            migrate_mode_title)  value="How do you want to transfer the copy to the new server?" ;;
            migrate_mode_manual) value="By hand — copy the archive yourself (the reliable way)" ;;
            migrate_mode_manual_note) value="the file travels by any means (scp, a USB stick) and is deployed by the installer on the spot" ;;
            migrate_mode_link)   value="By a one-time link from this server (⚠️ not yet verified on a live move)" ;;
            migrate_mode_link_note) value="port 8899 must be reachable from the new server" ;;
            migrate_mode_choice) value="Choice [1]: " ;;
            step_restore)        value="Restoring from a copy" ;;
            restore_downloading) value="Downloading the copy" ;;
            restore_selfextract) value="Migration bundle detected: extracting the embedded copy" ;;
            restore_auto_empty)  value="No radar-backup-*.tar.gz next to the installer — put the archive in this directory or name it: --restore=FILE" ;;
            restore_auto_found)  value="Copy found next to the installer" ;;
            restore_download_failed) value="Download failed — is the link still alive?" ;;
            restore_url_cached)  value="The link did not open — using the copy downloaded by the previous run" ;;
            restore_unpacking)   value="Unpacking the copy" ;;
            restore_broken)      value="Could not unpack the copy — the file may be damaged" ;;
            restore_env)         value="Settings restored" ;;
            restore_no_env)      value="No .env in the copy — settings must be entered again" ;;
            restore_data)        value="Data files restored" ;;
            restore_dump)        value="Database dump ready to load" ;;
            restore_no_dump)     value="No database dump in the copy" ;;
            restore_bot_db)      value="Database files from a bot-made copy restored" ;;
            restore_no_data)     value="No dump or data files found in the copy — the bot will start with an empty database" ;;
            restore_continues)   value="A normal installation follows — it will bring the system up on this data" ;;
            step_integrity)      value="Integrity check after migration" ;;
            integrity_ok)        value="Data is in place" ;;
            integrity_failed)    value="Integrity check failed — data may not have transferred" ;;
            integrity_hint)      value="The copy is intact: restore it again or go back to the old machine" ;;
            *) value="" ;;
        esac
    fi
    if [ -z "$value" ]; then
        case "$key" in
            step_prepare)        value="Подготовка каталога и журнала установки" ;;
            step_check)          value="Проверка компонентов системы" ;;
            step_update)         value="Обновление компонентов системы" ;;
            step_previous)       value="Проверка предыдущей установки" ;;
            step_deploy)         value="Развёртывание файлов проекта" ;;
            step_settings)       value="Настройка параметров" ;;
            step_build)          value="Сборка образа и запуск контейнеров" ;;
            step_diagnose)       value="Проверка системы до запуска бота" ;;
            step_start)          value="Запуск бота" ;;
            time_report)         value="Затраченное время" ;;
            time_total)          value="ВСЕГО" ;;
            time_server)         value="время на сервере" ;;
            done_running)        value="Система «Радар» v%s запущена" ;;
            tls_botfather_title) value="Остался шаг — он делается в Telegram, а не на сервере:" ;;
            tls_botfather_open)  value="Откройте" ;;
            tls_botfather_pick)  value="Выберите своего бота из списка" ;;
            tls_botfather_send)  value="Пришлите адрес:" ;;
            tls_botfather_note)  value="Без этого виджет входа пишет «Bot domain invalid»." ;;
            tls_ask)             value="Открыть панель наружу по домену с HTTPS? [д/Н]" ;;
            tls_domain_ask)      value="Домен (например radar.example.ru):" ;;
            tls_domain_empty)    value="Домен не введён — пропускаю" ;;
            tls_domain_bad)      value="Это не похоже на домен:" ;;
            tls_found)           value="Сертификат уже настроен для" ;;
            tls_found_no_domain) value="Сертификат есть, но домен не настроен" ;;
            tls_short_missing)   value="Сократитель ссылок ещё не знает адрес — прописываю" ;;
            tls_short_differs)   value="Адрес коротких ссылок расходится с доменом сертификата — оставляю как есть" ;;
            tls_short_url)       value="Короткие ссылки будут вида" ;;
            tls_salt_created)    value="Соль для коротких кодов создана" ;;
            tls_salt_kept)       value="Существующая соль сохранена: смена сломала бы уже разосланные ссылки" ;;
            tls_script_missing)  value="Рядом с установкой нет tls.sh" ;;
            tls_failed)          value="Сертификат не выдан — смотрите вывод выше" ;;
            tls_restart_hint)    value="Перезапустите бота, чтобы настройки применились: docker compose restart" ;;
            updates_ask)         value="Обновлять пакеты системы? [Д/н]" ;;
            updates_skipped)     value="Пакеты системы обновляться не будут" ;;
            migrate_ask)         value="Переехать с этой установки на другой сервер? [д/Н]" ;;
            migrate_making_copy) value="Собираю копию для переезда" ;;
            migrate_copy_ready)  value="Копия готова" ;;
            migrate_port_busy)   value="Порт уже занят:" ;;
            action_title)        value="Что делаем?" ;;
            action_main)         value="Поставить последний код (main) — по умолчанию" ;;
            action_release)      value="Поставить конкретный релиз" ;;
            action_backup)       value="Только снять полную копию и выйти" ;;
            action_migrate)      value="Переехать на другой сервер" ;;
            action_choice)       value="Выбор" ;;
            versions_loading)    value="Получаю список релизов…" ;;
            versions_pick)       value="Номер или тег" ;;
            versions_fallback_main) value="Продолжаю с последним кодом из main" ;;
            version_selected)    value="Выбрано:" ;;
            backup_before)       value="Полная копия перед установкой" ;;
            backup_done)         value="Копия сохранена:" ;;
            versions_title)      value="Доступные версии" ;;
            versions_main)       value="последний код, возможно без релиза" ;;
            versions_failed)     value="Не удалось получить список релизов с GitHub" ;;
            versions_howto)      value="Поставить конкретную:" ;;
            step_fetch_version)  value="Загрузка выбранной версии" ;;
            version_unknown)     value="Такого релиза нет:" ;;
            version_download_failed) value="Не удалось скачать эту версию" ;;
            version_broken)      value="Скачанный установщик повреждён" ;;
            version_ready)       value="Установщик получен:" ;;
            version_handoff)     value="Передаю управление установщику этой версии…" ;;
            rollback_offer)      value="Откатиться на предыдущий релиз?" ;;
            step_migrate)        value="Сбор данных для переезда" ;;
            migrate_no_install)  value="Установка не найдена в $APP_DIR" ;;
            migrate_backup_failed) value="Не удалось собрать копию" ;;
            migrate_ready)       value="Выполните это на НОВОМ сервере:" ;;
            migrate_note_once)   value="Ссылка сработает ОДИН раз и сразу погаснет." ;;
            migrate_note_time)   value="Срок жизни — $extra минут, даже если ею не воспользуются." ;;
            migrate_note_port)   value="Порт $extra должен быть доступен с нового сервера." ;;
            migrate_note_secret) value="В копии токен бота и пароли — никому не пересылайте эту ссылку." ;;
            migrate_note_stop)   value="Когда новый бот ответит в Telegram, остановите старый:" ;;
            migrate_note_nat)    value="Не подключается? На роутере старого сервера пробросьте порт $extra на эту машину — без проброса ссылка не откроется." ;;
            migrate_bundle_ok)   value="Собран самодостаточный пакет: код и данные одним файлом" ;;
            migrate_downloaded)  value="Копия скачана новым сервером — перенос завершён" ;;
            migrate_expired)     value="Срок ссылки истёк, копия не скачана" ;;
            migrate_stopped)     value="Раздача остановилась раньше срока" ;;
            migrate_cancelled)   value="Ожидание отменено, раздача остановлена" ;;
            migrate_waiting_left) value="Жду скачивания… осталось" ;;
            db_title)            value="Какую базу данных использовать?" ;;
            db_sqlite_note)      value="(рекомендуется)" ;;
            db_sqlite_line1)     value="файл data/radar.db рядом с ботом, отдельный контейнер не нужен," ;;
            db_sqlite_line2)     value="ни пароля, ни ожидания запуска — подходит для 1–2 ГБ ОЗУ" ;;
            db_postgres_line)    value="отдельный контейнер, +300–500 МБ памяти; нужен на машине помощнее" ;;
            db_current)          value="Сейчас выбрано:" ;;
            db_switch_confirm)   value="Продолжить смену базы?" ;;
            dbmaint_title)       value="Обслуживание базы данных" ;;
            dbmaint_nothing)     value="Ничего не делать (по умолчанию)" ;;
            dbmaint_backup)      value="Снять копию базы" ;;
            dbmaint_recreate)    value="Снять копию, удалить базу и создать заново" ;;
            dbmaint_restore)     value="Восстановить базу из копии (доступно:" ;;
            existing_title)      value="Как поступить с существующей установкой?" ;;
            existing_update)     value="Обновление" ;;
            existing_update_note1) value="текущая версия обновится до новой из репозитория," ;;
            existing_update_note2) value="база, настройки и собранный образ сохраняются" ;;
            existing_reinstall)  value="Переустановка" ;;
            existing_reinstall_note1) value="образ и файлы проекта соберутся заново," ;;
            existing_reinstall_note2) value="база данных и .env сохраняются" ;;
            existing_clean)      value="С чистого листа" ;;
            existing_clean_note) value="удаление всех данных и установка с настройкой заново" ;;
            existing_backup)     value="Только резервная копия" ;;
            existing_backup_note) value="снять копию и выйти, ничего не меняя" ;;
            existing_note)       value="Перед любым из вариантов снимается резервная копия." ;;
            existing_diagnosis)  value="Диагностика" ;;
            existing_recommended) value="рекомендуется вариант" ;;
            botapi_title)        value="Собственный Bot API Server" ;;
            botapi_why)          value="Поднимает предел отправки с 50 МБ до 2 ГБ." ;;
            botapi_cost)         value="Нужны api_id и api_hash с my.telegram.org, и он кэширует файлы на диск." ;;
            botapi_ask)          value="Настроить сейчас? [д/Н]" ;;
            botapi_skip)         value="Пропущено — предел остаётся 50 МБ. Вопрос вернётся при следующем запуске." ;;
            botapi_where)        value="Ключи берутся на my.telegram.org -> API development tools" ;;
            botapi_id_ask)       value="api_id (только цифры):" ;;
            botapi_hash_ask)     value="api_hash (32 знака):" ;;
            botapi_id_bad)       value="api_id должен быть числом — пропускаю" ;;
            botapi_hash_bad)     value="api_hash не похож на настоящий — пропускаю" ;;
            botapi_ready)        value="Свой Bot API Server настроен: предел стал 2 ГБ" ;;
            botapi_have)         value="Свой Bot API Server уже настроен" ;;
            botapi_disk)         value="Учтите: он кэширует файлы локально и требует заметно больше диска." ;;
            env_exists)          value="Файл .env уже существует" ;;
            env_reuse_ask)       value="Использовать текущие настройки? (Y/n):" ;;
            migrate_serve_failed) value="Временный сервер не запустился — переношу копию вручную" ;;
            migrate_manual)      value="Скопируйте файлы руками:" ;;
            migrate_manual_old)  value="На СТАРОМ сервере:" ;;
            migrate_manual_new)  value="На НОВОМ сервере:" ;;
            migrate_manual_host) value="пользователь@новый-сервер" ;;
            migrate_manual_note) value="--restore без имени возьмёт архив из текущего каталога; на новом сервере нужен Docker" ;;
            migrate_mode_title)  value="Как передать копию на новый сервер?" ;;
            migrate_mode_manual) value="Вручную — скопировать архив самому (надёжный путь)" ;;
            migrate_mode_manual_note) value="файл едет любым способом (scp, флешка), установщик на месте развернёт его сам" ;;
            migrate_mode_link)   value="Одноразовой ссылкой с этого сервера (⚠️ на живом переезде ещё не проверено)" ;;
            migrate_mode_link_note) value="порт 8899 должен быть доступен новому серверу снаружи" ;;
            migrate_mode_choice) value="Выбор [1]: " ;;
            step_restore)        value="Разворачивание из копии" ;;
            restore_downloading) value="Скачиваю копию" ;;
            restore_selfextract) value="Обнаружен пакет переезда: извлекаю вложенную копию" ;;
            restore_auto_empty)  value="Рядом с установщиком нет файла radar-backup-*.tar.gz — положите архив в этот каталог или укажите имя: --restore=ФАЙЛ" ;;
            restore_auto_found)  value="Найдена копия рядом с установщиком" ;;
            restore_download_failed) value="Скачать не удалось — ссылка ещё жива?" ;;
            restore_url_cached)  value="Ссылка не открылась — использую копию, скачанную прошлым запуском" ;;
            restore_unpacking)   value="Распаковываю копию" ;;
            restore_broken)      value="Не удалось распаковать копию — файл повреждён?" ;;
            restore_env)         value="Настройки перенесены" ;;
            restore_no_env)      value="В копии нет .env — параметры придётся ввести заново" ;;
            restore_data)        value="Файлы данных перенесены" ;;
            restore_dump)        value="Дамп базы готов к заливке" ;;
            restore_no_dump)     value="В копии нет дампа базы" ;;
            restore_bot_db)      value="Файлы базы из копии бота перенесены" ;;
            restore_no_data)     value="В копии нет ни дампа базы, ни файлов данных — бот поднимется с пустой базой" ;;
            restore_continues)   value="Дальше идёт обычная установка — она поднимет систему на этих данных" ;;
            step_integrity)      value="Проверка целостности после переезда" ;;
            integrity_ok)        value="Данные на месте" ;;
            integrity_failed)    value="Проверка целостности не пройдена — данные могли не перенестись" ;;
            integrity_hint)      value="Копия цела: разверните её заново или вернитесь на старую машину" ;;
            *) value="$key" ;;
        esac
    fi
    printf '%s' "$value"
}

detect_language

# Спрашиваем язык в начале, если его не задали флагом и не запомнили
# раньше. Без терминала (curl | bash в конвейере) вопрос пропускаем:
# ждать ответа там некому, установка просто зависла бы.
ask_language() {
    # Язык задан флагом или переменной — не переспрашиваем.
    [ -n "${RADAR_LANG:-}" ] && return 0
    [ -n "${RADAR_ASKED:-}" ] && return 0

    # Проверяем ИМЕННО /dev/tty, а не stdin. При установке одной строкой
    # (`curl … | bash`) на stdin висит сам скрипт, поэтому `[ -t 0 ]`
    # всегда ложно — из-за этого вопрос не задавался никогда, хотя
    # терминал у человека был.
    #
    # И проверяем открытием, а не наличием: в контейнерах файл /dev/tty
    # существует, но открыть его нельзя («No such device or address»),
    # и проверка -e пропускала дальше — вопрос печатался, а чтение
    # тут же падало с ошибкой посреди установки.
    ( : < /dev/tty ) 2>/dev/null || return 0

    local stored=""
    if [ -f "$APP_DIR/.env" ]; then
        stored="$(grep -E '^INSTALLER_LANG=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
    fi

    # Значения через :- намеренно: функция должна работать, даже если её
    # позовут раньше блока с цветами. Вопрос о языке — не то место, где
    # установка имеет право упасть.
    printf "\n  %sChoose language / Выберите язык%s\n" \
        "${C_BOLD:-}" "${C_RESET:-}"
    printf "    1) Русский%s\n" "$([ "$stored" = "ru" ] && printf ' ✓' || true)"
    printf "    2) English%s\n" "$([ "$stored" = "en" ] && printf ' ✓' || true)"

    local default_choice="1"
    [ "$stored" = "en" ] && default_choice="2"
    printf "  %sВыбор / Choice [%s]:%s " \
        "${C_DIM:-}" "$default_choice" "${C_RESET:-}"

    local answer=""
    # Таймаут: при запуске из cron или чужого скрипта терминал может
    # существовать, но отвечать будет некому — молча ждать вечно нельзя.
    if ! read -r -t 60 answer < /dev/tty; then
        answer="$default_choice"
        printf "\n"
    fi
    : "${answer:=$default_choice}"

    case "$answer" in
        2|en|EN|english|English) LANG_CODE="en" ;;
        *) LANG_CODE="ru" ;;
    esac
    printf "\n"
}

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

# --------------------------------------------------------------------------
#  Что делаем (с 4.7.3.3)
# --------------------------------------------------------------------------
#
# Раньше всё это существовало только флагами: чтобы поставить релиз,
# переехать или снять копию, надо было знать про --version, --migrate
# и --backup. Человек, запустивший установщик одной строкой, о них
# не догадывался. Теперь те же действия предлагаются вопросом.
#
# Вопрос задаётся только при живом терминале и только если действие
# не задано флагом: автоматический запуск обязан работать по-прежнему.

ask_action() {
    # Вопросы уже заданы установщиком, который передал нам управление.
    [ -n "${RADAR_ASKED:-}" ] && return 0
    ( : < /dev/tty ) 2>/dev/null || return 0
    [ -n "$TARGET_VERSION" ] && return 0
    [ "$MIGRATE_OUT" = true ] && return 0
    [ "$BACKUP_ONLY" = true ] && return 0
    [ -n "$RESTORE_FROM$RESTORE_URL" ] && return 0
    [ "$LIST_VERSIONS" = true ] && return 0
    [ "$ROLLBACK_ONLY" = true ] && return 0
    [ "$FULL_RESET" = true ] && return 0

    printf "\n  %s%s%s\n" "${C_BOLD:-}" "$(t action_title)" "${C_RESET:-}"
    printf "    1) %s\n" "$(t action_main)"
    printf "    2) %s\n" "$(t action_release)"
    printf "    3) %s\n" "$(t action_backup)"
    printf "    4) %s\n" "$(t action_migrate)"
    printf "  %s%s [1]:%s " "${C_DIM:-}" "$(t action_choice)" "${C_RESET:-}"

    local answer=""
    read -r -t 120 answer < /dev/tty || answer="1"
    : "${answer:=1}"
    printf "\n"

    case "$answer" in
        2) choose_release ;;
        3) BACKUP_ONLY=true ;;
        4) MIGRATE_OUT=true ;;
        *) : ;;   # main — как и было
    esac

    ask_updates
}

# Собственный Bot API Server поднимает предел отправки с 50 МБ до 2 ГБ.
# Спрашиваем, но не настаиваем: ключи берутся на стороннем сайте, и человек
# может не иметь их под рукой прямо сейчас. Отказ ничего не записывает —
# значит при следующем запуске вопрос появится снова, и внести ключи можно
# будет когда угодно. Настойчивость здесь навредила бы: установка не должна
# упираться в то, за чем надо идти в браузер.
ask_bot_api_server() {
    local id_now hash_now answer api_id api_hash

    id_now="$(get_env_value TELEGRAM_API_ID)"
    hash_now="$(get_env_value TELEGRAM_API_HASH)"
    if [ -n "$id_now" ] && [ -n "$hash_now" ]; then
        # Уже настроено — доводим до конца, если адрес сервера не прописан.
        if [ -z "$(get_env_value TELEGRAM_API_SERVER)" ]; then
            set_env_value TELEGRAM_API_SERVER "http://telegram-bot-api:8081"
            set_env_value MEDIA_ENABLED 1
        fi
        ok "$(t botapi_have)"
        return 0
    fi

    # Без живого терминала спрашивать некого.
    if [ ! -t 0 ] && [ ! -e /dev/tty ]; then
        return 0
    fi

    echo
    printf "  %s%s%s\n" "$C_BOLD" "$(t botapi_title)" "$C_RESET"
    printf "  %s%s%s\n" "$C_DIM" "$(t botapi_why)" "$C_RESET"
    printf "  %s%s%s\n" "$C_DIM" "$(t botapi_cost)" "$C_RESET"
    printf "  %s " "$(t botapi_ask)"
    read -r answer < /dev/tty || answer="n"

    # Перечисление, а не скобочное выражение: в bash `[YyДд]` сравнивает
    # БАЙТЫ, а все кириллические буквы начинаются с 0xD0 — и «нет»
    # попадало бы в набор наравне с «да». Проверено на живом bash.
    case "$answer" in
        y|Y|yes|д|Д|да|ДА) : ;;
        *) info "$(t botapi_skip)"; return 0 ;;
    esac

    printf "  %s%s%s\n" "$C_DIM" "$(t botapi_where)" "$C_RESET"

    printf "  %s " "$(t botapi_id_ask)"
    read -r api_id < /dev/tty || api_id=""
    case "$api_id" in
        ''|*[!0-9]*) warn "$(t botapi_id_bad)"; return 0 ;;
    esac

    printf "  %s " "$(t botapi_hash_ask)"
    read -r api_hash < /dev/tty || api_hash=""
    # Хэш всегда 32 знака шестнадцатеричных. Проверяем длину и состав:
    # опечатка здесь выяснилась бы только при первой крупной отправке.
    if [ "${#api_hash}" -ne 32 ]; then
        warn "$(t botapi_hash_bad)"
        return 0
    fi
    case "$api_hash" in
        *[!0-9a-fA-F]*) warn "$(t botapi_hash_bad)"; return 0 ;;
    esac

    set_env_value TELEGRAM_API_ID "$api_id"
    set_env_value TELEGRAM_API_HASH "$api_hash"
    # Без адреса бот продолжал бы ходить в общий Telegram: контейнер
    # поднят, а толку нет. До 4.7.13 эта строка не выставлялась нигде,
    # и весь путь со своим сервером был мёртвым.
    set_env_value TELEGRAM_API_SERVER "http://telegram-bot-api:8081"
    set_env_value MEDIA_ENABLED 1

    ok "$(t botapi_ready)"
    info "$(t botapi_disk)"
    return 0
}

ask_updates() {
    [ -n "${RADAR_ASKED:-}" ] && return 0
    # Обновление пакетов системы — самый долгий шаг после сборки образа,
    # и на слабом канале оно может занять больше, чем всё остальное.
    # Иногда его сознательно пропускают: например, когда обновляют бот
    # третий раз за вечер и система заведомо свежая.
    [ "$SKIP_UPDATES" = true ] && return 0
    [ "$BACKUP_ONLY" = true ] && return 0
    [ "$MIGRATE_OUT" = true ] && return 0
    ( : < /dev/tty ) 2>/dev/null || return 0

    printf "  %s%s%s " "${C_DIM:-}" "$(t updates_ask)" "${C_RESET:-}"
    local answer=""
    read -r -t 60 answer < /dev/tty || answer="y"
    : "${answer:=y}"
    printf "\n"

    case "$answer" in
        n|N|н|Н|no|нет)
            SKIP_UPDATES=true
            info "$(t updates_skipped)"
            ;;
        *) : ;;
    esac
}

choose_release() {
    printf "  %s\n" "$(t versions_loading)"
    local versions
    versions="$(fetch_versions)"
    if [ -z "$versions" ]; then
        warn "$(t versions_failed)"
        printf "  %s\n\n" "$(t versions_fallback_main)"
        return 0
    fi

    printf "\n"
    local index=1
    printf '%s\n' "$versions" | head -15 | while read -r tag; do
        [ -n "$tag" ] && printf "    %s%2d)%s %s\n" \
            "${C_CYAN:-}" "$index" "${C_RESET:-}" "$tag"
        index=$((index + 1))
    done
    printf "  %s%s:%s " "${C_DIM:-}" "$(t versions_pick)" "${C_RESET:-}"

    local pick=""
    read -r -t 120 pick < /dev/tty || pick=""
    printf "\n"
    [ -z "$pick" ] && return 0

    local chosen=""
    case "$pick" in
        # Можно ввести и номер, и сам тег: человек видит перед собой список
        # с номерами, но привычнее бывает набрать «v4.6.1».
        ''|*[!0-9]*) chosen="$pick" ;;
        *) chosen="$(printf '%s\n' "$versions" | sed -n "${pick}p")" ;;
    esac

    if [ -z "$chosen" ]; then
        warn "$(t version_unknown) $pick"
        return 0
    fi
    TARGET_VERSION="$chosen"
    ok "$(t version_selected) $TARGET_VERSION"
}

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

# Полоса этапа рисуется в ОСНОВНОМ процессе, пока в фоне работает команда.
#
# Первый вариант делал наоборот — крутил полосу фоновым процессом, — и это
# оказалось ошибкой: фоновая полоса переживала свой этап, продолжала писать
# поверх чужого вывода, и к концу установки на экране крутились сразу
# несколько полос от разных шагов. Здесь убежать нечему: цикл кончается
# вместе с командой, потому что он её и ждёт.
erase_line() {
    [ "$HAS_TTY" = true ] || return 0
    printf "\r%s\r" "$(repeat ' ' $((COLS > 1 ? COLS - 1 : 40)))"
}

# Если установка оборвалась посреди полосы, строку надо стереть,
# иначе итоговое сообщение допишется в её хвост.
trap 'erase_line' EXIT

step_finish() {
    [ -n "$STEP_TITLE" ] || return 0
    erase_line
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
    printf "\n%s%s%s\n" "$C_BOLD" "$(t time_report)" "$C_RESET"
    # Без выравнивания колонкой: printf считает ширину в байтах, а кириллица
    # занимает по два — таблица разъехалась бы ровно на русских названиях.
    printf "%b" "$STEP_TIMES" | while IFS="$(printf '\t')" read -r name spent; do
        [ -n "$name" ] || continue
        printf "  %s%s%s — %s\n" "$C_DIM" "$name" "$C_RESET" "$(human_time "$spent")"
    done
    line
    printf "  %s%s%s — %s%s%s\n" "$C_BOLD" "$(t time_total)" "$C_RESET" \
        "$C_BOLD" "$(human_time "$total")" "$C_RESET"
    printf "  %s%s: %s%s\n" "$C_DIM" "$(t time_server)" "$(date "+%d.%m.%Y %H:%M:%S %Z")" "$C_RESET"
    log_raw "TIME  установка заняла ${total} с"
}
# Перевод сообщений по самому русскому тексту.
#
# Так сделано намеренно: сообщений больше восьмидесяти, и заводить каждому
# отдельный ключ означало бы править восемьдесят вызовов и держать их
# в согласии со словарём. Здесь русская строка И ЕСТЬ ключ — вызовы
# остаются как были, а непереведённое просто печатается по-русски.
#
# В журнал пишем всегда русский оригинал: журнал читает автор,
# и разнобой языков в нём только мешает искать.
tr_msg() {
    if [ "${LANG_CODE:-ru}" != "en" ]; then
        printf '%s' "$*"
        return 0
    fi
    case "$*" in
        "Бот вышел в рабочий режим") printf '%s' "The bot is up and running" ;;
        "Жду запуска бота (первый запуск — до 10 минут)") printf '%s' "Waiting for the bot (first start takes up to 10 minutes)" ;;
        "Запускаю диагностику внутри контейнера") printf '%s' "Running diagnostics inside the container" ;;
        "Диагностика пройдена без замечаний") printf '%s' "Diagnostics passed with no issues" ;;
        "Есть предупреждения, но запуск возможен") printf '%s' "There are warnings, but the start is possible" ;;
        "Собираю образ (первый раз это занимает 5-15 минут)") printf '%s' "Building the image (5-15 minutes the first time)" ;;
        "Образ собран") printf '%s' "Image built" ;;
        "Останавливаю прежние контейнеры") printf '%s' "Stopping the previous containers" ;;
        "База данных: SQLite (файл data/radar.db, отдельный контейнер не нужен)") printf '%s' "Database: SQLite (file data/radar.db, no separate container needed)" ;;
        "База данных: PostgreSQL (отдельный контейнер)") printf '%s' "Database: PostgreSQL (separate container)" ;;
        "Все пакеты актуальны") printf '%s' "All packages are up to date" ;;
        "Время синхронизировано") printf '%s' "Clock is synchronised" ;;
        "Время не синхронизировано — оповещения по расписанию будут смещаться") printf '%s' "Clock is not synchronised — scheduled alerts will drift" ;;
        "Найдена предыдущая установка") printf '%s' "Found a previous installation" ;;
        "Текущая установка работоспособна") printf '%s' "The current installation is healthy" ;;
        "Использую существующий .env") printf '%s' "Using the existing .env" ;;
        "Файл .env уже существует") printf '%s' "The .env file already exists" ;;
        "Найден том PostgreSQL") printf '%s' "Found a PostgreSQL volume" ;;
        "Найден том PostgreSQL от прежней версии") printf '%s' "Found a PostgreSQL volume from the previous version" ;;
        "Данные будут перенесены заново из data/db.json") printf '%s' "Data will be imported again from data/db.json" ;;
        "Содержимое прежней базы в новую автоматически не переносится") printf '%s' "Contents of the old database are NOT copied over automatically" ;;
        "Старая база остаётся на диске — вернуть выбор можно тем же меню") printf '%s' "The old database stays on disk — the same menu brings it back" ;;
        "База удалена, будет создана заново при запуске") printf '%s' "Database removed, it will be recreated on start" ;;
        "Удаляю базу") printf '%s' "Removing the database" ;;
        "Найдены данные версии 3.x — будут перенесены в базу") printf '%s' "Found 3.x data — it will be imported into the database" ;;
        "Контейнер бота не найден") printf '%s' "Bot container not found" ;;
        "Предыдущих установок не найдено") printf '%s' "No previous installation found" ;;
        "Способ задан ключом командной строки") printf '%s' "The mode was set by a command-line flag" ;;
        "Обновление поверх существующей установки") printf '%s' "Updating over the existing installation" ;;
        "Собираю резервную копию (перед установкой)") printf '%s' "Making a backup (before installing)" ;;
        "Контейнер базы не запущен — дамп пропущен") printf '%s' "Database container is not running — dump skipped" ;;
        "Сохраняю снимок текущей установки") printf '%s' "Saving a snapshot of the current installation" ;;
        "Распаковываю копию") printf '%s' "Unpacking the copy" ;;
        "Заливаю базу из копии") printf '%s' "Loading the database from the copy" ;;
        "База развёрнута из копии") printf '%s' "Database restored from the copy" ;;
        "Залить дамп не удалось — смотрите журнал") printf '%s' "Could not load the dump — see the log" ;;
        "Дамп базы не удался — копия будет без него") printf '%s' "Database dump failed — the copy will be without it" ;;
        "Загрузка видео будет работать с пределом 50 МБ") printf '%s' "Video download will work with a 50 MB limit" ;;
        "Загрузка видео: свой Bot API Server (файлы до 2 ГБ)") printf '%s' "Video download: own Bot API Server (files up to 2 GB)" ;;
        "Базу восстановить не удалось") printf '%s' "Could not restore the database" ;;
        "Восстановление отменено") printf '%s' "Restore cancelled" ;;
        "Восстановить не удалось — подробности в журнале") printf '%s' "Restore failed — details in the log" ;;
        "В копии нет манифеста — возможно, это не копия «Радара»") printf '%s' "No manifest in the copy — it may not be a Radar backup" ;;
        *) printf '%s' "$*" ;;
    esac
}

# Перед любой печатью гасим строку прогресса. Она рисуется через \r
# и остаётся на месте, пока её не затрут: без этого сообщение печатается
# ПОВЕРХ полосы, и на экране получается «[####...] 25% список пакетов
# обновлён ✓ Список пакетов актуален» — три состояния в одной строке.
info() {
    progress_done
    printf "  %s→%s %s\n" "$C_CYAN" "$C_RESET" "$(tr_msg "$*")"
    log_raw "INFO  $*"
}
ok() {
    progress_done
    printf "  %s✓%s %s\n" "$C_GREEN" "$C_RESET" "$(tr_msg "$*")"
    log_raw "OK    $*"
}
warn() {
    progress_done
    printf "  %s!%s %s\n" "$C_YELLOW" "$C_RESET" "$(tr_msg "$*")"
    log_raw "WARN  $*"
}

RELEASES_API="https://api.github.com/repos/Chistovik92/radar/releases"
RAW_BASE="https://raw.githubusercontent.com/Chistovik92/radar"

fetch_versions() {
    curl -fsSL --max-time 20 "$RELEASES_API" 2>/dev/null \
        | grep -oP '"tag_name"\s*:\s*"\K[^"]+' || true
}

run_questions() {
    # Вопросы задаются здесь, а не раньше по файлу. В bash функция должна
    # быть ОПРЕДЕЛЕНА к моменту вызова, а не просто присутствовать в файле:
    # прежний вызов не видел ни info(), ни fetch_versions(), объявленных
    # ниже, и падал с «command not found». Это место — первое, где
    # определено уже всё нужное, и при этом установка ещё ничего не сделала.
    ask_language
    ask_action
}



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
    # Без терминала анимация превращается в мусор из управляющих
    # последовательностей: при `curl | bash` и в CI её быть не должно.
    if [ "$HAS_TTY" != true ]; then
        info "$label"
        return 0
    fi
    # Второй спиннер поверх первого — источник каши на экране: полосы разных
    # шагов начинают перебивать друг друга. Прежний всегда гасим.
    spinner_stop
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
        # Строку обязательно затираем: иначе следующая печать допишется
        # в хвост полосы, и на экране остаются обрывки «сборка образа…».
        erase_line
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
remember_language() {
    # Запоминаем выбор, чтобы при следующем запуске не спрашивать снова.
    [ -f "$APP_DIR/.env" ] || return 0
    set_env_value INSTALLER_LANG "$LANG_CODE"
}

env_fix_perms() {     # права на .env: владелец — пользователь контейнера
    # В образе бот работает под uid 1000. Файл должен быть доступен ему
    # на чтение и запись, иначе раздел ключей снова станет декоративным.
    # Права 600 сохраняются: доступ только у владельца, не у всей машины.
    chown 1000:1000 "$APP_DIR/.env" 2>/dev/null || true
    chmod 600 "$APP_DIR/.env" 2>/dev/null || true
}

# С 4.8.4.2 .env смонтирован в контейнер. Bind-mount привязан к ИНОДУ,
# а `sed -i` пишет во временный файл и переименовывает его — инод меняется,
# и контейнер продолжает читать прежний файл, которого на хосте уже нет.
# Поэтому правим через временный файл, но возвращаем содержимое НА МЕСТО.
set_env_value() {     # set_env_value <ключ> <значение>
    local key="$1" value="$2" file="$APP_DIR/.env" tmp
    touch "$file"
    tmp="$(mktemp)" || { log_raw "ENV   временный файл не создан"; return 1; }
    if grep -qE "^${key}=" "$file"; then
        # Разделитель | — в значениях встречаются слэши (пути, URL)
        sed "s|^${key}=.*|${key}=${value}|" "$file" > "$tmp"
    else
        { cat "$file"; printf '%s=%s\n' "$key" "$value"; } > "$tmp"
    fi
    cat "$tmp" > "$file"
    rm -f "$tmp"
    env_fix_perms
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
    printf "  %s%s%s\n\n" "$C_BOLD" "$(t db_title)" "$C_RESET"
    printf "    1) SQLite %s%s%s\n" "$C_GREEN" "$(t db_sqlite_note)" "$C_RESET"
    printf "       %s%s%s\n" "$C_DIM" "$(t db_sqlite_line1)" "$C_RESET"
    printf "       %s%s%s\n" "$C_DIM" "$(t db_sqlite_line2)" "$C_RESET"
    printf "    2) PostgreSQL\n"
    printf "       %s%s%s\n" "$C_DIM" "$(t db_postgres_line)" "$C_RESET"

    if [ "$has_sqlite" = true ] || [ "$has_pg" = true ]; then
        echo
        [ "$has_sqlite" = true ] && info "Найдена база SQLite ($(du -h "$APP_DIR/data/radar.db" 2>/dev/null | cut -f1))"
        [ "$has_pg" = true ] && info "Найден том PostgreSQL"
    fi

    local default_choice=1
    [ "$current" = "postgres" ] && default_choice=2

    printf "\n  %s %s%s%s\n" "$(t db_current)" "$C_BOLD" "$current" "$C_RESET"
    printf "  %s [%d]: " "$(t action_choice)" "$default_choice"
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
            printf "  %s%s%s (y/N): " "$C_BOLD" "$(t db_switch_confirm)" "$C_RESET"
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

# Заливка дампа PostgreSQL. Общая для переезда и отката намеренно:
# переезд научился делать это сам ещё в 4.7.1, а откат до 4.7.6.5
# печатал команду и предлагал выполнить её руками — то есть ровно
# в тот момент, когда установка уже сломана и человеку не до psql.
# Две отдельные реализации разошлись бы: одну поправят, вторую забудут.
load_pg_dump() {      # load_pg_dump <файл дампа>
    local dump="$1" db_user db_name ready=false

    [ -n "$dump" ] && [ -f "$dump" ] || return 1

    db_user="$(get_env_value DB_USER)"; : "${db_user:=radar}"
    db_name="$(get_env_value DB_NAME)"; : "${db_name:=radar}"

    # Ждём готовности: psql в ещё не поднявшийся контейнер уйдёт впустую,
    # а дамп будет считаться залитым.
    for _ in $(seq 1 45); do
        if docker exec radar_db pg_isready -U "$db_user" >/dev/null 2>&1; then
            ready=true
            break
        fi
        sleep 2
    done
    if [ "$ready" != true ]; then
        warn "PostgreSQL не поднялся — дамп не залит"
        return 1
    fi

    info "Заливаю базу из копии"
    if docker exec -i radar_db psql -U "$db_user" -d "$db_name" \
            < "$dump" >>"$LOG_FILE" 2>&1; then
        ok "База развёрнута из копии"
        # Переименовываем, чтобы повторный запуск не залил дамп поверх
        # уже работающей базы.
        mv "$dump" "$dump.applied" 2>/dev/null || true
        return 0
    fi

    warn "Залить дамп не удалось — смотрите журнал"
    return 1
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

    info "Пересобираю образ прежней версии"
    if ! (cd "$APP_DIR" && run $COMPOSE build); then
        fail "Сборка прежней версии не удалась"
        return 1
    fi

    local snapshot_dump="$APP_DIR/data/postgres-dump.sql"
    local backend compose_args=""
    backend="$(get_env_value DB_BACKEND)"; : "${backend:=sqlite}"
    [ "$backend" = "postgres" ] && compose_args="--profile postgres"

    # Дамп заливается ДО старта бота: иначе бот создаст пустую схему,
    # и дамп ляжет поверх наполовину — часть таблиц из копии, часть новых.
    # Поэтому сперва поднимаем одну базу.
    if [ -f "$snapshot_dump" ] && [ "$backend" = "postgres" ]; then
        if (cd "$APP_DIR" && run $COMPOSE $compose_args up -d postgres); then
            load_pg_dump "$snapshot_dump" \
                || warn "Откат продолжается, но данные остались прежними"
        else
            warn "PostgreSQL не запустился — дамп из снимка не залит"
        fi
    elif [ -f "$snapshot_dump" ]; then
        # Дамп есть, а база теперь SQLite: залить нельзя — разные диалекты.
        # Промолчать тоже нельзя, иначе человек решит, что данные вернулись.
        warn "В снимке дамп PostgreSQL, а выбрана SQLite — залить нельзя"
        info "Дамп остался на месте: data/postgres-dump.sql"
    fi

    # Профиль postgres нужен и здесь: без него откат на установке
    # с PostgreSQL поднимал бота без базы.
    if ! (cd "$APP_DIR" && run $COMPOSE $compose_args up -d); then
        fail "Запуск прежней версии не удался"
        return 1
    fi

    ok "Откат выполнен, восстановлена версия $(installed_version)"
    return 0
}

previous_release() {
    # Предпоследний тег: последний — это, скорее всего, тот, что сломался.
    fetch_versions | sed -n '2p'
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
    printf "    %s3) %s%s\n" "$C_BOLD" "$(t rollback_offer)" "$C_RESET"
    printf "       %sскачать и поставить предыдущий релиз с GitHub%s\n" \
        "$C_DIM" "$C_RESET"
    printf "    %s4) Ничего не делать — разберусь сам%s\n\n" "$C_BOLD" "$C_RESET"
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
        3)
            # Снимок мог не помочь, если сломан сам код: тогда берём
            # предыдущий релиз с GitHub — заведомо рабочий, его уже ставили.
            local previous
            previous="$(previous_release)"
            if [ -z "$previous" ]; then
                warn "$(t versions_failed)"
                return 1
            fi
            info "Ставлю предыдущий релиз: $previous"
            local older
            older="$(mktemp)"
            if curl -fsSL --max-time 60 -o "$older" \
                    "$RAW_BASE/$previous/install.sh" && bash -n "$older" 2>/dev/null; then
                exec bash "$older" --lang="$LANG_CODE"
            fi
            rm -f "$older"
            warn "$(t version_download_failed)"
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

run_questions

# Режимы, которые выходят до установки. Стоят здесь, а не ниже: показывать
# список релизов, пройдя через создание каталога и журнала, незачем —
# человек просил справку, а не установку.
if [ "$LIST_VERSIONS" = true ]; then
    banner
    printf "  %s%s%s\n\n" "$C_BOLD" "$(t versions_title)" "$C_RESET"
    versions="$(fetch_versions)"
    if [ -z "$versions" ]; then
        warn "$(t versions_failed)"
        exit 1
    fi
    printf "    %smain%s — %s\n" "$C_CYAN" "$C_RESET" "$(t versions_main)"
    printf '%s\n' "$versions" | while read -r tag; do
        [ -n "$tag" ] && printf "    %s%s%s\n" "$C_CYAN" "$tag" "$C_RESET"
    done
    printf "\n  %s\n" "$(t versions_howto)"
    printf "    sudo bash install.sh --version=v4.6.1\n\n"
    exit 0
fi

if [ -n "$TARGET_VERSION" ] && [ "$TARGET_VERSION" != "main" ]; then
    banner
    step "$(t step_fetch_version)"

    # Проверяем, что такая версия существует: иначе curl молча скачает
    # страницу 404 и мы попытаемся выполнить HTML как скрипт.
    if ! fetch_versions | grep -qx "$TARGET_VERSION"; then
        warn "$(t version_unknown) $TARGET_VERSION"
        printf "  %s\n" "$(t versions_howto)"
        printf "    sudo bash install.sh --versions\n\n"
        exit 1
    fi

    NEW_INSTALLER="$(mktemp)"
    if ! curl -fsSL --max-time 60 -o "$NEW_INSTALLER" \
            "$RAW_BASE/$TARGET_VERSION/install.sh"; then
        rm -f "$NEW_INSTALLER"
        die "$(t version_download_failed)"
    fi

    # Скачанное — тоже bash-скрипт, и он может быть повреждён при передаче.
    if ! bash -n "$NEW_INSTALLER" 2>/dev/null; then
        rm -f "$NEW_INSTALLER"
        die "$(t version_broken)"
    fi

    ok "$(t version_ready) $TARGET_VERSION"
    printf "  %s\n\n" "$(t version_handoff)"
    # Передаём управление установщику нужной версии, убрав --version,
    # иначе он попытается скачать сам себя по кругу.
    # RADAR_ASKED=1: установщик нужной версии не должен спрашивать заново
    # то, на что человек уже ответил здесь. На фото это выглядело так:
    # выбрал релиз, ответил про обновления — и получил те же вопросы ещё раз.
    RADAR_ASKED=1 RADAR_LANG="$LANG_CODE" \
        exec bash "$NEW_INSTALLER" ${SKIP_UPDATES:+--skip-updates} \
        --lang="$LANG_CODE"
fi

banner

# --------------------------------------------------------------------------
#  Шаг 1. Каталог и лог
# --------------------------------------------------------------------------

remember_language
step "$(t step_prepare)"

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
    printf "\n  Восстановление: %s --restore=%s\n\n" "$0" "$BACKUP_PATH"
    exit 0
fi

# Удаление с сохранением данных. До 4.8.4 флаг парсился, но ветки
# исполнения не было вовсе: молчаливый no-op — флаг из справки,
# который ничего не делает. Удаляются контейнеры и образ; база, .env
# и копии остаются в каталоге установки. Для удаления всего целиком
# существует отдельный скрипт — он печатается подсказкой ниже.
if [ "$UNINSTALL" = true ]; then
    COMPOSE="docker compose"
    docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"
    step "Удаление «Радара» (данные сохраняются)"
    if command -v docker >/dev/null 2>&1; then
        if [ -d "$APP_DIR" ]; then
            (cd "$APP_DIR" && run $COMPOSE down --remove-orphans) || true
        fi
        run docker rm -f "$CONTAINER_NAME" radar_db radar_bot_api radar_singbox 2>/dev/null || true
        run docker rmi -f "$IMAGE_NAME" 2>/dev/null || true
        ok "Контейнеры и образ удалены"
    else
        warn "Docker не найден — контейнеры и образ, если они есть, остались"
    fi
    info "Данные и настройки сохранены в $APP_DIR"
    printf "\n  %s\n" "Полное удаление вместе с данными:"
    printf "    curl -fsSLo uninstall.sh https://raw.githubusercontent.com/Chistovik92/radar/main/tools/uninstall.sh\n"
    printf "    bash uninstall.sh\n\n"
    log_raw "UNINSTALL: контейнеры и образ удалены, данные сохранены"
    exit 0
fi

# --------------------------------------------------------------------------
#  Переезд на другую машину (с 4.7.1)
# --------------------------------------------------------------------------
#
# Две команды вместо десятка ручных шагов. На старой машине --migrate
# снимает копию и печатает, что делать дальше; на новой --restore=ФАЙЛ
# разворачивает систему и сверяет, что данные доехали.
#
# Бот на старой машине НЕ выключается автоматически: два одновременно
# работающих экземпляра с одним токеном будут отбирать друг у друга
# обновления, но решать, когда переключаться, должен человек — иначе
# неудачный переезд оставит без оповещений и старую систему, и новую.

# --- разворачивание из копии (вторая половина переезда) --------------------
#
# Копию раскладываем ДО обычной установки: дальше идёт штатный путь, который
# видит готовый .env и файлы данных и ведёт себя как при обновлении. Так
# переезд использует уже проверенный код, а не отдельную ветку, которую
# никто не запускает.
unpack_migration() {   # unpack_migration <архив>
    local archive="$1" staging flat
    [ -f "$archive" ] || die "Файл копии не найден: $archive"

    staging="$(mktemp -d)"
    info "$(t restore_unpacking)"
    tar -xzf "$archive" -C "$staging" 2>>"$LOG_FILE" \
        || die "$(t restore_broken)"

    if [ -f "$staging/manifest.txt" ]; then
        printf "  %sСодержимое копии%s\n" "$C_BOLD" "$C_RESET"
        sed 's/^/    /' "$staging/manifest.txt"
    else
        warn "В копии нет манифеста — возможно, это не копия «Радара»"
    fi

    mkdir -p "$APP_DIR/data"

    if [ -f "$staging/env.backup" ]; then
        cp "$staging/env.backup" "$APP_DIR/.env"
        # Права ниоткуда не наследуются: в архив копия попадает обычным
        # cp, а разворачивается в файл, которого на новой машине ещё
        # не было. Без явной установки .env оставался читаемым всей
        # машиной — с токеном бота и паролем базы внутри.
        env_fix_perms
        ok "$(t restore_env)"
    else
        warn "$(t restore_no_env)"
    fi

    if [ -d "$staging/data" ]; then
        cp -r "$staging/data/." "$APP_DIR/data/" 2>/dev/null || true
        ok "$(t restore_data)"
    fi

    # Копии, снятые самим ботом (radar/backup.py — ночные и из панели),
    # кладут файлы базы россыпью в корень архива: radar.db, radar.db-wal,
    # radar.db-shm, db.json. Каталога data/ в них нет. До 4.8.2.2
    # установщик молча выбрасывал эти файлы: .env переносился, бот
    # поднимался с теми же токенами, но с пустой базой — без
    # пользователей, локаций и источников. Нашлось на живом переезде.
    flat=""
    for dbfile in radar.db radar.db-wal radar.db-shm db.json; do
        if [ -f "$staging/$dbfile" ]; then
            cp "$staging/$dbfile" "$APP_DIR/data/$dbfile"
            flat="$flat $dbfile"
        fi
    done
    if [ -n "$flat" ]; then
        ok "$(t restore_bot_db):$flat"
    fi

    if [ -f "$staging/database.sql" ]; then
        cp "$staging/database.sql" "$APP_DIR/data/migration-database.sql"
        MIGRATION_DUMP="$APP_DIR/data/migration-database.sql"
        ok "$(t restore_dump): $(du -h "$MIGRATION_DUMP" | cut -f1)"
    else
        warn "$(t restore_no_dump)"
    fi

    # Молчаливый пропуск данных — то, из-за чего эта правка существует.
    # Если в копии нет ни одного известного носителя данных, говорим
    # об этом вслух, а не позволяем бот подняться с пустой базой.
    if [ -z "$flat" ] && [ ! -d "$staging/data" ] \
        && [ ! -f "$staging/database.sql" ]; then
        warn "$(t restore_no_data)"
    fi

    rm -rf "$staging"
}

MIGRATION_DUMP=""

# Самодостаточный пакет переезда (с 4.8.3). Старый сервер отдаёт по
# ссылке файл: обычный install.sh, к которому сзади приклеены
# строка-маркер и сама копия. Новому серверу не нужен ни GitHub,
# ни выбор способа установки: скачал один файл — запустил файлом.
# Здесь установщик находит маркер в самом себе, отрезает копию
# и дальше идёт штатный путь --restore.
SELF_PAYLOAD_LINE=""
if [ -f "$SELF_PATH" ] && grep -q '^RADAR_MIGRATION_PAYLOAD_BELOW$' "$SELF_PATH" 2>/dev/null; then
    # -a обязателен: у пакета позади маркера лежит бинарная копия,
    # и без него grep печатает «Binary file matches» вместо номера строки.
    SELF_PAYLOAD_LINE="$(grep -an '^RADAR_MIGRATION_PAYLOAD_BELOW$' "$SELF_PATH" 2>/dev/null | head -n 1 | cut -d: -f1)"
fi
if [ -n "$SELF_PAYLOAD_LINE" ]; then
    mkdir -p "$APP_DIR"
    RESTORE_FROM="$APP_DIR/migration-incoming.tar.gz"
    info "$(t restore_selfextract)"
    tail -n +"$((SELF_PAYLOAD_LINE + 1))" "$SELF_PATH" > "$RESTORE_FROM" \
        || die "$(t restore_broken)"
fi

# --restore без имени: копия ищется рядом с установщиком (с 4.8.3.1).
# Ручной переезд сводится к «положил архив в каталог — запустил скрипт».
# Разрешается здесь, до любых переходов в другие каталоги.
if [ "$RESTORE_AUTO" = true ]; then
    RESTORE_FROM="$(find . -maxdepth 1 -name 'radar-backup-*.tar.gz' 2>/dev/null \
        | sort -r | head -n 1 || true)"
    [ -n "$RESTORE_FROM" ] || die "$(t restore_auto_empty)"
    ok "$(t restore_auto_found): $(basename "$RESTORE_FROM")"
fi

if [ -n "$RESTORE_URL" ]; then
    banner
    step "$(t step_restore)"
    mkdir -p "$APP_DIR"
    RESTORE_FROM="$APP_DIR/migration-incoming.tar.gz"
    info "$(t restore_downloading)"
    # --fail: сервер отдаёт 404 на просроченную или уже использованную
    # ссылку, и без этого флага curl сохранил бы страницу ошибки как архив.
    # Скачиваем во временный файл: прямая запись затирала бы копию,
    # скачанную прошлым запуском, — а повторный запуск после установки
    # Docker должен уметь обойтись без новой ссылки.
    if ! curl -fsSL --max-time 900 -o "$RESTORE_FROM.tmp" "$RESTORE_URL"; then
        rm -f "$RESTORE_FROM.tmp"
        if [ -f "$RESTORE_FROM" ]; then
            warn "$(t restore_url_cached)"
        else
            die "$(t restore_download_failed)"
        fi
    else
        mv -f "$RESTORE_FROM.tmp" "$RESTORE_FROM"
    fi
    ok "$(t restore_downloading): $(du -h "$RESTORE_FROM" | cut -f1)"
fi

if [ -n "$RESTORE_FROM" ]; then
    banner
    step "$(t step_restore)"
    mkdir -p "$APP_DIR"
    # Путь может быть относительным — приводим к абсолютному до перехода
    # в каталог установки, иначе файл «потеряется».
    case "$RESTORE_FROM" in
        /*) : ;;
        *)  RESTORE_FROM="$(pwd)/$RESTORE_FROM" ;;
    esac
    unpack_migration "$RESTORE_FROM"
    RESTORED=true
    info "$(t restore_continues)"
fi

# Раздача копии по временной ссылке.
#
# Копия содержит .env: токен бота, пароль базы, ключи API. Отдавать её
# открытым HTTP означает выложить всё это в сеть, поэтому раздача:
#   * защищена одноразовым путём со случайным токеном в 32 знака —
#     подобрать за время жизни ссылки нереально;
#   * отдаёт файл ОДИН раз и сразу выключается;
#   * живёт ограниченное время и гасится по таймауту, даже если о ней забыли;
#   * работает по HTTP без шифрования — поэтому ссылка одноразовая
#     и короткоживущая, а не «пусть повисит».
kill_stale_serve() {
    # Повторный запуск переезда гасит раздачу прошлой попытки: та живёт
    # до получаса после выдачи ссылки и всё это время держит порт.
    # Случилось на живом сервере: повтор упёрся в занятый порт и ушёл
    # в ручной перенос, хотя человеку была нужна новая ссылка.
    if command -v pkill >/dev/null 2>&1 \
        && pkill -f "$APP_DIR/.migrate-serve.py" 2>/dev/null; then
        sleep 1
    fi
    return 0
}

print_manual_migration() {
    # Ручной перенос — путь на случай, когда раздача не поднялась:
    # сервер не запустился или порт занят чужим процессом. С 4.8.3.1
    # это и самостоятельный способ переезда: установщик спрашивает,
    # как передавать копию, и ручной — вариант по умолчанию.
    # Команды разделены по серверам, а на новой машине установщику
    # достаточно --restore без имени: архив берётся из текущего каталога.
    printf "\n  %s\n\n" "$(t migrate_manual)"
    printf "  %s\n" "$(t migrate_manual_old)"
    printf "    scp %s %s:~/\n" "$BACKUP_PATH" "$(t migrate_manual_host)"
    printf "\n  %s\n" "$(t migrate_manual_new)"
    printf "    curl -fsSLo radar-install.sh %s\n" "$INSTALLER_URL"
    printf "    sudo bash radar-install.sh --restore\n\n"
    printf "  %s\n\n" "$(t migrate_manual_note)"
}

build_migration_bundle() {   # build_migration_bundle <копия>
    # Склейка самодостаточного пакета: установщик + маркер + копия одним
    # файлом. Если собрать не вышло (установщик запущен потоком, а GitHub
    # недоступен), вернём неудачу — раздача пойдёт простой копией
    # с командами из GitHub, как раньше.
    local backup="$1" src=""
    MIGRATION_BUNDLE=""

    if [ -n "$SELF_PATH" ]; then
        src="$SELF_PATH"
    else
        curl -fsSL --max-time 60 -o "$APP_DIR/.migrate-installer.sh" \
            "$INSTALLER_URL" 2>>"$LOG_FILE" || true
        if [ -s "$APP_DIR/.migrate-installer.sh" ] \
            && head -c 2 "$APP_DIR/.migrate-installer.sh" | grep -q '#!'; then
            src="$APP_DIR/.migrate-installer.sh"
        fi
    fi
    [ -n "$src" ] || return 1

    MIGRATION_BUNDLE="$APP_DIR/.migrate-bundle.sh"
    # Источник сам может оказаться пакетом (переезд запустили из
    # скачанного пакета): отрезаем его собственный хвост, иначе
    # в новом файле оказалось бы два маркера и две копии.
    # grep с -a: бинарный хвост пакета иначе даёт «Binary file matches».
    if grep -q '^RADAR_MIGRATION_PAYLOAD_BELOW$' "$src" 2>/dev/null; then
        local cut_at
        cut_at="$(grep -an '^RADAR_MIGRATION_PAYLOAD_BELOW$' "$src" | head -n 1 | cut -d: -f1)"
        head -n "$((cut_at - 1))" "$src" > "$MIGRATION_BUNDLE" \
            || { MIGRATION_BUNDLE=""; return 1; }
    else
        cat "$src" > "$MIGRATION_BUNDLE" \
            || { MIGRATION_BUNDLE=""; return 1; }
    fi
    printf '\nRADAR_MIGRATION_PAYLOAD_BELOW\n' >> "$MIGRATION_BUNDLE"
    cat "$backup" >> "$MIGRATION_BUNDLE" \
        || { MIGRATION_BUNDLE=""; return 1; }
    [ -s "$MIGRATION_BUNDLE" ] || { MIGRATION_BUNDLE=""; return 1; }
    return 0
}

serve_migration() {   # serve_migration <файл> <порт> <минут>
    local file="$1" port="$2" minutes="$3" token
    token="$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)"
    [ -n "$token" ] || die "Не удалось получить случайный токен"

    local runner=""
    if command -v python3 >/dev/null 2>&1; then
        runner="python3"
    elif docker image inspect radar:latest >/dev/null 2>&1; then
        runner="docker"
    else
        return 1
    fi

    cat > "$APP_DIR/.migrate-serve.py" <<'RADAR_SERVE_EOF'
"""Одноразовая раздача файла копии.

Отдаёт один файл по секретному пути ровно один раз, затем выключается.
Всё остальное получает 404 без подсказок: сканеру не за что зацепиться.
"""
import http.server
import os
import sys
import threading

PATH = "/" + sys.argv[1]
FILE = sys.argv[2]
PORT = int(sys.argv[3])
TIMEOUT = int(sys.argv[4]) * 60
DONE = sys.argv[5] if len(sys.argv) > 5 else ""

done = threading.Event()


class Once(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != PATH or done.is_set():
            self.send_error(404)
            return
        done.set()
        size = os.path.getsize(FILE)
        self.send_response(200)
        self.send_header("Content-Type", "application/gzip")
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition",
            'attachment; filename="%s"' % os.path.basename(FILE),
        )
        self.end_headers()
        with open(FILE, "rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        # Отметка для установщика на этой машине: он ждёт скачивания
        # с обратным отсчётом и по этому файлу понимает, что всё получилось.
        if DONE:
            try:
                with open(DONE, "w") as handle:
                    handle.write("ok")
            except OSError:
                pass
        threading.Timer(1.0, server.shutdown).start()

    def log_message(self, *_args):
        pass


server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Once)
threading.Timer(TIMEOUT, server.shutdown).start()
server.serve_forever()
RADAR_SERVE_EOF

    mkdir -p "$APP_DIR/.migrate-state"
    rm -f "$APP_DIR/.migrate-state/done"
    SERVE_DONE="$APP_DIR/.migrate-state/done"

    if [ "$runner" = "python3" ]; then
        nohup python3 "$APP_DIR/.migrate-serve.py" \
            "$token" "$file" "$port" "$minutes" "$SERVE_DONE" >>"$LOG_FILE" 2>&1 &
    else
        nohup docker run --rm -p "$port:$port" \
            -v "$file:/copy.tar.gz:ro" \
            -v "$APP_DIR/.migrate-serve.py:/serve.py:ro" \
            -v "$APP_DIR/.migrate-state:/state" \
            radar:latest python /serve.py "$token" /copy.tar.gz "$port" "$minutes" /state/done \
            >>"$LOG_FILE" 2>&1 &
    fi

    SERVE_PID=$!
    sleep 1
    kill -0 "$SERVE_PID" 2>/dev/null || return 1
    # Процесс жив — но мог не открыть сокет (порт перехвачен между
    # проверкой занятости и стартом, не хватило прав). Ссылка тогда
    # мертва, и узнать об этом лучше сейчас, а не по «не подключается»
    # на новом сервере.
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | grep -q ":$port " || return 1
    fi
    SERVE_TOKEN="$token"
    return 0
}

detect_address() {
    # Внешний адрес полезнее локального: переезжают обычно между машинами,
    # а не внутри одной. Если узнать не вышло — отдаём локальный, человек
    # подставит нужный сам.
    local address=""
    address="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
    if [ -z "$address" ]; then
        address="$(hostname -I 2>/dev/null | awk '{print $1}')"
    fi
    printf '%s' "${address:-АДРЕС-СТАРОГО-СЕРВЕРА}"
}

wait_for_download() {   # wait_for_download <pid> <минуты>
    # До 4.8.3 здесь печаталось «Жду скачивания… Ctrl+C — отменить» —
    # и скрипт немедленно выходил: раздача жила в фоне, а человек видел
    # приглашение оболочки и делал вывод, что всё закончилось. Сообщение
    # обещало ожидание, которого не было. Теперь ожидание настоящее:
    # обратный отсчёт, отметка о скачивании, Ctrl+C действительно отменяет.
    local pid="$1" total=$(( $2 * 60 )) elapsed=0 left result=0
    trap 'kill "$pid" 2>/dev/null; printf "\n\n"; warn "$(t migrate_cancelled)"; exit 130' INT
    while :; do
        if [ -f "$SERVE_DONE" ]; then
            rm -f "$SERVE_DONE"
            printf "\n\n"
            ok "$(t migrate_downloaded)"
            result=0
            break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            printf "\n\n"
            warn "$(t migrate_stopped)"
            result=1
            break
        fi
        if [ "$elapsed" -ge "$total" ]; then
            printf "\n\n"
            warn "$(t migrate_expired)"
            kill "$pid" 2>/dev/null || true
            result=1
            break
        fi
        left=$(( total - elapsed ))
        printf "\r  %s %02d:%02d\033[K" "$(t migrate_waiting_left)" \
            "$((left / 60))" "$((left % 60))"
        sleep 5
        elapsed=$((elapsed + 5))
    done
    trap - INT
    return "$result"
}

cleanup_migration_files() {
    # Вызывается, когда раздача закончилась: временные файлы не нужны.
    # Без терминала ожидание пропускается, раздача продолжает жить —
    # там чистить нельзя, файл ещё раздаётся.
    rm -f "$APP_DIR/.migrate-serve.py" "$APP_DIR/.migrate-bundle.sh" \
        "$APP_DIR/.migrate-installer.sh" 2>/dev/null || true
    rm -rf "$APP_DIR/.migrate-state" 2>/dev/null || true
    return 0
}

ask_migration_mode() {   # печатает manual | link
    # Способ переезда спрашивается явно (с 4.8.3.1). Ручной перенос —
    # путь проверенный: файл едет scp-ом, установщик на новой машине
    # разворачивает его сам, портов и раздач не нужно. Ссылка удобнее,
    # но на живом переезде ещё не проверена — и человек должен знать,
    # что выбирает. По умолчанию ручной.
    printf "\n  %s\n\n" "$(t migrate_mode_title)"
    printf "  1) %s\n" "$(t migrate_mode_manual)"
    printf "     %s\n" "$(t migrate_mode_manual_note)"
    printf "  2) %s\n" "$(t migrate_mode_link)"
    printf "     %s\n\n" "$(t migrate_mode_link_note)"
    printf "  %s" "$(t migrate_mode_choice)"
    local answer="1"
    read -r answer < /dev/tty || answer="1"
    printf "\n"
    case "$answer" in
        2|link|ссылка) printf '%s' "link" ;;
        *)             printf '%s' "manual" ;;
    esac
}

# --------------------------------------------------------------------------
#  Установка выбранной версии из GitHub (с 4.7.3.1)
# --------------------------------------------------------------------------
#
# Три сценария, которые раньше делались руками:
#   --version=v4.6.1  поставить конкретный релиз (в том числе более старый —
#                     это и есть откат на предыдущую версию);
#   --versions        показать, что вообще доступно;
#   по умолчанию      ставится код из main, независимо от того, оформлен
#                     он релизом или нет: на сервере автора должна
#                     оказываться последняя версия, а не последняя
#                     помеченная тегом.
#
# Откат намеренно не запрещён и не требует подтверждения: если новая
# версия сломалась, человеку нужно вернуться назад немедленно, а не
# доказывать установщику, что он понимает последствия. Предупреждение
# выводится, снимок снимается — этого достаточно.


if [ "$MIGRATE_OUT" = true ]; then
    [ -d "$APP_DIR" ] || die "$(t migrate_no_install)"
    cd "$APP_DIR"
    banner
    step "$(t step_migrate)"

    make_backup "переезд" || die "$(t migrate_backup_failed)"

    # Способ передачи копии спрашиваем явно; без терминала — ссылка,
    # как было: там выбора всё равно не показать.
    MIGRATE_MODE="link"
    if ( : < /dev/tty ) 2>/dev/null; then
        MIGRATE_MODE="$(ask_migration_mode)"
    fi
    if [ "$MIGRATE_MODE" = "manual" ]; then
        print_manual_migration
        log_raw "MIGRATE ручной перенос, копия: $BACKUP_PATH"
        timing_report
        exit 0
    fi

    SERVE_PORT="${MIGRATE_PORT:-8899}"
    SERVE_MINUTES="${MIGRATE_MINUTES:-30}"
    SERVE_TOKEN=""
    SERVE_PID=""
    SERVE_FILE="$BACKUP_PATH"
    SERVE_BUNDLE=false

    kill_stale_serve
    if build_migration_bundle "$BACKUP_PATH"; then
        SERVE_FILE="$MIGRATION_BUNDLE"
        SERVE_BUNDLE=true
        ok "$(t migrate_bundle_ok)"
    fi
    if serve_migration "$SERVE_FILE" "$SERVE_PORT" "$SERVE_MINUTES"; then
        ADDRESS="$(detect_address)"
        LINK="http://$ADDRESS:$SERVE_PORT/$SERVE_TOKEN"

        line
        printf "  %s%s%s\n\n" "$C_BOLD" "$(t migrate_ready)" "$C_RESET"
        if [ "$SERVE_BUNDLE" = true ]; then
            # Пакет самодостаточен: код бота и данные одним файлом,
            # GitHub новому серверу не нужен. Про лимит ядра на длину
            # аргумента — см. комментарий выше: качаем в файл,
            # запускаем файлом.
            printf "  %s%s%s\n" "$C_CYAN" \
                "curl -fsSLo radar-restore.sh $LINK" "$C_RESET"
            printf "  %s%s%s\n\n" "$C_CYAN" \
                "sudo bash radar-restore.sh" "$C_RESET"
        else
            printf "  %s%s%s\n" "$C_CYAN" \
                "curl -fsSLo radar-install.sh $INSTALLER_URL" "$C_RESET"
            printf "  %s%s%s\n\n" "$C_CYAN" \
                "sudo bash radar-install.sh --restore-url=$LINK" "$C_RESET"
        fi
        line
        printf "  %s\n" "$(t migrate_note_once)"
        printf "  %s\n" "$(t migrate_note_time "$SERVE_MINUTES")"
        printf "  %s\n" "$(t migrate_note_port "$SERVE_PORT")"
        printf "  %s\n" "$(t migrate_note_nat "$SERVE_PORT")"
        printf "  %s\n\n" "$(t migrate_note_secret)"
        printf "  %s\n" "$(t migrate_note_stop)"
        printf "    cd %s && docker compose down\n\n" "$APP_DIR"
        log_raw "MIGRATE ссылка выдана, порт $SERVE_PORT, срок $SERVE_MINUTES мин, пакет: $SERVE_BUNDLE"
        # Ожидание — только при живом терминале: без него скрипт
        # закончит работу, а фоновая раздача продолжит жить свой срок.
        if ( : < /dev/tty ) 2>/dev/null; then
            wait_for_download "$SERVE_PID" "$SERVE_MINUTES" \
                || print_manual_migration
            cleanup_migration_files
        fi
    else
        warn "$(t migrate_serve_failed)"
        print_manual_migration
    fi
    timing_report
    exit 0
fi

# --------------------------------------------------------------------------
#  Шаг 2. Проверка окружения
# --------------------------------------------------------------------------

step "$(t step_check)"

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
    # При разворачивании из копии повторный запуск ничего не теряет:
    # пакет переезда и скачанная копия — локальные файлы, новая ссылка
    # со старого сервера не нужна. Молчание об этом стоило живого
    # переезда: человек упёрся в отсутствие Docker и унёс файлы руками.
    if [ "$RESTORED" = true ]; then
        echo
        printf "  %s\n" "Данные из копии уже развёрнуты в $APP_DIR."
        printf "  %s\n" "После установки Docker запустите тот же файл той же командой —"
        printf "  %s\n" "новая ссылка и повторный перенос не нужны."
    fi
    die "Не хватает обязательных компонентов"
fi

# --------------------------------------------------------------------------
#  Шаг 3. Обновление системы
# --------------------------------------------------------------------------

step "$(t step_update)"

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
    # grep -c печатает «0» и при этом выходит с кодом 1, когда совпадений
    # нет. Прежняя конструкция «grep -c ... || echo 0» дописывала второй
    # ноль, переменная становилась «0\n0», и сравнение падало с
    # «integer expression expected». Ошибка не останавливала установку,
    # но печаталась в отчёт при каждом запуске на актуальной системе.
    UPGRADABLE=$(apt-get -s upgrade 2>/dev/null | grep -c '^Inst' || true)
    # Пояс поверх подтяжек: что бы ни пришло, в сравнение уйдёт число.
    case "$UPGRADABLE" in
        ''|*[!0-9]*) UPGRADABLE=0 ;;
    esac
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

step "$(t step_previous)"

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
    printf "  %s%s%s\n\n" "$C_BOLD" "$(t existing_title)" "$C_RESET"
    printf "    %s1) %s%s\n" "$C_BOLD" "$(t existing_update)" "$C_RESET"
    printf "       %s%s%s\n" "$C_DIM" "$(t existing_update_note1)" "$C_RESET"
    printf "       %s%s%s\n" "$C_DIM" "$(t existing_update_note2)" "$C_RESET"
    printf "    %s2) %s%s\n" "$C_BOLD" "$(t existing_reinstall)" "$C_RESET"
    printf "       %s%s%s\n" "$C_DIM" "$(t existing_reinstall_note1)" "$C_RESET"
    printf "       %s%s%s\n" "$C_DIM" "$(t existing_reinstall_note2)" "$C_RESET"
    printf "    %s3) %s%s\n" "$C_BOLD" "$(t existing_clean)" "$C_RESET"
    printf "       %s%s%s\n" "$C_DIM" "$(t existing_clean_note)" "$C_RESET"
    printf "    %s4) %s%s\n" "$C_BOLD" "$(t existing_backup)" "$C_RESET"
    printf "       %s%s%s\n" "$C_DIM" "$(t existing_backup_note)" "$C_RESET"
    printf "\n  %s%s%s\n\n" "$C_DIM" "$(t existing_note)" "$C_RESET"

    if [ "$HEALTHY" != true ] && [ -n "$DIAGNOSIS" ]; then
        printf "  %s%s: %s → %s %d%s\n" \
            "$C_YELLOW" "$(t existing_diagnosis)" "$DIAGNOSIS" \
            "$(t existing_recommended)" "$RECOMMENDED" "$C_RESET"
    fi

    printf "  %s [%d]: " "$(t action_choice)" "$RECOMMENDED"
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

step "$(t step_deploy)"

# Снимок делается до перезаписи: после неё вернуть прежнюю версию уже нечем
make_snapshot

# Плюс полная копия — та же, что снимает --backup. Снимок годится для
# отката на этой машине, но переносимой копии из него не сделать: в нём
# нет манифеста и дампа в переносимом виде. Раз уж мы всё равно трогаем
# установку, копия должна остаться такая, которую можно увезти на другую
# машину — это ровно тот случай, когда она понадобится срочно.
if [ -d "$APP_DIR/radar" ]; then
    info "$(t backup_before)"
    if make_backup "перед установкой"; then
        ok "$(t backup_done) $(basename "$BACKUP_PATH")"
    else
        # Не прерываем установку: снимок уже снят, откат возможен.
        # Но сказать об этом надо — человек рассчитывает на копию.
        warn "Полную копию снять не удалось, откат из снимка остаётся доступен"
    fi
fi

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
# Скрипт восстановления кладётся рядом с установкой. Он нужен именно
# тогда, когда установщик может не работать, — значит должен лежать
# на машине заранее, а не скачиваться в момент аварии.
cat > "$APP_DIR/restore.sh" <<'RADAR_RESTORE_EOF'
#!/usr/bin/env bash
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
    # Владелец — пользователь контейнера: .env смонтирован внутрь,
    # и файл, оставшийся за root, бот перезаписать не сможет.
    chown 1000:1000 "$APP_DIR/.env" 2>/dev/null || true
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
RADAR_RESTORE_EOF
chmod +x "$APP_DIR/restore.sh" 2>/dev/null || true

# Скрипт получения сертификата — тоже рядом с установкой: он нужен
# на самой машине, где домен и порты, а не на машине разработчика.
cat > "$APP_DIR/tls.sh" <<'RADAR_TLS_EOF'
#!/usr/bin/env bash
#
# Получает сертификат и поднимает перед панелью Caddy, который сам держит
# его в актуальном состоянии.
#
# Почему Caddy, а не certbot с nginx: Caddy получает и продлевает
# сертификат сам, без cron и хуков. Для машины, за которой никто
# не следит ежедневно, это важнее гибкости — забытое продление ломает
# панель ровно через три месяца, когда о нём уже никто не помнит.
#
# ГЛАВНОЕ ОГРАНИЧЕНИЕ, о котором нужно знать заранее: проверка владения
# доменом идёт ИЗВНЕ на порты 80 и 443. Если роутер их не пробрасывает
# или провайдер режет — выдача не пройдёт, и никакие настройки здесь
# не помогут. Скрипт проверяет это до обращения к Let's Encrypt,
# чтобы не тратить попытки: у них лимит пять неудач в час на домен.
#
set -Eeuo pipefail

APP_DIR="${RADAR_HOME:-$HOME/radar_bot}"
DOMAIN="${1:-}"
EMAIL="${2:-}"

C_RESET=""; C_BOLD=""; C_DIM=""; C_GREEN=""; C_RED=""; C_YELLOW=""
if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_YELLOW=$'\033[1;33m'
fi
ok()   { printf "  %s✓%s %s\n" "$C_GREEN" "$C_RESET" "$*"; }
info() { printf "  %s→%s %s\n" "$C_DIM" "$C_RESET" "$*"; }
warn() { printf "  %s!%s %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
die()  { printf "\n  %s✗ %s%s\n\n" "$C_RED" "$*" "$C_RESET" >&2; exit 1; }

if [ -z "$DOMAIN" ]; then
    cat <<'USAGE'

  Сертификат для веб-панели «Радара»

  Использование:
    bash tls.sh домен [почта]

  Например:
    bash tls.sh radar.example.ru admin@example.ru

  Что нужно заранее:
    1. Домен указывает A-записью на внешний адрес этого сервера.
    2. Порты 80 и 443 проброшены на сервер снаружи.
       Проверка владения доменом идёт именно снаружи — без проброса
       сертификат не выдадут, сколько ни пробуй.

USAGE
    exit 0
fi

printf "\n  %sСертификат для %s%s\n\n" "$C_BOLD" "$DOMAIN" "$C_RESET"

command -v docker >/dev/null 2>&1 || die "Docker не установлен"
[ -d "$APP_DIR" ] || die "Установка не найдена в $APP_DIR"

# --- проверки до обращения к Let's Encrypt --------------------------------
#
# У них лимит: пять неудачных попыток на домен в час. Поэтому всё, что
# можно проверить самим, проверяем заранее.

info "Проверяю, куда указывает домен"
resolved="$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 || true)"
external="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"

if [ -z "$resolved" ]; then
    die "Домен $DOMAIN не разрешается в адрес — проверьте A-запись"
fi
ok "Домен указывает на $resolved"

if [ -n "$external" ] && [ "$resolved" != "$external" ]; then
    warn "Внешний адрес сервера — $external, а домен указывает на $resolved"
    warn "Если между ними нет проброса, проверка владения не пройдёт"
fi

info "Проверяю, свободен ли порт 80"
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':80 '; then
    die "Порт 80 занят. Освободите его: проверка Let's Encrypt идёт на него"
fi
ok "Порт 80 свободен"

WEB_PORT="$(grep -E '^WEB_PORT=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
: "${WEB_PORT:=8080}"

# --- Caddy ----------------------------------------------------------------

mkdir -p "$APP_DIR/tls"
cat > "$APP_DIR/tls/Caddyfile" <<CADDY
$DOMAIN {
    reverse_proxy radar:$WEB_PORT
    encode gzip
}
CADDY
ok "Настройки Caddy записаны"

cat > "$APP_DIR/tls/docker-compose.tls.yml" <<COMPOSE
services:
  caddy:
    image: caddy:2-alpine
    container_name: radar_tls
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./tls/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - default

volumes:
  caddy_data:
  caddy_config:
COMPOSE
ok "Описание контейнера готово"

info "Поднимаю Caddy — сертификат запросится автоматически"
cd "$APP_DIR"
if ! docker compose -f docker-compose.yml -f tls/docker-compose.tls.yml up -d caddy; then
    die "Caddy не запустился — смотрите docker logs radar_tls"
fi

printf "\n"
info "Жду выдачу сертификата (обычно до минуты)"
issued=false
for _ in $(seq 1 30); do
    if docker logs radar_tls 2>&1 | grep -q "certificate obtained successfully"; then
        issued=true
        break
    fi
    sleep 4
done

if [ "$issued" = true ]; then
    ok "Сертификат получен"
    printf "\n  Панель доступна: %shttps://%s%s\n" "$C_BOLD" "$DOMAIN" "$C_RESET"
    printf "  Короткие ссылки: %shttps://%s/s/КОД%s\n\n" "$C_BOLD" "$DOMAIN" "$C_RESET"
    printf "  Не забудьте задать в боте:\n"
    printf "    SHORT_BASE_URL = https://%s\n\n" "$DOMAIN"
else
    warn "Сертификат пока не выдан. Обычная причина — порты 80 и 443"
    warn "не проброшены снаружи. Посмотрите: docker logs radar_tls"
    printf "\n"
fi
RADAR_TLS_EOF
chmod +x "$APP_DIR/tls.sh" 2>/dev/null || true
chmod +x "$APP_DIR/collect-logs.sh"
ok "Сборщик журналов: $APP_DIR/collect-logs.sh"
ok "Восстановление из копии: $APP_DIR/restore.sh"
ok "Сертификат для панели: $APP_DIR/tls.sh домен"

# --------------------------------------------------------------------------
#  Шаг 6. Настройки
# --------------------------------------------------------------------------

step "$(t step_settings)"

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
    read -r -p "  $(t env_reuse_ask) " reply < /dev/tty || true
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

# С 4.8.4.2 .env смонтирован в контейнер, поэтому владельцем должен быть
# пользователь образа (uid 1000), а не root: иначе бот не прочитает ключи
# и не запишет новые из раздела настроек. Делается и при обновлении:
# на установках прежних версий .env остался за root.
env_fix_perms

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
    # Без `|| echo 0`: при pipefail неудачный ls делает весь конвейер
    # ненулевым, срабатывает запасная ветка — и к нулю от wc добавляется
    # второй ноль. На экране это выглядело как «доступно: 0 0)».
    snapshots="$(find "$APP_DIR/backups" -maxdepth 1 -name 'db-*.tar.gz' \
        2>/dev/null | wc -l)" || true
    snapshots="${snapshots//[!0-9]/}"
    : "${snapshots:=0}"

    if [ "$has_db" != true ] && [ "$snapshots" -eq 0 ]; then
        return 0
    fi

    echo
    printf "  %s%s%s\n\n" "$C_BOLD" "$(t dbmaint_title)" "$C_RESET"
    printf "    1) %s\n" "$(t dbmaint_nothing)"
    printf "    2) %s\n" "$(t dbmaint_backup)"
    printf "    3) %s\n" "$(t dbmaint_recreate)"
    printf "    4) %s%s %s)%s\n" \
        "$(t dbmaint_restore)" "$C_DIM" "$snapshots" "$C_RESET"
    printf "  %s [1]: " "$(t action_choice)"

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

step "$(t step_build)"

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

    # Заливка дампа при переезде. Делается до старта бота: иначе он создаст
    # пустую схему, и дамп ляжет поверх наполовину — часть таблиц из копии,
    # часть новых. Логика общая с откатом — см. load_pg_dump.
    if [ -n "$MIGRATION_DUMP" ] && [ -f "$MIGRATION_DUMP" ]; then
        if load_pg_dump "$MIGRATION_DUMP"; then
            MIGRATION_DUMP="$MIGRATION_DUMP.applied"
        else
            warn "Система поднимется с пустой базой; данные остались в копии"
        fi
    fi
else
    info "База данных: SQLite (файл data/radar.db, отдельный контейнер не нужен)"
    if [ -n "$MIGRATION_DUMP" ] && [ -f "$MIGRATION_DUMP" ]; then
        # Дамп pg_dump в SQLite не заливается: это разные диалекты SQL.
        # Молча продолжить нельзя — человек решит, что данные переехали.
        warn "В копии дамп PostgreSQL, а выбрана SQLite — залить нельзя"
        warn "Выберите PostgreSQL при установке либо переносите файл data/radar.db"
    fi
fi

# Профиль media поднимает собственный Bot API Server: он снимает предел
# отправки с 50 МБ до 2 ГБ, но требует ключей с my.telegram.org.
ask_bot_api_server

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

step "$(t step_diagnose)"

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

step "$(t step_start)"

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

# --- проверка целостности после переезда ----------------------------------
#
# Восстановление, которое не пересчитали, считается непроверенным. После
# переезда сверяем, что данные действительно доехали: пустая база при
# успешном старте выглядит точно так же, как полная, и человек узнает
# о потере, только когда кто-то пожалуется на пропавшие оповещения.
if [ "$RESTORED" = true ]; then
    step "$(t step_integrity)"
    if $COMPOSE $COMPOSE_ARGS run --rm --no-deps radar python - <<'RADAR_CHECK_EOF' 2>>"$LOG_FILE"
import asyncio


async def main() -> int:
    from radar.db import engine, repo

    await engine.ensure_schema()
    users = await repo.count_users()
    locations = await repo.count_locations()
    sources = await repo.count_sources()

    print(f"Пользователей: {users}")
    print(f"Локаций: {locations}")
    print(f"Источников: {sources}")

    if users == 0:
        print("ВНИМАНИЕ: пользователей ноль — данные не доехали")
        return 1
    return 0


raise SystemExit(asyncio.run(main()))
RADAR_CHECK_EOF
    then
        ok "$(t integrity_ok)"
    else
        warn "$(t integrity_failed)"
        warn "$(t integrity_hint)"
    fi
fi

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

# --------------------------------------------------------------------------
#  Публикация панели наружу (с 4.7.5.1)
# --------------------------------------------------------------------------
#
# Раньше сертификат получали отдельным скриптом, о котором надо было знать.
# Теперь установщик сам спрашивает — и сам доводит настройку до конца:
# получить сертификат мало, нужно ещё прописать адрес в сократитель ссылок
# и завести соль, иначе короткие ссылки останутся выключенными и человек
# не поймёт, почему.

tls_certificate_present() {
    # Сертификат живёт в томе Caddy. Проверяем и контейнер, и том:
    # контейнер могли остановить, а сертификат при этом цел.
    docker volume ls --format '{{.Name}}' 2>/dev/null \
        | grep -q 'caddy_data' && return 0
    docker ps -a --format '{{.Names}}' 2>/dev/null \
        | grep -q '^radar_tls$' && return 0
    return 1
}

configured_domain() {
    [ -f "$APP_DIR/tls/Caddyfile" ] || return 1
    head -1 "$APP_DIR/tls/Caddyfile" 2>/dev/null | awk '{print $1}'
}

setup_shortener() {   # setup_shortener <домен>
    local domain="$1"

    # Соль разводит коды разных экземпляров. Генерируем, если её нет,
    # и НИКОГДА не трогаем существующую: смена соли меняет все коды,
    # и уже разосланные ссылки перестают открываться.
    local salt
    salt="$(get_env_value SHORT_SALT)"
    if [ -z "$salt" ]; then
        salt="$(head -c 18 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 24)"
        set_env_value SHORT_SALT "$salt"
        ok "$(t tls_salt_created)"
    else
        info "$(t tls_salt_kept)"
    fi

    set_env_value SHORT_BASE_URL "https://$domain"
    ok "$(t tls_short_url): https://$domain"
}

offer_tls() {
    set +e
    ( : < /dev/tty ) 2>/dev/null || return 0

    local existing=""
    if tls_certificate_present; then
        existing="$(configured_domain || true)"
        if [ -n "$existing" ]; then
            ok "$(t tls_found): $existing"
            # Сертификат уже есть — остаётся убедиться, что короткие
            # ссылки о нём знают. Это отдельный шаг, и его легко забыть.
            local current
            current="$(get_env_value SHORT_BASE_URL)"
            if [ -z "$current" ]; then
                info "$(t tls_short_missing)"
                setup_shortener "$existing"
            elif [ "$current" != "https://$existing" ]; then
                # Раньше здесь стояла молчаливая перезапись, и адрес,
                # исправленный администратором, возвращался к домену
                # из Caddyfile при КАЖДОМ обновлении. Настройку,
                # сделанную руками, установщик не отменяет — только
                # показывает расхождение.
                warn "$(t tls_short_differs)"
                printf "      .env: %s\n" "$current"
                printf "      Caddyfile: https://%s\n" "$existing"
            fi
            return 0
        fi
        info "$(t tls_found_no_domain)"
    fi

    printf "\n  %s%s%s " "${C_DIM:-}" "$(t tls_ask)" "${C_RESET:-}"
    local answer=""
    if ! read -r answer < /dev/tty; then
        printf "\n"
        return 0
    fi
    printf "\n"
    case "$answer" in
        y|Y|д|Д|yes|да|YES|ДА) : ;;
        *) return 0 ;;
    esac

    printf "  %s " "$(t tls_domain_ask)"
    local domain=""
    read -r domain < /dev/tty || domain=""
    domain="$(printf '%s' "$domain" | tr -d ' \t\r')"
    printf "\n"

    if [ -z "$domain" ]; then
        warn "$(t tls_domain_empty)"
        return 0
    fi
    case "$domain" in
        *.*) : ;;
        *) warn "$(t tls_domain_bad) $domain"; return 0 ;;
    esac

    if [ ! -x "$APP_DIR/tls.sh" ]; then
        warn "$(t tls_script_missing)"
        return 0
    fi

    if RADAR_HOME="$APP_DIR" bash "$APP_DIR/tls.sh" "$domain"; then
        setup_shortener "$domain"

        # Домен для входа в панель привязывается у BotFather, а не здесь.
        # Без этого шага виджет Telegram пишет «Bot domain invalid»,
        # и по этой надписи догадаться, что делать, невозможно.
        line
        printf "  %s%s%s\n\n" "${C_BOLD:-}" "$(t tls_botfather_title)" "${C_RESET:-}"
        printf "    1. %s @BotFather\n" "$(t tls_botfather_open)"
        printf "    2. /setdomain\n"
        printf "    3. %s\n" "$(t tls_botfather_pick)"
        printf "    4. %s %shttps://%s%s\n\n" "$(t tls_botfather_send)" \
            "${C_CYAN:-}" "$domain" "${C_RESET:-}"
        printf "  %s\n" "$(t tls_botfather_note)"
        line

        info "$(t tls_restart_hint)"
    else
        warn "$(t tls_failed)"
    fi
    return 0
}

if [ "$MIGRATE_OUT" != true ]; then
    offer_tls
fi

# Предложение переехать. Спрашиваем в конце, а не в начале: до установки
# человек ещё не знает, работает ли новая версия, и решать про переезд рано.
#
# Всё тело — в функции с выключенным `set -e`. К этому месту ловушка ERR
# уже снята, и при включённом errexit любая осечка (недоступный внешний
# адрес, занятый порт) обрывала скрипт МОЛЧА: на экране оставался ответ
# «Y» и приглашение оболочки, без единого слова о причине. Молчание здесь
# хуже ошибки — человек считает, что переезд состоялся.
offer_migration() {
    set +e

    printf "  %s%s%s " "${C_DIM:-}" "$(t migrate_ask)" "${C_RESET:-}"
    local answer=""
    # Без таймаута: на экране вопрос уже напечатан, и оборвать его через
    # минуту — значит показать вопрос и не дать ответить. Ровно это
    # и происходило: строка появлялась, тут же возвращалось приглашение.
    # Если терминала нет, сюда мы не дойдём — проверка выше.
    if ! read -r answer < /dev/tty; then
        printf "\n"
        return 0
    fi
    printf "\n"

    case "$answer" in
        y|Y|д|Д|yes|да|YES|ДА) : ;;
        *) return 0 ;;
    esac

    # Способ передачи копии спрашивается и здесь: переезд предложен
    # в конце установки, но выбирать способ человек должен сам.
    local mode="link"
    if ( : < /dev/tty ) 2>/dev/null; then
        mode="$(ask_migration_mode)"
    fi

    local port="${MIGRATE_PORT:-8899}"
    local minutes="${MIGRATE_MINUTES:-30}"
    SERVE_TOKEN=""

    if [ -z "${BACKUP_PATH:-}" ] || [ ! -f "${BACKUP_PATH:-}" ]; then
        info "$(t migrate_making_copy)"
        if ! make_backup "переезд"; then
            warn "$(t migrate_backup_failed)"
            return 0
        fi
    fi

    if [ ! -f "${BACKUP_PATH:-}" ]; then
        warn "$(t migrate_backup_failed)"
        return 0
    fi
    ok "$(t migrate_copy_ready): $(basename "$BACKUP_PATH")"

    if [ "$mode" = "manual" ]; then
        print_manual_migration
        log_raw "MIGRATE ручной перенос, копия: $BACKUP_PATH"
        return 0
    fi

    kill_stale_serve

    # Порт может быть занят чужим процессом: молча промахнуться мимо
    # этого нельзя, ссылка тогда просто не откроется. Своя прошлая
    # раздача уже погашена выше.
    if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$port "; then
        warn "$(t migrate_port_busy) $port"
        print_manual_migration
        return 0
    fi

    local serve_file="$BACKUP_PATH" serve_bundle=false
    if build_migration_bundle "$BACKUP_PATH"; then
        serve_file="$MIGRATION_BUNDLE"
        serve_bundle=true
        ok "$(t migrate_bundle_ok)"
    fi

    if ! serve_migration "$serve_file" "$port" "$minutes"; then
        warn "$(t migrate_serve_failed)"
        print_manual_migration
        return 0
    fi

    local address link
    address="$(detect_address)"
    link="http://$address:$port/$SERVE_TOKEN"

    line
    printf "  %s%s%s\n\n" "${C_BOLD:-}" "$(t migrate_ready)" "${C_RESET:-}"
    # Про лимит ядра на длину аргумента и самодостаточный пакет —
    # см. комментарий у раздачи в --migrate: качаем в файл,
    # запускаем файлом.
    if [ "$serve_bundle" = true ]; then
        printf "  %s%s%s\n" "${C_CYAN:-}" \
            "curl -fsSLo radar-restore.sh $link" "${C_RESET:-}"
        printf "  %s%s%s\n\n" "${C_CYAN:-}" \
            "sudo bash radar-restore.sh" "${C_RESET:-}"
    else
        printf "  %s%s%s\n" "${C_CYAN:-}" \
            "curl -fsSLo radar-install.sh $INSTALLER_URL" "${C_RESET:-}"
        printf "  %s%s%s\n\n" "${C_CYAN:-}" \
            "sudo bash radar-install.sh --restore-url=$link" "${C_RESET:-}"
    fi
    line
    printf "  %s\n" "$(t migrate_note_once)"
    printf "  %s\n" "$(t migrate_note_time "$minutes")"
    printf "  %s\n" "$(t migrate_note_port "$port")"
    printf "  %s\n" "$(t migrate_note_nat "$port")"
    printf "  %s\n\n" "$(t migrate_note_secret)"
    printf "  %s\n" "$(t migrate_note_stop)"
    printf "    cd %s && docker compose down\n\n" "$APP_DIR"
    log_raw "MIGRATE ссылка выдана, порт $port, срок $minutes мин, пакет: $serve_bundle"
    wait_for_download "$SERVE_PID" "$minutes" || print_manual_migration
    cleanup_migration_files
    return 0
}

if ( : < /dev/tty ) 2>/dev/null && [ "$MIGRATE_OUT" != true ]; then
    offer_migration
fi

if [ "$SHOW_LOGS" = true ]; then
    docker logs -f "$CONTAINER_NAME"
fi

}   # конец radar_installer_main

# Единственная исполняемая пара строк файла. Если скачивание оборвалось,
# до неё дело не дойдёт — bash упадёт на разборе незакрытой функции.
# exit обязателен: у пакета переезда позади этих строк лежит бинарная
# копия, и без явного выхода bash взялся бы разбирать её как команды.
radar_installer_main "$@"
exit $?
