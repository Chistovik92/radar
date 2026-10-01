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
    # Тип нужен форме и проверке: число — полем-числом, выбор — списком,
    # флаг — переключателем. Значение в .env при этом остаётся строкой.
    kind: str = "text"        # text | int | bool | choice | url | time
    choices: tuple[str, ...] = ()
    low: int | None = None
    high: int | None = None
    default: str = ""         # что действует, пока значение не задано


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

    Setting("MUSIC_CLOUD_URL", "Облако для музыки",
            "Адрес WebDAV, например http://rclone:8080. Поднимается "
            "командой rclone serve webdav. Пусто — музыка лежит "
            "на устройстве.",
            "Медиа", secret=False),
    Setting("MUSIC_CLOUD_USER", "Облако: логин",
            "Пусто, если rclone слушает без проверки на localhost.",
            "Медиа", secret=False),
    Setting("MUSIC_CLOUD_PASSWORD", "Облако: пароль",
            "Пароль к WebDAV rclone.", "Медиа"),
    Setting("RCLONE_RC_URL", "Управление облаками",
            "Адрес управляющего API rclone, например http://radar_rclone:5572. "
            "С ним облака подключаются из веб-панели, без правки конфига "
            "на сервере. Пусто — раздел «Облако» только показывает состояние.",
            "Медиа", secret=False),
    Setting("RCLONE_RC_USER", "Управление облаками: логин",
            "Тот же, что задан rclone ключом --rc-user.",
            "Медиа", secret=False),
    Setting("RCLONE_RC_PASS", "Управление облаками: пароль",
            "Тот же, что задан rclone ключом --rc-pass.", "Медиа"),

    # --- сеть ---
    Setting("EGRESS_PROXY", "Прокси для выхода в сеть",
            "Например socks5://singbox:1080.", "Сеть", restart=True, secret=False),
    Setting("MEDIA_COOKIES", "Файл cookies",
            "Путь к cookies.txt для закрытых площадок. Проще прислать "
            "файл прямо в чат — команда /cookies.", "Медиа", secret=False),

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

    # --- ВКонтакте как мессенджер (с 5.6) ---
    Setting("VK_BOT_TOKEN", "ВК-бот: ключ сообщества",
            "Управление сообществом → Работа с API → Ключи доступа, "
            "право «сообщения сообщества». Не путать с VK_SERVICE_TOKEN "
            "для чтения стен.", "ВК-бот", restart=True,
            where="Управление сообществом → Работа с API"),
    Setting("VK_BOT_GROUP_ID", "ВК-бот: id сообщества",
            "Числовой id сообщества, например 123456789. В сообществе включите "
            "«Сообщения» и Long Poll API с событием «Входящее сообщение».",
            "ВК-бот", secret=False),

    # --- Discord (с 5.5) ---
    Setting("DISCORD_BOT_TOKEN", "Discord: токен бота",
            "Developer Portal → приложение → Bot → Reset Token.", "Discord",
            restart=True, where="discord.com/developers/applications"),
    Setting("DISCORD_CHANNEL_ID", "Discord: канал сводок",
            "Числовой id канала для суточной сводки и статуса мониторинга "
            "(в Discord: режим разработчика → ПКМ по каналу → Copy ID).",
            "Discord", secret=False),
    Setting("DISCORD_SUMMARY_TIME", "Discord: время сводки",
            "ЧЧ:ММ по времени сервера, по умолчанию 20:00.", "Discord", secret=False),
    Setting("DISCORD_VERIFY_ROLE_ID", "Discord: роль «проверен»",
            "Числовой id роли, которую бот выдаёт после проверки. Роль бота "
            "должна стоять выше неё, а у бота — право управлять ролями. "
            "Остальные каналы откройте только этой роли.",
            "Discord", restart=True, secret=False, kind="int", low=1),
    Setting("DISCORD_VERIFY_MINUTES", "Discord: время на проверку, минут",
            "Не прошедший за это время исключается. 0 — не исключать. "
            "По умолчанию 10. Работает при включённом намерении Server Members.",
            "Discord", secret=False, kind="int", low=0, high=1440, default="10"),
    Setting("DISCORD_MIN_ACCOUNT_DAYS", "Discord: возраст аккаунта, дней",
            "Вступившего с более молодым аккаунтом исключают сразу. 0 — не "
            "проверять (по умолчанию). Нужно намерение Server Members.",
            "Discord", secret=False, kind="int", low=0, high=365, default="0"),
    Setting("DISCORD_LOG_CHANNEL_ID", "Discord: канал журнала проверки",
            "Числовой id канала, куда бот пишет, кого исключил и почему. "
            "Пусто — только в журнал бота.",
            "Discord", secret=False, kind="int", low=1),

    # --- VPN: общее для всех панелей (с 5.0) ---
    Setting("VPN_DAYS", "VPN: срок выдачи, дней",
            "Срок новой записи и шаг продления. По умолчанию 30.",
            "VPN", secret=False),
    Setting("VPN_DEVICES", "VPN: устройств на подписку",
            "Сколько устройств одновременно может пользоваться одной подпиской. "
            "По умолчанию 25, 0 — без предела. Панели без такого предела "
            "(Marzban, PasarGuard, Hiddify, Outline, wg-easy…) его не применяют.",
            "VPN", secret=False),
    Setting("DIGEST_PLANS", "Подписка бота: тарифы",
            "«дни:звёзды» через запятую, например 30:150, 90:400, 365:1400. "
            "Цена — в звёздах Telegram, не меньше одной. Подписка одна: "
            "открывает и подборки, и загрузку видео без предела.",
            "Подписка бота", secret=False),
    Setting("VPN_TRAFFIC_GB", "VPN: предел трафика, ГБ",
            "Для новых записей. Пусто или 0 — без предела.", "VPN", secret=False),

    # --- продажа VPN и оплата (с 5.0.2) ---
    Setting("VPN_PLANS", "VPN: тарифы",
            "«дни:трафикГБ:устройства:цена» через точку с запятой, например "
            "30:0:3:199; 90:0:3:499. Трафик и устройства 0 — без предела.",
            "Продажа VPN", secret=False),
    Setting("VPN_CURRENCY", "VPN: валюта цен",
            "Код валюты, по умолчанию RUB. Crypto Pay пересчитает в криптовалюту сам.",
            "Продажа VPN", secret=False),
    Setting("VPN_PLAN_SLOTS", "VPN: панели для продажи",
            "Номера слотов через запятую, например 1,2. Пусто — все настроенные.",
            "Продажа VPN", secret=False),
    Setting("PAY_PROVIDER", "Оплата: провайдер",
            "manual — оплату подтверждает суперадминистратор кнопкой; "
            "cryptopay — Crypto Pay (@CryptoBot). Пусто — manual.",
            "Продажа VPN", secret=False),
    Setting("PAY_MANUAL_NOTE", "Оплата: как платить (вручную)",
            "Текст для покупателя при ручном подтверждении: куда и как "
            "перевести оплату. Показывается под заказом.",
            "Продажа VPN", secret=False),
    Setting("PAY_CRYPTOPAY_TOKEN", "Crypto Pay: токен",
            "Из @CryptoBot → Crypto Pay → Create App. Комиссию и условия "
            "вывода проверьте там же до включения продаж.",
            "Продажа VPN", where="@CryptoBot → Crypto Pay"),
    Setting("PAY_CRYPTOPAY_TESTNET", "Crypto Pay: тестовая сеть",
            "1 — счета в тестовой сети (@CryptoTestnetBot), деньги ненастоящие.",
            "Продажа VPN", secret=False),
    Setting("PAY_CRYPTOPAY_ASSETS", "Crypto Pay: принимаемые монеты",
            "Через запятую, например USDT,TON. Пусто — все, что разрешит Crypto Pay.",
            "Продажа VPN", secret=False),

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


# --------------------------------------------------------------------------
#  Слоты VPN-панелей (с 5.0.1)
# --------------------------------------------------------------------------
#
# Панелей может быть несколько и разных, поэтому — слоты по образцу своих
# агентов: у каждого своя группа в разделе ключей. Смысловая часть —
# в radar/vpn.py, здесь только имена и подписи.

VPN_SLOTS = 6


def _vpn_settings(slots: int) -> tuple[Setting, ...]:
    built: list[Setting] = []
    for slot in range(1, slots + 1):
        group = f"VPN {slot}"
        prefix = f"VPN{slot}_"
        built.extend((
            Setting(prefix + "KIND", f"VPN {slot}: вид панели",
                    "3xui, xui, sui, marzban, pasarguard, marzneshin, remnawave, "
                    "hiddify, outline или wgeasy. Пусто — слот не используется.",
                    group, secret=False),
            Setting(prefix + "TITLE", f"VPN {slot}: название",
                    "Как панель подписана для людей, например «Нидерланды».",
                    group, secret=False),
            Setting(prefix + "URL", f"VPN {slot}: адрес панели",
                    "Вместе с секретным путём, если он есть. Для Outline — "
                    "apiUrl целиком, для Hiddify — с путём администратора.",
                    group, secret=False),
            Setting(prefix + "TOKEN", f"VPN {slot}: токен",
                    "Токен или ключ API панели. Для Hiddify — uuid "
                    "администратора, для s-ui — токен из «Настройки → API».",
                    group),
            Setting(prefix + "USER", f"VPN {slot}: логин",
                    "Вместо токена — там, где панель это позволяет.",
                    group, secret=False),
            Setting(prefix + "PASS", f"VPN {slot}: пароль",
                    "Вместо токена — там, где панель это позволяет.", group),
            Setting(prefix + "INBOUND", f"VPN {slot}: подключение",
                    "Для 3x-ui и x-ui: номер входящего подключения (inbound).",
                    group, secret=False),
            Setting(prefix + "SUB_URL", f"VPN {slot}: адрес подписки",
                    "Для 3x-ui, x-ui и s-ui — адрес службы подписки, для Hiddify — "
                    "клиентский путь. Остальные панели сообщают ссылку сами.",
                    group, secret=False),
            Setting(prefix + "GROUPS", f"VPN {slot}: группы",
                    "Через запятую: группы PasarGuard, сервисы Marzneshin, отряды "
                    "Remnawave, подключения s-ui или протоколы Marzban.",
                    group, secret=False),
            Setting(prefix + "CERT", f"VPN {slot}: отпечаток сертификата",
                    "SHA-256 сертификата для панели на самоподписанном — "
                    "для Outline обязателен (certSha256).",
                    group, secret=False),
        ))
    return tuple(built)


# Бот показывает первые пять слотов: в переписке длинный список неудобен,
# а пяти сервисов хватает с запасом. Панель заводит агентов без этого
# ограничения — там у неё своя вкладка, и слоты сверх пятого правятся
# в ней. Разделение осознанное: перечень настроек собирается один раз при
# старте, и «показывать всё, что заведено» означало бы либо перечитывать
# .env на каждый показ, либо врать до перезапуска.
SETTINGS = SETTINGS + _agent_settings(AGENT_SLOTS) + _vpn_settings(VPN_SLOTS)

# Настройки, которые раньше правились только в .env (5.9.2.2), и типы прежних.
from . import settingsets  # noqa: E402

SETTINGS = settingsets.refine(SETTINGS + settingsets.build(Setting))

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
    return write_many({key: value})


def write_many(values: dict[str, str]) -> bool:
    """Записывает несколько значений одной правкой .env (5.9.2.1).

    Одна копия `.env` и одна перезапись на всё: слот VPN-панели — десять
    полей, и десять отдельных `write` вытеснили бы из десяти хранимых
    копий все прежние.
    """
    if any("\n" in value or "\r" in value for value in values.values()):
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

        for key, value in values.items():
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
        log.error("Не удалось записать %s в %s: %s", ", ".join(values), ENV_PATH, exc)
        return False

    # Применяем к текущему процессу: провайдеры ИИ читают ключи на лету
    for key, value in values.items():
        known = BY_KEY.get(key)
        if known is not None and known.restart and os.environ.get(key, "") != value:
            PENDING_RESTART.add(key)
        os.environ[key] = value
        log.info("Обновлено значение %s (%d символов)", key, len(value))
    return True


# Значения, изменённые с момента запуска и вступающие в силу после
# перезапуска (5.9.2.2): панель показывает их и предлагает перезапуск.
PENDING_RESTART: set[str] = set()

_TRUE = ("1", "true", "yes", "on", "да")
_FALSE = ("0", "false", "no", "off", "нет")


def normalize_value(setting: "Setting", value: str) -> str:
    """Приводит введённое к хранимому виду: флаг — 1/0, выбор — как в списке."""
    text = (value or "").strip()
    if not text:
        return ""
    if setting.kind == "bool":
        if text.lower() in _TRUE:
            return "1"
        if text.lower() in _FALSE:
            return "0"
    if setting.kind == "choice":
        for option in setting.choices:
            if option.lower() == text.lower():
                return option
    if setting.kind == "time":
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"
    return text


def check_value(setting: "Setting", value: str) -> str:
    """Причина отказа по-человечески или пустая строка (5.9.2.2).

    Пустое значение допустимо всегда: оно возвращает настройку к значению
    по умолчанию. Опечатка в числе или адресе иначе обнаруживалась бы
    только по странному поведению бота после перезапуска.
    """
    text = normalize_value(setting, value)
    if not text:
        return ""
    kind = setting.kind
    if kind == "int":
        if not re.fullmatch(r"\d{1,12}", text):
            return "Нужно целое неотрицательное число."
        number = int(text)
        if setting.low is not None and number < setting.low:
            return f"Не меньше {setting.low}."
        if setting.high is not None and number > setting.high:
            return f"Не больше {setting.high}."
    elif kind == "bool":
        if text not in ("0", "1"):
            return "Нужно 1 (включено) или 0 (выключено)."
    elif kind == "choice":
        if text not in setting.choices:
            return "Допустимо: " + ", ".join(setting.choices) + "."
    elif kind == "url":
        from urllib.parse import urlparse

        try:
            parsed = urlparse(text)
        except ValueError:
            return "Адрес указан неверно."
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return "Адрес должен начинаться с http:// или https://."
    elif kind == "time":
        match = re.fullmatch(r"(\d{2}):(\d{2})", text)
        if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
            return "Время — ЧЧ:ММ, например 20:00."
    return ""


def validate_extra(key: str, value: str) -> str:
    """Проверка значения до записи: опечатка в тарифах молча ломала бы продажу.

    Общая для панели и консоли (5.9.3.1): две проверки разошлись бы
    на первом же новом ключе.
    """
    if not value:
        return ""
    if key == "DIGEST_PLANS":
        if not re.fullmatch(r"\s*\d+:\d+\s*(,\s*\d+:\d+\s*)*", value):
            return "Формат: 30:150, 90:400 — дни и звёзды через двоеточие."
        for chunk in value.split(","):
            days, _, stars = chunk.strip().partition(":")
            if int(days) < 1 or int(stars) < 1:
                return "Срок и цена — не меньше единицы (звезда — минимальная цена)."
    elif key == "VPN_PLANS":
        from . import vpnsales

        chunks = [c for c in value.split(";") if c.strip()]
        if not chunks or len(vpnsales.parse_plans(value)) != len(chunks):
            return ("Формат: дни:трафикГБ:устройства:цена через «;», например "
                    "30:0:3:199; 90:0:3:499 — есть негодный тариф.")
    elif key in ("VPN_DAYS", "VPN_TRAFFIC_GB", "VPN_DEVICES"):
        if not value.isdigit():
            return "Нужно целое число."
        if key == "VPN_DAYS" and int(value) < 1:
            return "Срок — не меньше одного дня."
    return ""


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
