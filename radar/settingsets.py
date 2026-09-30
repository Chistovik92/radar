"""Настройки, которые раньше правились только в .env (5.9.2.2).

До 5.9.2.2 в панели можно было изменить ключи ИИ и несколько токенов, а всё
остальное — настройки ИИ и оповещений, MAX, медиа, раздачу файлов, проверку
ссылок, журнал, адрес панели — лежало только в `.env` на сервере. Здесь они
описаны так же, как прочие значения: название, подсказка, тип, границы.

Что намеренно НЕ выведено в панель, и почему:

* `PROMO_IN_ALERTS` — реклама внутри тревожных сообщений запрещена правилами
  проекта; переключателя для неё быть не должно.
* `SUPERADMIN_ID`, `SECRET_KEY`, `DATABASE_URL`, `DB_*`, `DATA_FILE`,
  `ENV_FILE`, `LOG_DIR`, `RADAR_HOST_DIR` — основа установки: неверное
  значение оставляет бот без владельца, без базы или без доступа к данным,
  а исправлять это придётся уже не из панели. Их меняет установщик.
* `AI_PROVIDER`, `EGRESS_*` — состояние, которое бот пишет сам.
* Все значения, прочитанные при запуске (`restart=True`), вступают в силу
  после перезапуска; панель предлагает его кнопкой, когда есть docker.

Функция `build` получает класс `Setting` параметром, а не импортирует его:
`secrets` импортирует этот модуль, и обратный импорт был бы циклом.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
from typing import Any

# Группа → раздел «Настроек» веб-панели. Сам порядок и состав карточек —
# в radar/web/settingspages.py; здесь только переименование прежних групп,
# чтобы ключи одной платформы оказались рядом.
REGROUP = {
    "ВК-бот": "ВКонтакте",
    "VK_SERVICE_TOKEN": "ВКонтакте",
    "OK_APPLICATION_KEY": "Одноклассники",
    "OK_ACCESS_TOKEN": "Одноклассники",
    "OK_SECRET_KEY": "Одноклассники",
    "TELEGRAM_API_ID": "Telegram",
    "TELEGRAM_API_HASH": "Telegram",
    "TELEGRAM_API_SERVER": "Telegram",
    "MUSIC_CLOUD_URL": "Облако музыки",
    "MUSIC_CLOUD_USER": "Облако музыки",
    "MUSIC_CLOUD_PASSWORD": "Облако музыки",
    "RCLONE_RC_URL": "Облако музыки",
    "RCLONE_RC_USER": "Облако музыки",
    "RCLONE_RC_PASS": "Облако музыки",
    "MEDIA_COOKIES": "Загрузка видео",
    "EGRESS_PROXY": "Сеть",
    "WEB_PUBLIC_URL": "Веб-панель",
    "SHORT_BASE_URL": "Короткие ссылки",
    "SHORT_SALT": "Короткие ссылки",
    "SAFE_BROWSING_API_KEY": "Проверка ссылок",
}

# Типы уже существующих значений.
REFINE = {
    "TELEGRAM_API_ID": {"kind": "int", "low": 1},
    "DISCORD_CHANNEL_ID": {"kind": "int", "low": 1},
    "DISCORD_SUMMARY_TIME": {"kind": "time"},
    "VK_BOT_GROUP_ID": {"kind": "int", "low": 1},
    "WEB_PUBLIC_URL": {"kind": "url"},
    "SHORT_BASE_URL": {"kind": "url"},
    "TELEGRAM_API_SERVER": {"kind": "url"},
    "MUSIC_CLOUD_URL": {"kind": "url"},
    "RCLONE_RC_URL": {"kind": "url"},
}


def _num(key: str, title: str, hint: str, group: str, default: int, low: int | None = None,
         high: int | None = None, restart: bool = True, cls: Any = None) -> Any:
    return cls(key, title, hint, group, restart=restart, secret=False,
               kind="int", low=low, high=high, default=str(default))


def build(Setting: Any) -> tuple[Any, ...]:  # noqa: N803 — это класс, а не переменная
    def num(*args, **kwargs):
        return _num(*args, cls=Setting, **kwargs)

    def flag(key, title, hint, group, default, restart=True):
        return Setting(key, title, hint, group, restart=restart, secret=False,
                       kind="bool", default="1" if default else "0")

    def text(key, title, hint, group, restart=True, kind="text", where="", choices=(), default=""):
        return Setting(key, title, hint, group, restart=restart, secret=False, kind=kind,
                       where=where, choices=choices, default=default)

    return (
        # --- Telegram ---
        Setting("BOT_TOKEN", "Telegram: токен бота",
                "Основной токен от @BotFather. Неверное значение оставит бота без связи: "
                "перед сменой проверьте токен в @BotFather. Применяется после перезапуска.",
                "Telegram", restart=True, where="@BotFather"),
        flag("TELEGRAM_API_LOCAL", "Telegram: свой Bot API Server — файлы по пути",
             "1 — бот берёт большие файлы с диска сервера Bot API, а не по сети. "
             "Имеет смысл только с заданным TELEGRAM_API_SERVER.", "Telegram", True),

        # --- MAX ---
        Setting("MAX_BOT_TOKEN", "MAX: токен бота",
                "Токен бота мессенджера MAX. Пусто — MAX не используется. "
                "Включается флагом «MAX» на этой же странице.",
                "MAX", restart=True, where="business.max.ru"),
        text("MAX_API_URL", "MAX: адрес API", "По умолчанию https://platform-api2.max.ru.",
             "MAX", kind="url", default="https://platform-api2.max.ru"),
        text("MAX_MODE", "MAX: способ получения сообщений",
             "polling — бот сам опрашивает MAX; webhook — MAX присылает на адрес ниже "
             "(нужен открытый HTTPS-адрес).", "MAX", kind="choice",
             choices=("polling", "webhook"), default="polling"),
        text("MAX_WEBHOOK_URL", "MAX: адрес webhook", "Внешний HTTPS-адрес, на который MAX шлёт события.",
             "MAX", kind="url"),
        num("MAX_WEBHOOK_PORT", "MAX: порт webhook", "Порт внутри контейнера.", "MAX",
            8081, 1, 65535),

        # --- ИИ: модели и лимиты ---
        text("GEMINI_MODEL", "Gemini: модель ассистента", "Модель для разговора с ассистентом.",
             "ИИ: модели и лимиты", default="gemini-3.6-flash"),
        text("GEMINI_MODEL_ANALYSIS", "Gemini: модель разбора новостей",
             "Разбор — задача классификации: дешёвая модель с большей квотой.",
             "ИИ: модели и лимиты", default="gemini-3.5-flash-lite"),
        num("AI_CONCURRENCY", "ИИ: запросов одновременно", "Сколько обращений к модели идёт параллельно.",
            "ИИ: модели и лимиты", 2, 1, 16),
        num("AI_TIMEOUT", "ИИ: ожидание ответа, с", "Не меньше 20.", "ИИ: модели и лимиты", 90, 20, 600),
        num("AI_RPM", "ИИ: запросов в минуту", "Квота вашего тарифа у провайдера.",
            "ИИ: модели и лимиты", 15, 1, 10000),
        num("AI_RPD", "ИИ: запросов в сутки", "Квота вашего тарифа у провайдера.",
            "ИИ: модели и лимиты", 1000, 1, 10000000),
        num("AI_RESERVE", "ИИ: резерв под ассистента, запросов в сутки",
            "Эта часть суточной квоты не тратится на подборки — она защищает "
            "оповещения и ассистента.", "ИИ: модели и лимиты", 150, 0, 10000000),
        num("AI_BATCH_SIZE", "ИИ: новостей в одном запросе",
            "Крупнее пачка — меньше запросов на тот же объём.", "ИИ: модели и лимиты", 12, 1, 100),
        num("AI_COOLDOWN", "ИИ: пауза после отказа 429, с", "Не меньше 60.",
            "ИИ: модели и лимиты", 900, 60, 86400),
        flag("AI_PREFILTER", "ИИ: сначала фильтр по ключевым словам",
             "1 — до обращения к модели сообщения проходят дешёвый фильтр.",
             "ИИ: модели и лимиты", True),
        flag("AI_SEARCH", "ИИ: поиск в интернете для ассистента",
             "1 — ассистент может искать в сети (grounding).", "ИИ: модели и лимиты", True),

        # --- оповещения и источники ---
        num("POLL_INTERVAL", "Опрос источников, с", "Как часто бот обходит источники. Не меньше 60.",
            "Оповещения и источники", 180, 60, 86400),
        num("MSG_PER_SOURCE", "Сообщений с одного источника за обход", "Не меньше 1.",
            "Оповещения и источники", 5, 1, 100),
        num("SOURCE_CONCURRENCY", "Источников одновременно", "Параллельных запросов при обходе.",
            "Оповещения и источники", 6, 1, 64),
        num("CLUSTER_RADIUS_M", "Радиус объединения событий, м",
            "События ближе этого расстояния считаются одним. 0 — не объединять.",
            "Оповещения и источники", 1000, 0, 100000),
        num("MAX_LOCATIONS", "Адресов на человека", "0 — без ограничения.",
            "Оповещения и источники", 0, 0, 1000),
        num("EVENT_RETENTION_DAYS", "Хранить историю событий, дней", "0 — бессрочно.",
            "Оповещения и источники", 180, 0, 36500),
        text("DEFAULT_CITY", "Город по умолчанию", "Используется при первом заполнении списка источников.",
             "Оповещения и источники"),

        # --- загрузка видео и медиа ---
        text("MEDIA_DIR", "Видео: каталог загрузок", "Внутри контейнера; по умолчанию data/media.",
             "Загрузка видео", default="data/media"),
        text("MEDIA_RATE_LIMIT", "Видео: предел скорости скачивания",
             "Для yt-dlp, например 2M. Пусто — без предела.", "Загрузка видео"),
        num("MEDIA_CONCURRENCY", "Видео: загрузок одновременно", "Не меньше 1.", "Загрузка видео", 1, 1, 8),
        num("TRANSCODE_TIMEOUT", "Видео: предел сжатия, с", "Не меньше 60.", "Загрузка видео", 1800, 60, 86400),
        text("MEDIA_MIN_ROLE", "Видео: кому доступна загрузка",
             "Минимальная роль. Подписчики получают доступ отдельно.", "Загрузка видео",
             kind="choice", choices=("user", "moderator", "admin", "superadmin"), default="moderator"),
        text("MUSIC_DIR", "Музыка: каталог", "Каталог музыки или точка монтирования.",
             "Облако музыки", restart=False),
        num("FILEDROP_MAX_MB", "Раздача файлов: предел одного файла, МБ", "По умолчанию 5120.",
            "Раздача файлов", 5120, 1, 1048576),
        num("FILEDROP_BUDGET_MB", "Раздача файлов: общий бюджет, МБ",
            "Сколько места отдано под раздачу; превышение не даёт скачать новое.",
            "Раздача файлов", 15360, 1, 10485760),
        num("FILEDROP_TTL_HOURS", "Раздача файлов: срок жизни ссылки, ч", "По умолчанию 24.",
            "Раздача файлов", 24, 1, 8760),

        # --- проверка ссылок ---
        flag("LINKCHECK_NET", "Проверка ссылок: ходить по сети",
             "1 — проверять и сам адрес запросом; 0 — только по спискам.", "Проверка ссылок", True),
        num("LINKCHECK_TIMEOUT", "Проверка ссылок: ожидание, с", "Не меньше 5.", "Проверка ссылок", 15, 5, 120),
        num("LINKCHECK_RATE_LIMIT", "Проверка ссылок: запросов в минуту на человека", "Не меньше 1.",
            "Проверка ссылок", 5, 1, 1000),
        num("LINKCHECK_FREE_PER_DAY", "Проверка ссылок: бесплатных в сутки", "Не меньше 1.",
            "Проверка ссылок", 200, 1, 100000),

        # --- веб-панель, журнал, сеть ---
        text("WEB_HOST", "Веб-панель: на каком адресе слушать",
             "0.0.0.0 — на всех; 127.0.0.1 — только за обратным прокси на этом же сервере.",
             "Веб-панель", default="0.0.0.0"),
        num("WEB_PORT", "Веб-панель: порт", "Внутри контейнера. Менять нужно и проброс порта.",
            "Веб-панель", 8080, 1, 65535),
        flag("WEB_HTTPS", "Веб-панель: стоит за HTTPS",
             "1 — панель отдаёт cookie с флагом secure и верит заголовку X-Forwarded-For. "
             "Включайте только если перед панелью есть обратный прокси с HTTPS.",
             "Веб-панель", False),
        text("LOG_LEVEL", "Журнал: подробность", "INFO — обычный; DEBUG — подробный, для поиска ошибок.",
             "Журнал", kind="choice", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"),
        num("LOG_KEEP_DAYS", "Журнал: хранить, дней", "0 — не удалять.", "Журнал", 14, 0, 3650),
        num("LOG_MAX_MB", "Журнал: размер файла, МБ", "После этого размера файл ротируется.",
            "Журнал", 5, 1, 1024),
        text("USER_AGENT", "Сеть: User-Agent бота", "Как бот представляется источникам. Пусто — стандартный.",
             "Сеть"),

        # --- RustDesk ---
        text("RUSTDESK_PUBLIC_HOST", "RustDesk: внешний адрес", "Домен или IP, по которому клиенты видят сервер.",
             "RustDesk"),
        text("RUSTDESK_HBBS_CONTAINER", "RustDesk: контейнер hbbs", "Имя контейнера.", "RustDesk",
             default="radar_hbbs"),
        text("RUSTDESK_HBBR_CONTAINER", "RustDesk: контейнер hbbr", "Имя контейнера.", "RustDesk",
             default="radar_hbbr"),
        text("RUSTDESK_KEY_PATH", "RustDesk: путь к открытому ключу", "Внутри контейнера бота.",
             "RustDesk", default="data/rustdesk/id_ed25519.pub"),

        # --- реклама проекта ---
        flag("PROMO_ENABLED", "Реклама: кнопка в меню", "1 — в главном меню есть кнопка проекта. "
             "Реклама никогда не попадает в тревожные сообщения.", "Реклама", True),
        text("PROMO_TITLE", "Реклама: подпись кнопки", "Короткий текст кнопки.", "Реклама",
             default="🐙 HydraSite"),
        text("PROMO_URL", "Реклама: ссылка", "Куда ведёт кнопка.", "Реклама", kind="url"),
    )


def refine(settings: tuple[Any, ...]) -> tuple[Any, ...]:
    """Переименовывает группы и проставляет типы уже существующим значениям."""
    result = []
    for item in settings:
        changes: dict[str, Any] = {}
        group = REGROUP.get(item.key) or REGROUP.get(item.group)
        if group and group != item.group:
            changes["group"] = group
        changes.update(REFINE.get(item.key, {}))
        result.append(dataclasses.replace(item, **changes) if changes else item)
    return tuple(result)
