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
