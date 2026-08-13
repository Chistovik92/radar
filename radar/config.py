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
    return logging.getLogger("radar")


def validate() -> None:
    """Проверяет обязательные параметры и завершает процесс при их отсутствии."""
    log = logging.getLogger("radar.config")
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN не задан")
    if not DATABASE_URL and not DB_PASSWORD:
        problems.append("DB_PASSWORD не задан (или задайте DATABASE_URL целиком)")
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
