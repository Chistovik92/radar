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

    # --- веб-панель ---
    Setting("WEB_PUBLIC_URL", "Публичный адрес панели",
            "Адрес, по которому панель открыта снаружи, например "
            "https://example.ru. Показывается в /panel. Пусто — панель "
            "считается доступной только с сервера.",
            "Панель", secret=False),

    # --- сокращение ссылок ---
    Setting("SHORT_BASE_URL", "Адрес для коротких ссылок",
            "Адрес, на котором открыта веб-панель, например https://example.ru. "
            "Пока не задан, сокращение отключено.",
            "Ссылки", secret=False),
    Setting("SHORT_SALT", "Соль коротких кодов",
            "Любая строка. Разводит коды разных экземпляров «Радара», "
            "чтобы они не совпадали. Менять после запуска нельзя: "
            "уже разосланные ссылки перестанут открываться.",
            "Ссылки"),

    # --- защита ---
    Setting("SAFE_BROWSING_API_KEY", "Google Safe Browsing",
            "Базы вредоносных сайтов для проверки ссылок (/check). "
            "Без ключа сетевые проверки работают частично.",
            "Защита", where="console.cloud.google.com → Safe Browsing API"),
)

# --------------------------------------------------------------------------
#  Свои агенты (с 4.8.8)
# --------------------------------------------------------------------------
#
# До 4.8.8 свой агент был ровно один: пара CUSTOM_AI_URL и CUSTOM_AI_KEY
# среди двух десятков чужих ключей. Сервисов бывает несколько — локальная
# модель, корпоративный шлюз, чей-то прокси, — поэтому теперь это слоты
# по три поля: название, адрес, ключ.
#
# Слоты добавляются в общий перечень настроек, а не живут отдельной
# машинерией: раздел ключей в боте, запись в .env и правка из панели уже
# умеют работать с Setting, и второй такой механизм пришлось бы чинить
# дважды. Смысловая часть — в radar/agents.py, здесь только имена и вид.

AGENT_GROUP = "Свои агенты"
AGENT_SLOTS = 5
AGENT_PREFIX = "CUSTOM_AI"


def agent_env_names(slot: int) -> tuple[str, str, str, str]:
    """Имена настроек слота: название, адрес, ключ, модель.

    Модель нарочно названа так же, как у встроенных провайдеров
    (`AI_MODEL_<ИМЯ>`), а не по образцу остальных полей слота. Иначе
    выбранная модель хранилась бы в двух местах: здесь и в общем выборе
    модели, который есть у каждого провайдера. Одно значение — одно имя.
    """
    return (f"{AGENT_PREFIX}_{slot}_TITLE",
            f"{AGENT_PREFIX}_{slot}_URL",
            f"{AGENT_PREFIX}_{slot}_KEY",
            f"AI_MODEL_CUSTOM{slot}")


def _agent_settings(slots: int) -> tuple[Setting, ...]:
    built: list[Setting] = []
    for slot in range(1, slots + 1):
        title_env, url_env, key_env, model_env = agent_env_names(slot)
        built.append(Setting(
            title_env, f"Агент {slot}: название",
            "Как агент будет показан в списке моделей. "
            "«Локальная Llama» говорит больше, чем «свой агент 3».",
            AGENT_GROUP, secret=False))
        built.append(Setting(
            url_env, f"Агент {slot}: базовый адрес",
            "Основание адреса без /chat/completions, например "
            "http://ollama:11434/v1",
            AGENT_GROUP, secret=False, where="ваш сервис"))
        built.append(Setting(
            key_env, f"Агент {slot}: ключ API",
            "Если сервис не требует ключа, впишите любое непустое значение.",
            AGENT_GROUP, where="ваш сервис"))
        built.append(Setting(
            model_env, f"Агент {slot}: модель",
            "Имя модели у этого сервиса, например llama3.1:8b. "
            "У своего агента списка моделей не спросить — вписывается руками.",
            AGENT_GROUP, secret=False))
    return tuple(built)


# Бот показывает первые пять слотов: в переписке длинный список неудобен,
# а пяти сервисов хватает с запасом. Панель заводит агентов без этого
# ограничения — там у неё своя вкладка, и слоты сверх пятого правятся
# в ней. Разделение осознанное: перечень настроек собирается один раз при
# старте, и «показывать всё, что заведено» означало бы либо перечитывать
# .env на каждый показ, либо врать до перезапуска.
SETTINGS = SETTINGS + _agent_settings(AGENT_SLOTS)

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

    # Копия перед правкой: потерять прежние ключи из-за опечатки нельзя
    try:
        from . import backup as backup_module

        backup_module.backup_env()
    except Exception:  # noqa: BLE001
        log.debug("Копию .env создать не удалось", exc_info=True)

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

        # Запись НА МЕСТО, а не подмена через переименование.
        #
        # До 4.8.4.2 здесь стоял os.replace ради атомарности: оборванная
        # запись .env оставила бы бота без токена. Но с версии 4.8.4.2
        # .env смонтирован в контейнер, а bind-mount привязан к ИНОДУ,
        # не к пути. Переименование в точку монтирования возвращает EBUSY,
        # а если бы прошло — хост писал бы в новый файл, контейнер читал бы
        # вечно старый. Молчаливое расхождение хуже оборванной записи.
        #
        # Атомарность заменена копией: backup_env выше снимает .env перед
        # каждой правкой, и последние десять копий лежат в data/backups.
        with open(ENV_PATH, "w", encoding="utf-8") as handle:
            handle.write("".join(lines))

        # Права выставляем отдельно и мягко: файл может принадлежать
        # другому пользователю (в контейнере бот работает под uid 1000,
        # на хосте .env заводит root), и отказ chmod не повод считать
        # запись неудавшейся — значение уже на диске.
        try:
            os.chmod(ENV_PATH, 0o600)
        except OSError:
            log.debug("Права на %s оставлены как есть", ENV_PATH)
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
