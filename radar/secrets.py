"""Секреты, которые задаются из бота: ключи ИИ, доступы к площадкам, Bot API.

Значения пишутся в `.env` рядом с ботом — тот же файл, что читает установщик.
Так настройка из интерфейса и настройка руками не расходятся.

Что важно понимать про применение
---------------------------------
Часть значений подхватывается сразу (ключи провайдеров ИИ читаются при
каждом запросе), часть — только после перезапуска контейнера: это касается
всего, что участвует в создании клиентов на старте, в первую очередь
`TELEGRAM_API_ID`, `TELEGRAM_API_HASH` и `TELEGRAM_API_SERVER`. В интерфейсе
это подписано у каждого поля, чтобы не гадать, почему «не сработало».
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from . import config

log = logging.getLogger("radar.secrets")

ENV_PATH = os.getenv("ENV_FILE") or ".env"


@dataclass(frozen=True)
class Setting:
    key: str
    title: str
    hint: str
    group: str
    restart: bool = False     # применяется только после перезапуска
    secret: bool = True       # показывать замаскированным
    where: str = ""           # где получить значение


SETTINGS: tuple[Setting, ...] = (
    # --- провайдеры ИИ ---
    Setting("GEMINI_API_KEY", "Google Gemini", "Основной провайдер: разбор новостей и ассистент.",
            "ИИ", where="aistudio.google.com/apikey"),
    Setting("GROQ_API_KEY", "Groq", "Быстрые открытые модели, щедрый бесплатный тариф.",
            "ИИ", where="console.groq.com/keys"),
    Setting("CEREBRAS_API_KEY", "Cerebras", "Открытые модели, около миллиона токенов в сутки.",
            "ИИ", where="cloud.cerebras.ai"),
    Setting("MISTRAL_API_KEY", "Mistral", "Европейская юрисдикция, 2 запроса в минуту.",
            "ИИ", where="console.mistral.ai"),
    Setting("OPENROUTER_API_KEY", "OpenRouter", "Один ключ на десятки моделей, есть бесплатные.",
            "ИИ", where="openrouter.ai/keys"),
    Setting("DEEPSEEK_API_KEY", "DeepSeek", "Очень низкая цена; проверьте фильтрацию военных тем.",
            "ИИ", where="platform.deepseek.com"),
    Setting("ZAI_API_KEY", "Z.ai / GLM", "Модели GLM, часть доступна бесплатно.",
            "ИИ", where="z.ai"),
    Setting("MOONSHOT_API_KEY", "Moonshot Kimi", "До тысячи запросов в сутки бесплатно.",
            "ИИ", where="platform.moonshot.ai"),
    Setting("DASHSCOPE_API_KEY", "Alibaba Qwen", "Международный эндпоинт DashScope.",
            "ИИ", where="modelstudio.console.alibabacloud.com"),
    Setting("OPENAI_API_KEY", "OpenAI", "Платный.", "ИИ", where="platform.openai.com"),
    Setting("ANTHROPIC_API_KEY", "Anthropic Claude", "Платный.", "ИИ",
            where="console.anthropic.com"),

    # --- источники ---
    Setting("VK_SERVICE_TOKEN", "ВКонтакте", "Сервисный ключ сообщества для чтения стен.",
            "Источники", where="Управление сообществом → Работа с API"),
    Setting("OK_APPLICATION_KEY", "OK: ключ приложения", "Публичный ключ приложения.",
            "Источники", secret=False, where="apiok.ru"),
    Setting("OK_ACCESS_TOKEN", "OK: токен доступа", "Токен приложения.",
            "Источники", where="apiok.ru"),
    Setting("OK_SECRET_KEY", "OK: секретный ключ", "Используется для подписи запросов.",
            "Источники", where="apiok.ru"),

    # --- медиа ---
    Setting("TELEGRAM_API_ID", "Telegram api_id", "Нужен для своего Bot API Server.",
            "Медиа", restart=True, secret=False, where="my.telegram.org → API development tools"),
    Setting("TELEGRAM_API_HASH", "Telegram api_hash", "Нужен для своего Bot API Server.",
            "Медиа", restart=True, where="my.telegram.org → API development tools"),
    Setting("TELEGRAM_API_SERVER", "Адрес Bot API Server",
            "Например http://telegram-bot-api:8081. Снимает предел 50 МБ.",
            "Медиа", restart=True, secret=False),

    # --- сеть ---
    Setting("EGRESS_PROXY", "Прокси для выхода в сеть",
            "Например socks5://singbox:1080.", "Сеть", restart=True, secret=False),
    Setting("MEDIA_COOKIES", "Файл cookies",
            "Путь к cookies.txt для закрытых площадок.", "Медиа", secret=False),
)

BY_KEY = {item.key: item for item in SETTINGS}
GROUPS: tuple[str, ...] = tuple(dict.fromkeys(item.group for item in SETTINGS))

_LINE = re.compile(r"^(\w+)=(.*)$")


def env_path() -> str:
    return ENV_PATH


def read_env() -> dict[str, str]:
    """Текущее содержимое .env. Отсутствие файла — не ошибка."""
    values: dict[str, str] = {}
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = _LINE.match(stripped)
                if match:
                    values[match.group(1)] = match.group(2)
    except OSError:
        pass
    return values


def get(key: str) -> str:
    """Значение: сначала из .env, потом из окружения процесса."""
    return read_env().get(key) or os.getenv(key) or ""


def write(key: str, value: str) -> bool:
    """Записывает значение в .env, сохраняя остальные строки и комментарии."""
    if "\n" in value or "\r" in value:
        return False

    try:
        lines: list[str] = []
        if os.path.exists(ENV_PATH):
            with open(ENV_PATH, "r", encoding="utf-8") as handle:
                lines = handle.readlines()

        replaced = False
        for index, line in enumerate(lines):
            match = _LINE.match(line.strip())
            if match and match.group(1) == key:
                lines[index] = f"{key}={value}\n"
                replaced = True
                break
        if not replaced:
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f"{key}={value}\n")

        # Атомарная запись: оборванная запись .env оставила бы бота без токена
        temporary = f"{ENV_PATH}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        os.replace(temporary, ENV_PATH)
        os.chmod(ENV_PATH, 0o600)
    except OSError as exc:
        log.error("Не удалось записать %s в %s: %s", key, ENV_PATH, exc)
        return False

    # Применяем к текущему процессу: провайдеры ИИ читают ключи на лету
    os.environ[key] = value
    log.info("Обновлено значение %s (%d символов)", key, len(value))
    return True


def clear(key: str) -> bool:
    return write(key, "")


def mask(value: str) -> str:
    """Показ значения без раскрытия секрета."""
    if not value:
        return "— не задано —"
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]} ({len(value)} симв.)"


def display(setting: Setting) -> str:
    value = get(setting.key)
    if not value:
        return "— не задано —"
    return value if not setting.secret else mask(value)


def by_group() -> dict[str, list[Setting]]:
    grouped: dict[str, list[Setting]] = {name: [] for name in GROUPS}
    for setting in SETTINGS:
        grouped[setting.group].append(setting)
    return grouped


def filled(group: str | None = None) -> int:
    items = SETTINGS if group is None else by_group().get(group, [])
    return sum(1 for item in items if get(item.key))


def writable() -> bool:
    """Доступен ли .env на запись — иначе настройка из бота бессмысленна."""
    target = os.path.dirname(os.path.abspath(ENV_PATH)) or "."
    if os.path.exists(ENV_PATH):
        return os.access(ENV_PATH, os.W_OK)
    return os.access(target, os.W_OK)
