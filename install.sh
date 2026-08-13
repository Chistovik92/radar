#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

#
# Система «Радар» v4.0.4 — автономный установщик.
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

VERSION="4.0.4"
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

mkdir -p "migrations" "migrations/versions" "radar" "radar/db" "radar/handlers" "radar/platforms"
FILE_COUNT=44
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "requirements.txt"
cat > "requirements.txt" <<'RADAR_FILE_00'
aiogram>=3.13,<4
aiohttp>=3.9,<4
beautifulsoup4>=4.12
google-genai>=1.0
aiofiles>=23.2
python-dotenv>=1.0

# База данных
SQLAlchemy[asyncio]>=2.0,<3
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
COPY radar ./radar
COPY migrations ./migrations

RUN useradd -m -u 1000 radar && mkdir -p /app/data && chown -R radar:radar /app
USER radar

CMD ["python", "-u", "main.py"]
RADAR_FILE_01
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "docker-compose.yml"
cat > "docker-compose.yml" <<'RADAR_FILE_02'
services:
  postgres:
    image: postgres:16-alpine
    container_name: radar_db
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DB_NAME:-radar}
      POSTGRES_USER: ${DB_USER:-radar}
      POSTGRES_PASSWORD: ${DB_PASSWORD:?DB_PASSWORD обязателен}
      # Слабое железо: русская локаль и лишние воркеры не нужны
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"
    command: >
      postgres
      -c shared_buffers=64MB
      -c effective_cache_size=192MB
      -c work_mem=4MB
      -c maintenance_work_mem=32MB
      -c max_connections=25
      -c max_parallel_workers=0
      -c max_parallel_workers_per_gather=0
      -c wal_compression=on
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
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

  radar:
    build:
      context: .
      args:
        TZ: ${TZ:-Europe/Saratov}
    image: radar_image
    container_name: radar_container
    # on-failure с лимитом вместо unless-stopped: при неверной конфигурации
    # бесконечный цикл рестартов маскирует причину и греет слабое железо.
    restart: on-failure:5
    env_file: .env
    environment:
      DB_HOST: postgres
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./data:/app/data
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

from radar import ai, features, handlers, monitor, roles, storage  # noqa: E402
from radar.db import engine as db_engine  # noqa: E402
from radar.db import importer, repo  # noqa: E402
from radar.middlewares import AccessMiddleware  # noqa: E402
from radar.tg import bot, dp, send_html  # noqa: E402

CHANGELOG = (
    f"🚀 <b>Система «Радар» v{config.VERSION}</b>\n\n"
    "🗄 <b>PostgreSQL вместо файла.</b> Данные перенесены автоматически.\n"
    "🕘 <b>История событий</b> — теперь видно, что приходило по каждому адресу.\n"
    "⚙️ <b>Управление возможностями</b> прямо в боте: /features у суперадминистратора. "
    "Функции включаются и выключаются без обновления версии.\n"
    "🔌 <b>Готовность к мессенджеру MAX</b> — единое ядро для двух платформ.\n"
    "🐙 Проект HydraVPN переименован в <b>HydraSite</b>, команда /partner.\n\n"
    "<i>Из прошлых версий:</i>\n"
    "✅ <b>Отбой опасности</b> приходит отдельным сообщением с другим сигналом, "
    "а не как новая тревога.\n"
    "📍 <b>Администрация может добавлять локации</b> пользователям — по адресу "
    "текстом или геопозицией.\n"
    "🔗 <b>Новости из лент СМИ</b> снабжаются ссылкой на источник.\n"
    "🌍 <b>Новые города</b>: Москва, Санкт-Петербург, Казань, Самара.\n"
    "☰ <b>Кнопки «Меню» и «HydraSite»</b> закреплены под полем ввода.\n\n"
    "<i>Из прошлых версий:</i>\n"
    "<b>Полностью переработанная версия:</b>\n"
    "🛸 <b>Военные угрозы</b> (БПЛА, ракетная опасность) определяются на весь город "
    "и приходят одним сообщением со списком совпавших локаций.\n"
    "🛠 <b>ЖКХ</b> (вода, свет, газ, отопление, аварии) ищется адресно — по улице и дому, "
    "отдельным сообщением.\n"
    "📍 <b>Локаций сколько угодно</b>; находящиеся ближе 1 км объединяются в одну сводку.\n"
    "🌤 <b>Погода</b> — по каждой группе локаций отдельно.\n"
    "🌐 <b>Источники</b>: каналы служб ЖКХ, МЧС, администраций города, района, области "
    "плюс RSS-ленты СМИ.\n"
    "🧠 <b>ИИ-ассистент</b> в диалоге — начиная с роли «Модератор».\n"
    "👥 <b>Роли</b>: суперадминистратор назначает администраторов, администратор — "
    "модераторов; правка локаций и оповещений — с модератора, удаление — с администратора.\n"
    "📉 <b>Экономия квоты Gemini</b>: предфильтр, пакетный разбор и резерв запросов "
    "под ассистента. Расход — командой /quota.\n"
    "🔄 <b>Модель выбирается автоматически</b> из доступных ключу: при отключении "
    "одной версии бот сам переходит на следующую. Список — командой /models.\n"
    "📦 <b>Источники выгружаются и загружаются файлом</b> — кнопки в панели модератора.\n"
    "🌤 <b>Погода переработана</b>: почасовая таблица, прогноз на три дня, восход и закат.\n"
    "📵 <b>Белые списки</b> больше не ищутся в новостях — предупреждение выдаётся "
    "автоматически вместе с оповещением о БПЛА или ракетной опасности."
)

async def announce() -> None:
    """Рассылает changelog один раз на версию, а не при каждом рестарте."""
    marker = await storage.meta_get("announced_version") or {}
    if marker.get("value") == config.VERSION:
        return
    await storage.meta_set("announced_version", {"value": config.VERSION})
    for uid, user in list(storage.users().items()):
        if roles.is_moderator(user.get("role")):
            await send_html(uid, CHANGELOG)
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


def upgrade_schema() -> None:
    """Накатывает миграции Alembic. Выполняется синхронно до старта бота."""
    from alembic import command
    from alembic.config import Config

    root = os.path.dirname(os.path.abspath(__file__))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    command.upgrade(cfg, "head")


async def prepare_database() -> None:
    """Готовит базу: ждёт готовности, накатывает схему, переносит старые данные."""
    await db_engine.wait_ready()
    log.info("Применяю миграции схемы (на слабом железе это до нескольких минут)")
    await asyncio.to_thread(upgrade_schema)
    log.info("Схема базы актуальна")
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

__version__ = "4.0.4"
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

# --- PostgreSQL ---
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


def database_url(async_driver: bool = True) -> str:
    """Строка подключения. DATABASE_URL имеет приоритет над отдельными полями."""
    from urllib.parse import quote_plus

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
USER_AGENT: str = (
    os.getenv("USER_AGENT") or f"RadarBot/{VERSION} (+https://github.com/Chistovik92/radar)"
).strip()

# Города, чьи наборы источников подключаются при первом запуске.
# Доступны: saratov, moscow, spb, kazan, samara (см. radar/presets.py).
SOURCE_CITIES: list[str] = _list("SOURCE_CITIES")

AI_ENABLED: bool = bool(GEMINI_API_KEY)


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)-16s | %(message)s",
    )
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
    if not DATABASE_URL and not DB_PASSWORD:
        problems.append("DB_PASSWORD не задан (или задайте DATABASE_URL целиком)")
    elif "$" in DB_PASSWORD:
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
    Flag("web_terminal", "Терминал в панели",
         "Консоль сервера в веб-панели. Повышенный риск: включайте осознанно.",
         group="Администрирование", since="4.4", default=False),
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
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/presets.py"
cat > "radar/presets.py" <<'RADAR_FILE_14'
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
RADAR_FILE_14
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/__init__.py"
cat > "radar/db/__init__.py" <<'RADAR_FILE_15'
"""Слой базы данных: модели, подключение, репозиторий."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from .engine import dispose, get_engine, session, session_factory, wait_ready
from .models import Base, Delivery, Event, Feature, Location, Meta, Source, User

# Внимание: здесь нельзя экспортировать имена `engine`, `models`, `repo`,
# `importer` — они совпадают с именами подмодулей пакета и затенили бы их
# при `from radar.db import engine`.
__all__ = [
    "Base", "Delivery", "Event", "Feature", "Location", "Meta", "Source", "User",
    "dispose", "get_engine", "session", "session_factory", "wait_ready",
]
RADAR_FILE_15
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/models.py"
cat > "radar/db/models.py" <<'RADAR_FILE_16'
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Базовый класс моделей."""

    type_annotation_map = {dict[str, Any]: JSONB, list[str]: JSONB}


class User(Base):
    """Пользователь любой платформы.

    Ключ суррогатный, а не Telegram ID: с версии 4.2 бот работает сразу
    в двух мессенджерах, и один и тот же числовой идентификатор может
    принадлежать разным людям в Telegram и MAX. Пара (platform, external_id)
    уникальна и служит естественным ключом.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), default="telegram", index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    weather_mode: Mapped[str] = mapped_column(String(16), default="interval")
    weather_interval: Mapped[int] = mapped_column(Integer, default=0)
    weather_time: Mapped[str] = mapped_column(String(8), default="08:00")
    weather_format: Mapped[str] = mapped_column(String(8), default="text")  # text | image
    last_weather: Mapped[int] = mapped_column(BigInteger, default=0)
    last_fixed_date: Mapped[str] = mapped_column(String(16), default="")

    # Задел под 4.1: тихие часы и антиспам.
    quiet_from: Mapped[str] = mapped_column(String(8), default="")
    quiet_to: Mapped[str] = mapped_column(String(8), default="")

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
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
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
    added_by: Mapped[int] = mapped_column(BigInteger, default=0)  # кто добавил, 0 — сам

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

    added_by: Mapped[int] = mapped_column(BigInteger, default=0)
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

    categories: Mapped[list[str]] = mapped_column(JSONB, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    scope: Mapped[str] = mapped_column(String(16), default="city")
    all_clear: Mapped[bool] = mapped_column(Boolean, default=False)

    city: Mapped[str] = mapped_column(String(120), default="", index=True)
    region: Mapped[str] = mapped_column(String(120), default="")
    districts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    streets: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)

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
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
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
    changed_by: Mapped[int] = mapped_column(BigInteger, default=0)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Meta(Base):
    """Служебные пары ключ-значение: версия анонса, флаги миграций."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
RADAR_FILE_16
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/engine.py"
cat > "radar/db/engine.py" <<'RADAR_FILE_17'
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

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .. import config

log = logging.getLogger("radar.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            config.database_url(),
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


async def dispose() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
RADAR_FILE_17
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/repo.py"
cat > "radar/db/repo.py" <<'RADAR_FILE_18'
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
from sqlalchemy.dialects.postgresql import insert

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
        row.seen_at = datetime.now(timezone.utc)

        await active.flush()
        user_id = row.id

        existing = {item.public_id: item for item in row.locations}
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
    async with session() as active:
        statement = (
            insert(Source)
            .values(kind=kind, ref=ref, pending=pending, added_by=added_by, city=city)
            .on_conflict_do_update(
                index_elements=[Source.kind, Source.ref],
                set_={"pending": pending, "enabled": True},
            )
        )
        await active.execute(statement)


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
        statement = (
            insert(Delivery)
            .values(
                event_id=event_id,
                user_id=row.id,
                location_id=location_id,
                sent_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(
                index_elements=[Delivery.event_id, Delivery.user_id, Delivery.location_id]
            )
            .returning(Delivery.id)
        )
        return (await active.scalar(statement)) is not None


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
        statement = (
            insert(Meta)
            .values(key=key, value=value)
            .on_conflict_do_update(index_elements=[Meta.key], set_={"value": value})
        )
        await active.execute(statement)


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
        statement = (
            insert(Feature)
            .values(key=key, enabled=enabled_value, changed_by=actor)
            .on_conflict_do_update(
                index_elements=[Feature.key],
                set_={"enabled": enabled_value, "changed_by": actor},
            )
        )
        await active.execute(statement)
RADAR_FILE_18
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/db/importer.py"
cat > "radar/db/importer.py" <<'RADAR_FILE_19'
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
    for uid, item in (raw.get("users") or {}).items():
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
        for entry in item.get("locs") or []:
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

    channels = [str(item) for item in (raw.get("channels") or []) if item]
    feeds = [str(item) for item in (raw.get("rss") or []) if item]
    vk = [str(item) for item in (raw.get("vk") or []) if item]
    pending = [str(item) for item in (raw.get("pending") or []) if item]

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
        "meta": raw.get("meta") or {},
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
RADAR_FILE_19
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "migrations/env.py"
cat > "migrations/env.py" <<'RADAR_FILE_20'
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
RADAR_FILE_20
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "migrations/script.py.mako"
cat > "migrations/script.py.mako" <<'RADAR_FILE_21'
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
RADAR_FILE_21
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "migrations/versions/0001_initial.py"
cat > "migrations/versions/0001_initial.py" <<'RADAR_FILE_22'
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
RADAR_FILE_22
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/platforms/__init__.py"
cat > "radar/platforms/__init__.py" <<'RADAR_FILE_23'
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
RADAR_FILE_23
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/platforms/base.py"
cat > "radar/platforms/base.py" <<'RADAR_FILE_24'
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
RADAR_FILE_24
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/storage.py"
cat > "radar/storage.py" <<'RADAR_FILE_25'
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
RADAR_FILE_25
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/exporting.py"
cat > "radar/exporting.py" <<'RADAR_FILE_26'
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
RADAR_FILE_26
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/ai.py"
cat > "radar/ai.py" <<'RADAR_FILE_27'
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
RADAR_FILE_27
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/geocode.py"
cat > "radar/geocode.py" <<'RADAR_FILE_28'
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
RADAR_FILE_28
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/weather.py"
cat > "radar/weather.py" <<'RADAR_FILE_29'
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
RADAR_FILE_29
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/sources.py"
cat > "radar/sources.py" <<'RADAR_FILE_30'
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
RADAR_FILE_30
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/tg.py"
cat > "radar/tg.py" <<'RADAR_FILE_31'
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
RADAR_FILE_31
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/keyboards.py"
cat > "radar/keyboards.py" <<'RADAR_FILE_32'
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

from . import config, roles
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
    if roles.can_use_assistant(role):
        rows.append([InlineKeyboardButton(text="🧠 ИИ-ассистент", callback_data="menu:ai")])
    if roles.is_moderator(role):
        rows.append([InlineKeyboardButton(text="🛡 Модерация", callback_data="menu:mod")])
    if roles.is_admin(role):
        rows.append([InlineKeyboardButton(text="👥 Пользователи", callback_data="menu:admin")])
    if roles.is_superadmin(role):
        rows.append([InlineKeyboardButton(text="⚙️ Возможности", callback_data="feat:list")])
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


def weather_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отключить", callback_data="set:wth:0"),
                InlineKeyboardButton(text="Каждый час", callback_data="set:wth:60"),
            ],
            [
                InlineKeyboardButton(text="Каждые 3 часа", callback_data="set:wth:180"),
                InlineKeyboardButton(text="Каждые 6 часов", callback_data="set:wth:360"),
            ],
            [
                InlineKeyboardButton(text="⏰ Точное время", callback_data="set:wthtime"),
                InlineKeyboardButton(text="⏱ Свой интервал", callback_data="set:wthint"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:settings")],
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
RADAR_FILE_32
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/states.py"
cat > "radar/states.py" <<'RADAR_FILE_33'
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
RADAR_FILE_33
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/middlewares.py"
cat > "radar/middlewares.py" <<'RADAR_FILE_34'
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
RADAR_FILE_34
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/monitor.py"
cat > "radar/monitor.py" <<'RADAR_FILE_35'
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

from . import ai, config, geocode, sources, storage, weather
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
                await cycle(session)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Сбой цикла мониторинга")
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(15.0, config.POLL_INTERVAL - elapsed))
RADAR_FILE_35
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/__init__.py"
cat > "radar/handlers/__init__.py" <<'RADAR_FILE_36'
"""Роутеры обработчиков. Порядок подключения важен: ассистент — последним."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import Dispatcher

from . import assistant, common, features, locations, settings, sources, users

def setup(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(locations.router)
    dp.include_router(settings.router)
    dp.include_router(sources.router)
    dp.include_router(users.router)
    dp.include_router(features.router)
    # Ассистент перехватывает любой оставшийся текст — только в самом конце.
    dp.include_router(assistant.router)


__all__ = ["setup"]
RADAR_FILE_36
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/common.py"
cat > "radar/handlers/common.py" <<'RADAR_FILE_37'
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
RADAR_FILE_37
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/locations.py"
cat > "radar/handlers/locations.py" <<'RADAR_FILE_38'
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
RADAR_FILE_38
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/settings.py"
cat > "radar/handlers/settings.py" <<'RADAR_FILE_39'
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
from ..tg import back_kb, safe_edit

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


@router.callback_query(F.data == "set:weather")
async def weather_menu(call: CallbackQuery) -> None:
    await call.answer()
    await safe_edit(
        call,
        "⏱ <b>Режим погоды</b>\nВыберите интервал или задайте своё значение.",
        keyboards.weather_menu(),
    )


@router.callback_query(F.data.startswith("set:wth:"))
async def set_interval(call: CallbackQuery, user: dict[str, Any]) -> None:
    try:
        minutes = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer()
        return
    user["weather_mode"] = "interval"
    user["weather_interval"] = minutes
    user["last_weather"] = 0
    await storage.save()
    await call.answer("Погода отключена" if minutes == 0 else f"Интервал: {minutes} мин")
    await safe_edit(call, "⚙️ <b>Оповещения</b>", keyboards.settings_menu(user))


@router.callback_query(F.data == "set:wthtime")
async def ask_time(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await safe_edit(
        call,
        "⏰ Введите время в формате <code>HH:MM</code> (например, 08:30):",
        back_kb("set:weather", "Отмена"),
    )
    await state.set_state(Form.weather_time)


@router.message(Form.weather_time)
async def save_time(message: Message, state: FSMContext, user: dict[str, Any]) -> None:
    value = (message.text or "").strip()
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
        await message.answer("❌ Неверный формат. Пример: <code>08:30</code>. /cancel — отмена.")
        return
    hour, minute = value.split(":")
    value = f"{int(hour):02d}:{minute}"
    user["weather_mode"] = "time"
    user["weather_time"] = value
    user["last_fixed_date"] = ""
    await storage.save()
    await state.clear()
    await message.answer(
        f"✅ Погода будет приходить ежедневно в <b>{value}</b>.",
        reply_markup=keyboards.settings_menu(user),
    )


@router.callback_query(F.data == "set:wthint")
async def ask_interval(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await safe_edit(
        call,
        "⏱ Введите интервал: <code>45</code> (минут) или <code>2ч</code> (часа):",
        back_kb("set:weather", "Отмена"),
    )
    await state.set_state(Form.weather_interval)


@router.message(Form.weather_interval)
async def save_interval(message: Message, state: FSMContext, user: dict[str, Any]) -> None:
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
    user["weather_mode"] = "interval"
    user["weather_interval"] = minutes
    user["last_weather"] = 0
    await storage.save()
    await state.clear()
    await message.answer(
        f"✅ Интервал: <b>{minutes} мин</b>.", reply_markup=keyboards.settings_menu(user)
    )
RADAR_FILE_39
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/sources.py"
cat > "radar/handlers/sources.py" <<'RADAR_FILE_40'
"""Источники: предложение пользователем, очередь модерации, ручное добавление."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import config, exporting, keyboards, roles, storage
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, safe_edit

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
RADAR_FILE_40
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/users.py"
cat > "radar/handlers/users.py" <<'RADAR_FILE_41'
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
RADAR_FILE_41
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/features.py"
cat > "radar/handlers/features.py" <<'RADAR_FILE_42'
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
RADAR_FILE_42
printf "  %s·%s %s\n" "$C_DIM" "$C_RESET" "radar/handlers/assistant.py"
cat > "radar/handlers/assistant.py" <<'RADAR_FILE_43'
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
RADAR_FILE_43
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

    # Каждые две минуты напоминаем, что процесс идёт
    if [ $((tick % 60)) -eq 0 ]; then
        info "· всё ещё работаю, прошло $((tick * 2 / 60)) мин"
    fi
    sleep 2
done

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
printf "    Копия базы    docker exec radar_db pg_dump -U radar radar | gzip > radar-\$(date +%%F).sql.gz\n"
echo
printf "  %sЖурнал установки: %s%s\n" "$C_DIM" "$LOG_FILE" "$C_RESET"
echo
log_raw "=== УСТАНОВКА ЗАВЕРШЕНА УСПЕШНО за ${ELAPSED} с ==="

if [ "$SHOW_LOGS" = true ]; then
    docker logs -f "$CONTAINER_NAME"
fi
