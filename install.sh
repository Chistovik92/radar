#!/usr/bin/env bash
#
# Система «Радар» v3.1.0 — автономный установщик.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh)
#
# Флаги:
#   --recreate-env   заново запросить токены и настройки
#   --no-cache       пересобрать образ без кэша Docker
#   --logs           показать логи после запуска
#   --uninstall      остановить и удалить контейнер и образ (данные сохраняются)
#
# Файл собирается автоматически: python3 tools/build_installer.py
# Правьте исходники проекта, а не install.sh.

set -Eeuo pipefail

VERSION="3.1.0"
APP_DIR="${RADAR_HOME:-$HOME/radar_bot}"
IMAGE_NAME="${RADAR_IMAGE:-radar_image}"
CONTAINER_NAME="${RADAR_CONTAINER:-radar_container}"
RECREATE_ENV=false
NO_CACHE=""
SHOW_LOGS=false
UNINSTALL=false

for arg in "$@"; do
    case "$arg" in
        --recreate-env) RECREATE_ENV=true ;;
        --no-cache)     NO_CACHE="--no-cache" ;;
        --logs)         SHOW_LOGS=true ;;
        --uninstall)    UNINSTALL=true ;;
        -v|--version)   echo "radar $VERSION"; exit 0 ;;
        -h|--help)      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Неизвестный флаг: $arg" >&2; exit 1 ;;
    esac
done

info() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ERR]\033[0m %s\n' "$*" >&2; exit 1; }
trap 'die "Установка прервана (строка $LINENO)"' ERR

echo "==========================================================="
echo "        СИСТЕМА «РАДАР» v${VERSION} — установка"
echo "==========================================================="

command -v docker >/dev/null 2>&1 || die "Docker не установлен: https://docs.docker.com/engine/install/"
docker info >/dev/null 2>&1 || die "Docker-демон недоступен. Запустите его или добавьте пользователя в группу docker."

if [ "$UNINSTALL" = true ]; then
    info "Удаляю контейнер и образ (данные в $APP_DIR/data сохраняются)"
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rmi "$IMAGE_NAME" >/dev/null 2>&1 || true
    ok "Готово."
    exit 0
fi

[ -e /dev/tty ] || die "Нет интерактивного терминала для ввода настроек."

# --- 1. Каталог -----------------------------------------------------------
info "Каталог установки: $APP_DIR"
mkdir -p "$APP_DIR/data"
cd "$APP_DIR"
chmod 700 "$APP_DIR" 2>/dev/null || true
chown -R 1000:1000 "$APP_DIR/data" 2>/dev/null || chmod -R a+rwX "$APP_DIR/data"

if [ -f "$APP_DIR/bot.py" ] && [ ! -d "$APP_DIR/radar" ]; then
    warn "Обнаружена установка версии 2.x — переношу bot.py в bot.py.bak-2x"
    mv -f "$APP_DIR/bot.py" "$APP_DIR/bot.py.bak-2x"
fi

# --- 2. Файлы проекта -----------------------------------------------------
info "Разворачиваю файлы проекта"
mkdir -p "radar" "radar/handlers"
printf "  %s\n" "requirements.txt"
cat > "requirements.txt" <<'RADAR_FILE_00'
aiogram>=3.13,<4
aiohttp>=3.9,<4
beautifulsoup4>=4.12
google-genai>=1.0
aiofiles>=23.2
python-dotenv>=1.0
RADAR_FILE_00
printf "  %s\n" "Dockerfile"
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

COPY main.py ./
COPY radar ./radar

RUN useradd -m -u 1000 radar && mkdir -p /app/data && chown -R radar:radar /app
USER radar

CMD ["python", "-u", "main.py"]
RADAR_FILE_01
printf "  %s\n" ".dockerignore"
cat > ".dockerignore" <<'RADAR_FILE_02'
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
RADAR_FILE_02
printf "  %s\n" "main.py"
cat > "main.py" <<'RADAR_FILE_03'
#!/usr/bin/env python3
"""Точка входа системы «Радар»."""

from __future__ import annotations

import asyncio
import os

from radar import config

# Логи и проверка конфигурации выполняются до импорта aiogram-слоя:
# без валидного BOT_TOKEN экземпляр Bot создать нельзя.
log = config.setup_logging()
config.validate()

from radar import handlers, monitor, roles, storage  # noqa: E402
from radar.middlewares import AccessMiddleware  # noqa: E402
from radar.tg import bot, dp, send_html  # noqa: E402

CHANGELOG = (
    f"🚀 <b>Система «Радар» v{config.VERSION}</b>\n\n"
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
    "под ассистента. Расход — командой /quota."
)


async def announce() -> None:
    """Рассылает changelog один раз на версию, а не при каждом рестарте."""
    meta = storage.meta()
    if meta.get("announced_version") == config.VERSION:
        return
    meta["announced_version"] = config.VERSION
    await storage.save()
    for uid, user in list(storage.users().items()):
        if roles.is_moderator(user.get("role")):
            await send_html(uid, CHANGELOG)
            await asyncio.sleep(0.2)


async def main() -> None:
    await storage.load()

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
        log.info("Остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
RADAR_FILE_03
printf "  %s\n" "radar/__init__.py"
cat > "radar/__init__.py" <<'RADAR_FILE_04'
"""Система «Радар» — мониторинг городских угроз и ЖКХ-аварий по локациям пользователя."""

__version__ = "3.1.0"
__all__ = ["__version__"]
RADAR_FILE_04
printf "  %s\n" "radar/config.py"
cat > "radar/config.py" <<'RADAR_FILE_05'
"""Конфигурация приложения: читается из переменных окружения (.env)."""

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
GEMINI_MODEL: str = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
# Разбор новостей — задача классификации: дешёвая модель с большей квотой.
GEMINI_MODEL_ANALYSIS: str = (
    os.getenv("GEMINI_MODEL_ANALYSIS") or "gemini-2.5-flash-lite"
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
POLL_INTERVAL: int = max(60, _int("POLL_INTERVAL", 180))
MSG_PER_SOURCE: int = max(1, _int("MSG_PER_SOURCE", 5))
CLUSTER_RADIUS_M: int = max(0, _int("CLUSTER_RADIUS_M", 1000))
MAX_LOCATIONS: int = _int("MAX_LOCATIONS", 0)  # 0 — без ограничения
DEFAULT_CITY: str = (os.getenv("DEFAULT_CITY") or "").strip()
EXTRA_CHANNELS: list[str] = _list("EXTRA_CHANNELS")
EXTRA_RSS: list[str] = [u for u in (os.getenv("EXTRA_RSS") or "").split(",") if u.strip()]

LOG_LEVEL: str = (os.getenv("LOG_LEVEL") or "INFO").upper()
USER_AGENT: str = (
    os.getenv("USER_AGENT") or f"RadarBot/{VERSION} (+https://github.com/Chistovik92/radar)"
).strip()

# Каналы по умолчанию: службы ЖКХ, МЧС, администрации, городские СМИ.
DEFAULT_CHANNELS: list[str] = [
    "saratov_24",
    "mchs_saratov",
    "saratovmeriya",
    "saratovzhkh",
    "saratovvodokanal",
    "tplus_saratov",
]

DEFAULT_RSS: list[str] = []

AI_ENABLED: bool = bool(GEMINI_API_KEY)


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)-16s | %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    return logging.getLogger("radar")


def validate() -> None:
    """Проверяет обязательные параметры и завершает процесс при их отсутствии."""
    log = logging.getLogger("radar.config")
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN не задан")
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
RADAR_FILE_05
printf "  %s\n" "radar/textutils.py"
cat > "radar/textutils.py" <<'RADAR_FILE_06'
"""Чистые утилиты: разметка, нормализация адресов, геометрия, кластеризация.

Модуль намеренно не импортирует внешние пакеты — его можно тестировать
без установленного aiogram/aiohttp/google-genai.
"""

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
RADAR_FILE_06
printf "  %s\n" "radar/roles.py"
cat > "radar/roles.py" <<'RADAR_FILE_07'
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
RADAR_FILE_07
printf "  %s\n" "radar/ratelimit.py"
cat > "radar/ratelimit.py" <<'RADAR_FILE_08'
"""Учёт квот Gemini: запросы в минуту, запросы в сутки, резерв под ассистента.

Бесплатный тариф Gemini ограничен по RPM и RPD (для 2.5-flash — порядка
10 запросов в минуту), поэтому фоновый анализ новостей обязан уступать
дорогу живому диалогу с ассистентом. Дневной счётчик сбрасывается в полночь
по тихоокеанскому времени — так, как это делает Google.
"""

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
RADAR_FILE_08
printf "  %s\n" "radar/matching.py"
cat > "radar/matching.py" <<'RADAR_FILE_09'
"""Модель разобранной новости, правила сопоставления с локациями и сборка сообщений.

Только стандартная библиотека — модуль полностью покрывается тестами офлайн.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .textutils import (
    cluster_locations,
    district_matches,
    esc,
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
    "whitelist": "Связь и «белые списки»",
}

CATEGORY_ICONS = {"bpla": "🛸", "mchs": "🆘", "jkh": "🛠", "whitelist": "📶"}

# Военные угрозы объявляются на весь город, независимо от указанных улиц.
CITY_WIDE_ALWAYS = {"bpla"}
# Связь и «белые списки» обычно вводятся на город/регион целиком.
CITY_WIDE_DEFAULT = {"whitelist"}

SEVERITY_ICONS = {"critical": "🔴", "warning": "🟠", "info": "🔵"}


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
    engine: str = "ai"  # ai | heuristic

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, source: str, raw: str) -> "Analysis":
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


def heuristic_analysis(text: str, *, source: str = "", default_city: str = "") -> Analysis:
    """Резервный разбор без ИИ: ключевые слова + извлечение улиц и домов."""
    categories = [key for key, pattern in _HEURISTICS if pattern.search(text)]
    if not categories:
        return Analysis(relevant=False, source=source, raw=text, engine="heuristic")

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

    severity = "critical" if {"bpla", "mchs"} & set(categories) else "warning"
    summary = re.sub(r"\s+", " ", text).strip()
    return Analysis(
        relevant=True,
        categories=categories,
        severity=severity,
        scope=scope,
        city=city,
        districts=districts,
        streets=streets[:8],
        summary=summary[:400],
        source=source,
        raw=text,
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


def _event_line(analysis: Analysis) -> str:
    icon = SEVERITY_ICONS.get(analysis.severity, "🔵")
    label = analysis.source or "источник"
    source = esc(label) if ("." in label or "/" in label) else f"@{esc(label)}"
    mark = "" if analysis.engine == "ai" else " <i>(без ИИ)</i>"
    return f"{icon} <b>{source}</b>{mark}\n{esc(analysis.text())}"


def build_city_alert(city: str, locations: Sequence[dict[str, Any]], events: Sequence[Analysis]) -> str:
    """Одно сообщение на город: военные и другие общегородские угрозы."""
    titles = {analysis.title() for analysis in events}
    head = f"🚨 <b>ОПАСНОСТЬ — {esc(city or 'город')}</b>"
    lines = [head, f"<b>{esc(' / '.join(sorted(titles)))}</b>", format_locations_header(locations, "весь город")]
    lines.append("")
    lines.extend(_event_line(analysis) for analysis in events)
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


def build_weather_message(blocks: Sequence[tuple[Sequence[dict[str, Any]], str]]) -> str:
    """Погода: по одному блоку на группу локаций."""
    parts = ["🌤 <b>Погода по вашим локациям</b>"]
    for locations, weather in blocks:
        note = "в пределах 1 км" if len(locations) > 1 else ""
        parts.append("")
        parts.append(format_locations_header(locations, note))
        parts.append(weather)
    return "\n".join(parts)


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
            bucket = city_buckets.setdefault(key, {"city": label, "locs": {}, "events": []})
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
        messages.append(
            ("city", build_city_alert(bucket["city"], list(bucket["locs"].values()), bucket["events"]))
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
RADAR_FILE_09
printf "  %s\n" "radar/storage.py"
cat > "radar/storage.py" <<'RADAR_FILE_10'
"""JSON-хранилище с атомарной записью, блокировкой и миграцией с версий 2.x."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

import aiofiles

from . import config
from .matching import CATEGORY_TITLES
from .roles import SUPERADMIN, USER

log = logging.getLogger("radar.storage")

DB: dict[str, Any] = {}
_lock = asyncio.Lock()


# --------------------------------------------------------------------------
#  Значения по умолчанию
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
        "last_weather": 0,
        "last_fixed_date": "",
        "created": int(time.time()),
    }


def new_location(name: str, lat: float, lon: float, **extra: Any) -> dict[str, Any]:
    loc = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "city": "",
        "district": "",
        "region": "",
        "street": "",
        "house": "",
    }
    loc.update({k: v for k, v in extra.items() if v is not None})
    return loc


# --------------------------------------------------------------------------
#  Миграция
# --------------------------------------------------------------------------

def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Приводит базу любой версии 2.x к структуре 3.x без потери данных."""
    data.setdefault("users", {})
    data.setdefault("channels", [])
    data.setdefault("rss", [])
    data.setdefault("pending", [])
    data.setdefault("meta", {})

    if not isinstance(data["users"], dict):
        data["users"] = {}
    if not isinstance(data["channels"], list):
        data["channels"] = []
    if not isinstance(data["rss"], list):
        data["rss"] = []
    if not isinstance(data["pending"], list):
        data["pending"] = []

    for uid, udata in list(data["users"].items()):
        if not isinstance(udata, dict):
            data["users"][uid] = default_user()
            continue
        base = default_user(udata.get("role", USER))
        for key, value in base.items():
            udata.setdefault(key, value)
        if not isinstance(udata.get("settings"), dict):
            udata["settings"] = default_settings()
        for key in CATEGORY_TITLES:
            udata["settings"].setdefault(key, True)

        locs: list[dict[str, Any]] = []
        for loc in udata.get("locs") or []:
            if isinstance(loc, str):  # формат ещё до 2.0
                locs.append(new_location(loc, 0.0, 0.0))
                continue
            if not isinstance(loc, dict) or not loc.get("name"):
                continue
            item = new_location(
                str(loc["name"]),
                float(loc.get("lat") or 0.0),
                float(loc.get("lon") or 0.0),
            )
            for key in ("city", "district", "region", "street", "house"):
                if loc.get(key):
                    item[key] = str(loc[key])
            if loc.get("id"):
                item["id"] = str(loc["id"])
            locs.append(item)
        udata["locs"] = locs

    superadmin = str(config.SUPERADMIN_ID)
    if superadmin not in data["users"]:
        data["users"][superadmin] = default_user(SUPERADMIN)
        data["users"][superadmin]["weather_interval"] = 60
    else:
        data["users"][superadmin]["role"] = SUPERADMIN

    for channel in config.DEFAULT_CHANNELS + config.EXTRA_CHANNELS:
        if channel and channel not in data["channels"]:
            data["channels"].append(channel)
    for feed in config.DEFAULT_RSS + config.EXTRA_RSS:
        if feed and feed not in data["rss"]:
            data["rss"].append(feed)

    data["meta"]["schema"] = 3
    return data


# --------------------------------------------------------------------------
#  Загрузка и сохранение
# --------------------------------------------------------------------------

async def load() -> None:
    global DB
    directory = os.path.dirname(config.DATA_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)

    raw: dict[str, Any] = {}
    if os.path.exists(config.DATA_FILE):
        try:
            async with aiofiles.open(config.DATA_FILE, "r", encoding="utf-8") as fh:
                parsed = json.loads(await fh.read())
            raw = parsed if isinstance(parsed, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            backup = f"{config.DATA_FILE}.broken.{int(time.time())}"
            log.error("База повреждена (%s). Копия: %s", exc, backup)
            try:
                os.replace(config.DATA_FILE, backup)
            except OSError:
                pass

    DB = migrate(raw)
    await save()
    log.info(
        "База загружена: пользователей=%d, каналов=%d, RSS=%d",
        len(DB["users"]), len(DB["channels"]), len(DB["rss"]),
    )


async def save() -> None:
    async with _lock:
        payload = json.dumps(DB, ensure_ascii=False, indent=2)
        tmp = f"{config.DATA_FILE}.tmp"
        async with aiofiles.open(tmp, "w", encoding="utf-8") as fh:
            await fh.write(payload)
        os.replace(tmp, config.DATA_FILE)


# --------------------------------------------------------------------------
#  Доступ к данным
# --------------------------------------------------------------------------

def users() -> dict[str, Any]:
    return DB.setdefault("users", {})


def get_user(uid: int | str) -> dict[str, Any] | None:
    return users().get(str(uid))


def exists(uid: int | str) -> bool:
    return str(uid) in users()


def role_of(uid: int | str) -> str | None:
    user = get_user(uid)
    return user.get("role") if user else None


def register(uid: int | str, username: str = "") -> dict[str, Any]:
    user = default_user(USER, username)
    users()[str(uid)] = user
    return user


def find_location(uid: int | str, loc_id: str) -> dict[str, Any] | None:
    user = get_user(uid)
    if not user:
        return None
    for loc in user["locs"]:
        if loc.get("id") == loc_id:
            return loc
    return None


def remove_location(uid: int | str, loc_id: str) -> bool:
    user = get_user(uid)
    if not user:
        return False
    before = len(user["locs"])
    user["locs"] = [loc for loc in user["locs"] if loc.get("id") != loc_id]
    return len(user["locs"]) != before


def channels() -> list[str]:
    return DB.setdefault("channels", [])


def rss_feeds() -> list[str]:
    return DB.setdefault("rss", [])


def pending() -> list[str]:
    return DB.setdefault("pending", [])


def meta() -> dict[str, Any]:
    return DB.setdefault("meta", {})
RADAR_FILE_10
printf "  %s\n" "radar/ai.py"
cat > "radar/ai.py" <<'RADAR_FILE_11'
"""Слой Google Gemini: устойчивые запросы, экономный разбор новостей, ассистент.

Экономия квоты бесплатного тарифа держится на четырёх приёмах:
  1. предфильтр по ключевым словам — заведомо нерелевантное не уходит в модель;
  2. пакетный разбор — до AI_BATCH_SIZE новостей одним запросом;
  3. кэш результатов по хэшу текста — повтор не оплачивается;
  4. учёт RPM/RPD с резервом суточных запросов под живой диалог.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import OrderedDict
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


class AIError(RuntimeError):
    """Ошибка обращения к модели с понятным пользователю текстом."""


def _config(
    system: str | None,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
    search: bool,
):
    kwargs: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_tokens}
    if system:
        kwargs["system_instruction"] = system
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    if _features["thinking"]:
        # Без этого модели 2.5 расходуют весь бюджет токенов на размышления
        # и возвращают пустой response.text.
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    if _features["safety"]:
        kwargs["safety_settings"] = [
            types.SafetySetting(category=category, threshold="BLOCK_ONLY_HIGH")
            for category in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ]
    if search and _features["search"] and not json_mode:
        # Поиск в интернете несовместим со строгим JSON-режимом,
        # поэтому включается только для свободного диалога.
        kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
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


async def generate(
    contents: Any,
    *,
    system: str | None = None,
    json_mode: bool = False,
    max_tokens: int = 2048,
    temperature: float = 0.4,
    retries: int = 3,
    model: str | None = None,
    priority: bool = True,
    search: bool = False,
) -> str:
    """Запрос к модели с учётом квот.

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

    target = model or config.GEMINI_MODEL
    last: AIError | None = None
    for attempt in range(retries):
        cfg = _config(system, json_mode, max_tokens, temperature, search)
        try:
            async with _semaphore:
                response = await asyncio.wait_for(
                    _client.aio.models.generate_content(
                        model=target, contents=contents, config=cfg
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
            if "thinking" in low and _features["thinking"]:
                _features["thinking"] = False
                log.warning("Отключаю thinking_config: %s", detail)
                continue
            if "safety" in low and _features["safety"]:
                _features["safety"] = False
                log.warning("Отключаю safety_settings: %s", detail)
                continue
            if ("tool" in low or "google_search" in low) and _features["search"]:
                _features["search"] = False
                log.warning("Отключаю поиск в интернете: %s", detail)
                continue
            if any(key in low for key in ("429", "resource_exhausted", "quota", "rate limit")):
                limiter.note_rejection()
                raise AIError(
                    "Превышена квота Gemini (429). Суточный лимит бесплатного тарифа "
                    "обнуляется в полночь по тихоокеанскому времени — около 10–11 утра "
                    "по Москве. Проверить расход: /quota"
                ) from exc
            if any(key in low for key in ("500", "503", "unavailable", "internal", "deadline")):
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if any(key in low for key in ("api key", "401", "403", "permission", "unauthenticated")):
                raise AIError("Неверный или неактивный GEMINI_API_KEY.") from exc
            if "not found" in low or "404" in low:
                raise AIError(f"Модель «{target}» недоступна для этого ключа.") from exc
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
    "Ты всегда отвечаешь одним валидным JSON-массивом без пояснений и без Markdown."
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
8. Количество объектов в массиве должно совпадать с количеством сообщений."""

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


def _fallback(text: str, source: str) -> Analysis:
    analysis = heuristic_analysis(text, source=source, default_city=config.DEFAULT_CITY)
    if not analysis.city and config.DEFAULT_CITY:
        analysis.city = config.DEFAULT_CITY
    return analysis


async def analyze_batch(items: Sequence[tuple[str, str]]) -> list[Analysis]:
    """Разбирает список пар (текст, источник), тратя минимум запросов к модели."""
    results: list[Analysis | None] = [None] * len(items)
    todo: list[int] = []

    for index, (text, source) in enumerate(items):
        key = _cache_key(text)
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            _counters["cached"] += 1
            results[index] = cached
            continue

        if config.AI_PREFILTER:
            # Дешёвая проверка: если ключевых слов нет вовсе, модель не нужна.
            probe = heuristic_analysis(text, source=source, default_city=config.DEFAULT_CITY)
            if not probe.relevant:
                _counters["prefiltered"] += 1
                results[index] = _remember(text, probe)
                continue

        if not ENABLED:
            _counters["heuristic"] += 1
            results[index] = _remember(text, _fallback(text, source))
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
                model=config.GEMINI_MODEL_ANALYSIS,
                priority=False,
            )
            _counters["requests"] += 1
            payloads = _parse_array(raw)
        except QuotaExceeded:
            log.info("Квота исчерпана — оставшиеся %d сообщений по эвристике", len(chunk))
            for index in chunk:
                _counters["heuristic"] += 1
                results[index] = _remember(items[index][0], _fallback(*items[index]))
            continue
        except (AIError, ValueError, json.JSONDecodeError) as exc:
            log.warning("Пакетный разбор не удался (%s) — эвристика", exc)
            for index in chunk:
                _counters["heuristic"] += 1
                results[index] = _remember(items[index][0], _fallback(*items[index]))
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
            text, source = items[index]
            if payload is None:
                _counters["heuristic"] += 1
                results[index] = _remember(text, _fallback(text, source))
                continue
            analysis = Analysis.from_payload(payload, source=source, raw=text)
            if not analysis.city and config.DEFAULT_CITY:
                analysis.city = config.DEFAULT_CITY
            _counters["ai"] += 1
            results[index] = _remember(text, analysis)

    return [item if item is not None else Analysis(relevant=False) for item in results]


async def analyze(text: str, source: str) -> Analysis:
    """Разбор одного сообщения (обёртка над пакетным)."""
    return (await analyze_batch([(text, source)]))[0]


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
    "Отвечай по-русски, кратко и по делу. Разметка: **жирный**, `код`, списки."
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
        model=config.GEMINI_MODEL,
        priority=True,
        search=True,
    )
RADAR_FILE_11
printf "  %s\n" "radar/geocode.py"
cat > "radar/geocode.py" <<'RADAR_FILE_12'
"""Обратное геокодирование (Nominatim) с бережным соблюдением лимита 1 запрос/сек."""

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
RADAR_FILE_12
printf "  %s\n" "radar/weather.py"
cat > "radar/weather.py" <<'RADAR_FILE_13'
"""Погода и краткий прогноз через Open-Meteo (без ключа API)."""

from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("radar.weather")

_URL = "https://api.open-meteo.com/v1/forecast"

CODES = {
    0: "☀️ ясно", 1: "🌤 малооблачно", 2: "⛅️ облачно", 3: "☁️ пасмурно",
    45: "🌫 туман", 48: "🌫 изморозь",
    51: "🌦 морось", 53: "🌦 морось", 55: "🌦 сильная морось",
    56: "🌧 ледяная морось", 57: "🌧 ледяная морось",
    61: "🌧 небольшой дождь", 63: "🌧 дождь", 65: "🌧 сильный дождь",
    66: "🌧 ледяной дождь", 67: "🌧 ледяной дождь",
    71: "🌨 небольшой снег", 73: "🌨 снег", 75: "❄️ сильный снег", 77: "🌨 снежная крупа",
    80: "🌧 ливень", 81: "🌧 ливень", 82: "⛈ сильный ливень",
    85: "🌨 снегопад", 86: "🌨 сильный снегопад",
    95: "⛈ гроза", 96: "⛈ гроза с градом", 99: "⛈ сильная гроза с градом",
}


async def forecast(session: aiohttp.ClientSession, lat: float, lon: float) -> str:
    """HTML-блок: текущая погода и прогноз на 6 часов."""
    if not lat and not lon:
        return "⚠️ Нет координат — отправьте геопозицию заново."

    params = {
        "latitude": f"{lat}",
        "longitude": f"{lon}",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "wind_speed_10m,precipitation,weather_code",
        "hourly": "temperature_2m,precipitation_probability",
        "timezone": "auto",
        "forecast_hours": "7",
        "wind_speed_unit": "ms",
    }
    try:
        async with session.get(_URL, params=params) as response:
            if response.status != 200:
                return f"⚠️ Сервис погоды вернул код {response.status}."
            data = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Погода недоступна: %s", exc)
        return "⚠️ Сбой получения погоды."

    current = data.get("current") or {}
    try:
        code = CODES.get(int(current.get("weather_code", -1)), "")
    except (TypeError, ValueError):
        code = ""

    temp = current.get("temperature_2m", "?")
    feels = current.get("apparent_temperature")
    wind = current.get("wind_speed_10m", "?")
    humidity = current.get("relative_humidity_2m")

    head = f"🌡 <b>Сейчас:</b> {temp}°C"
    if feels is not None:
        head += f" (ощущается {feels}°C)"
    head += f" | 💨 {wind} м/с"
    if humidity is not None:
        head += f" | 💧 {humidity}%"
    if code:
        head += f" | {code}"

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    probs = hourly.get("precipitation_probability") or []
    slots = []
    for index in range(1, min(7, len(times))):
        clock = times[index].split("T")[1][:5] if "T" in times[index] else f"+{index}ч"
        value = temps[index] if index < len(temps) else "?"
        chance = probs[index] if index < len(probs) else 0
        slots.append(f"<code>{clock}</code> {value}°C ({chance}%)")

    if slots:
        return head + "\n⏱ <b>6 часов:</b> " + " | ".join(slots)
    return head
RADAR_FILE_13
printf "  %s\n" "radar/sources.py"
cat > "radar/sources.py" <<'RADAR_FILE_14'
"""Сбор сообщений из источников: публичные Telegram-каналы и RSS-ленты СМИ."""

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
            items.append(Item(source=label, text=text, kind="rss"))
    return items


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
RADAR_FILE_14
printf "  %s\n" "radar/tg.py"
cat > "radar/tg.py" <<'RADAR_FILE_15'
"""Экземпляр бота и безопасные обёртки отправки сообщений."""

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
RADAR_FILE_15
printf "  %s\n" "radar/keyboards.py"
cat > "radar/keyboards.py" <<'RADAR_FILE_16'
"""Инлайн-клавиатуры. Формат callback_data: «раздел:действие:аргумент»."""

from __future__ import annotations

from typing import Any, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import roles
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
    rows.append([InlineKeyboardButton(text="ℹ️ О системе", callback_data="menu:about")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
        ]
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
RADAR_FILE_16
printf "  %s\n" "radar/states.py"
cat > "radar/states.py" <<'RADAR_FILE_17'
"""Состояния FSM."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    suggest_source = State()
    add_channel = State()
    add_rss = State()
    weather_time = State()
    weather_interval = State()
    manual_address = State()
RADAR_FILE_17
printf "  %s\n" "radar/middlewares.py"
cat > "radar/middlewares.py" <<'RADAR_FILE_18'
"""Middleware доступа: регистрация по инвайту и отсев посторонних."""

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
RADAR_FILE_18
printf "  %s\n" "radar/monitor.py"
cat > "radar/monitor.py" <<'RADAR_FILE_19'
"""Фоновый цикл: сбор источников, разбор через ИИ, группировка и рассылка."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import aiohttp

from . import ai, config, geocode, sources, storage, weather
from .matching import Analysis, build_weather_message, plan_alerts
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
        blocks = []
        for cluster in clusters:
            lat, lon = cluster_center(cluster)
            blocks.append((cluster, await weather.forecast(session, lat, lon)))
        if blocks:
            await send_html(uid, build_weather_message(blocks), back_kb())
            sent += 1
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
            parsed = await ai.analyze_batch([(item.text, item.source) for item in items])
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
RADAR_FILE_19
printf "  %s\n" "radar/handlers/__init__.py"
cat > "radar/handlers/__init__.py" <<'RADAR_FILE_20'
"""Роутеры обработчиков. Порядок подключения важен: ассистент — последним."""

from __future__ import annotations

from aiogram import Dispatcher

from . import assistant, common, locations, settings, sources, users


def setup(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(locations.router)
    dp.include_router(settings.router)
    dp.include_router(sources.router)
    dp.include_router(users.router)
    # Ассистент перехватывает любой оставшийся текст — только в самом конце.
    dp.include_router(assistant.router)


__all__ = ["setup"]
RADAR_FILE_20
printf "  %s\n" "radar/handlers/common.py"
cat > "radar/handlers/common.py" <<'RADAR_FILE_21'
"""Команды /start, /menu, /help, /id, /cancel и главное меню."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

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
    await message.answer(greeting(role), reply_markup=keyboards.main_menu(role))


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    await message.answer(greeting(role), reply_markup=keyboards.main_menu(role))


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
    ]
    if roles.can_use_assistant(role):
        lines.append("/ai &lt;вопрос&gt; — ИИ-ассистент - /aireset — очистить контекст")
        lines.append("/quota — расход квоты Gemini")
    if roles.is_admin(role):
        lines.append("/stats — статистика системы")
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
    text = (
        f"ℹ️ <b>Система «Радар» v{config.VERSION}</b>\n\n"
        "Мониторит публичные Telegram-каналы служб ЖКХ, МЧС, администраций города, "
        "района и области, а также ленты СМИ. Сообщения разбирает ИИ Google Gemini, "
        "после чего события сопоставляются с вашими локациями.\n\n"
        "🛸 Военные угрозы — на весь город.\n"
        "🛠 ЖКХ — адресно, по улице и дому.\n"
        "🌤 Погода — по каждой группе локаций.\n\n"
        "<i>Система не заменяет официальные каналы оповещения.</i>"
    )
    await safe_edit(call, text, back_kb())


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
        f"ИИ: <b>{esc(config.GEMINI_MODEL) if ai.ENABLED else 'выключен (эвристика)'}</b>",
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
        f"Анализ: <code>{esc(config.GEMINI_MODEL_ANALYSIS)}</code>, "
        f"ассистент: <code>{esc(config.GEMINI_MODEL)}</code>",
        "<i>Суточный лимит обнуляется в полночь по тихоокеанскому времени "
        "(около 10–11 утра по Москве).</i>",
    ]
    await message.answer("\n".join(lines), reply_markup=back_kb())


@router.callback_query(F.data == "menu:stats")
async def stats_button(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _stats_text(), back_kb("menu:admin", "◀️ Назад"))
RADAR_FILE_21
printf "  %s\n" "radar/handlers/locations.py"
cat > "radar/handlers/locations.py" <<'RADAR_FILE_22'
"""Локации пользователя: добавление, список, удаление, погода по группам."""

from __future__ import annotations

from typing import Any

import aiohttp
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from .. import config, geocode, keyboards, roles, storage, weather
from ..matching import build_weather_message
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


@router.message(F.location)
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
    blocks = []
    async with _session() as session:
        for cluster in clusters:
            lat, lon = cluster_center(cluster)
            blocks.append((cluster, await weather.forecast(session, lat, lon)))
    await send_html(call.message.chat.id, build_weather_message(blocks), back_kb())
RADAR_FILE_22
printf "  %s\n" "radar/handlers/settings.py"
cat > "radar/handlers/settings.py" <<'RADAR_FILE_23'
"""Настройки: категории оповещений и режим отправки погоды."""

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
RADAR_FILE_23
printf "  %s\n" "radar/handlers/sources.py"
cat > "radar/handlers/sources.py" <<'RADAR_FILE_24'
"""Источники: предложение пользователем, очередь модерации, ручное добавление."""

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards, roles, storage
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
RADAR_FILE_24
printf "  %s\n" "radar/handlers/users.py"
cat > "radar/handlers/users.py" <<'RADAR_FILE_25'
"""Пользователи: список, карточка, смена роли, удаление, правка локаций и настроек."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from .. import keyboards, roles, storage
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
    storage.users().pop(target, None)
    await storage.save()
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
RADAR_FILE_25
printf "  %s\n" "radar/handlers/assistant.py"
cat > "radar/handlers/assistant.py" <<'RADAR_FILE_26'
"""ИИ-ассистент в диалоге. Доступен начиная с роли «модератор».

Роутер подключается последним: перехватывает любой необработанный текст.
"""

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
RADAR_FILE_26
ok "Файлы записаны"

# --- 3. Настройки ---------------------------------------------------------
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
    read -r -p "Файл .env найден. Использовать текущие настройки? (Y/n): " reply < /dev/tty || true
    case "${reply:-y}" in
        [Nn]*) RECREATE_ENV=true ;;
        *) ok "Использую существующий .env" ;;
    esac
else
    RECREATE_ENV=true
fi

if [ "$RECREATE_ENV" = true ]; then
    echo
    echo "Заполните параметры (Ctrl+C — выход):"
    ask "  Токен Telegram-бота (@BotFather): " IN_TOKEN '^[0-9]{6,}:[A-Za-z0-9_-]{30,}$' yes
    ask "  Ваш Telegram ID (@userinfobot): " IN_ADMIN '^[0-9]{5,}$' yes
    ask "  Ключ Google Gemini (Enter — без ИИ): " IN_GEMINI '^.{20,}$' no
    ask "  Часовой пояс [Europe/Saratov]: " IN_TZ '^[A-Za-z]+/[A-Za-z_+-]+$' no
    ask "  Город по умолчанию [Саратов]: " IN_CITY '.+' no
    : "${IN_TZ:=Europe/Saratov}"
    : "${IN_CITY:=Саратов}"

    umask 077
    cat > .env <<ENVEOF
BOT_TOKEN=${IN_TOKEN}
SUPERADMIN_ID=${IN_ADMIN}
GEMINI_API_KEY=${IN_GEMINI:-}
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MODEL_ANALYSIS=gemini-2.5-flash-lite
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
POLL_INTERVAL=180
MSG_PER_SOURCE=5
CLUSTER_RADIUS_M=1000
MAX_LOCATIONS=0
EXTRA_CHANNELS=
EXTRA_RSS=
LOG_LEVEL=INFO
ENVEOF
    umask 022
    chmod 600 .env
    ok "Файл .env создан"
    [ -z "${IN_GEMINI:-}" ] && warn "Ключ Gemini не задан: ассистент отключён, анализ пойдёт по ключевым словам."
fi

TZ_VALUE="$(grep -E '^TZ=' .env | cut -d= -f2- || true)"
: "${TZ_VALUE:=Europe/Saratov}"

# --- 4. Сборка и запуск ---------------------------------------------------
info "Останавливаю прежний контейнер"
docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true

info "Сборка образа $IMAGE_NAME (часовой пояс $TZ_VALUE)"
docker build $NO_CACHE --build-arg "TZ=$TZ_VALUE" -t "$IMAGE_NAME" . \
    || die "Сборка образа не удалась"

info "Запуск контейнера $CONTAINER_NAME"
docker run -d \
    --name "$CONTAINER_NAME" \
    --env-file "$APP_DIR/.env" \
    --restart unless-stopped \
    --log-opt max-size=10m --log-opt max-file=3 \
    -v "$APP_DIR/data:/app/data" \
    "$IMAGE_NAME" >/dev/null || die "Не удалось запустить контейнер"

sleep 5
if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null)" != "true" ]; then
    warn "Контейнер остановился. Последние строки лога:"
    docker logs --tail 40 "$CONTAINER_NAME" || true
    exit 1
fi

trap - ERR
ok "Система «Радар» v${VERSION} запущена."
echo
echo "  Логи:        docker logs -f $CONTAINER_NAME"
echo "  Перезапуск:  docker restart $CONTAINER_NAME"
echo "  Остановка:   docker stop $CONTAINER_NAME"
echo "  Данные:      $APP_DIR/data/db.json"
echo "  Обновление:  bash <(curl -fsSL https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh)"
echo
echo "  Откройте бота в Telegram и отправьте /start, затем пришлите геопозицию."
echo

if [ "$SHOW_LOGS" = true ]; then
    docker logs -f "$CONTAINER_NAME"
fi
