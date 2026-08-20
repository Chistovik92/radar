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
         group="Источники", since="4.3", default=False),
    Flag("source_ok", "Источники Одноклассники",
         "Ленты групп через API OK. Требует регистрации приложения на apiok.ru.",
         group="Источники", since="4.1", default=False),

    # --- подача ---
    Flag("all_clear", "Отбой опасности", "Отдельное сообщение при снятии угрозы.",
         group="Подача", since="3.3.5"),
    Flag("whitelist_notice", "Примечание о «белых списках»",
         "Пояснение об ограничениях мобильного интернета.", group="Подача", since="3.3"),
    Flag("weather_image", "Погода картинкой",
         "Разрешает отрисованную сводку. Каждый выбирает вид сам "
         "в настройках. Требует Pillow и шрифтов; без них автоматически "
         "используется текст.",
         group="Подача", since="4.4", default=False),
    Flag("weather_image_all", "Погода картинкой всем",
         "Картинка для всех, без личного выбора. Нужен включённый "
         "«Погода картинкой». Осторожно: при слабом мобильном интернете "
         "картинка может не прогрузиться там, где текст дошёл бы.",
         group="Подача", since="4.6", default=False),
    Flag("quiet_hours", "Тихие часы",
         "Несрочное придерживается до утра. Военные угрозы и МЧС проходят всегда.",
         group="Подача", since="4.4", default=False),
    Flag("antispam", "Антиспам оповещений",
         "Не повторять одно событие для той же локации.",
         group="Подача", since="4.4"),

    # --- новостные подборки ---
    Flag("digest", "Новостные подборки",
         "Утренняя и вечерняя сводка по выбранным тематикам, одно сообщение.",
         group="Новости", since="4.4", default=False),
    Flag("digest_summaries", "Пересказы подборок",
         "ИИ сжимает новости тематики в связную сводку — один запрос "
         "на тематику. Без него подборка выходит списком.",
         group="Подборки", since="4.6.1", default=False),
    Flag("link_shortener", "Сокращение ссылок",
         "Короткие ссылки на источники в подборках. Нужен адрес "
         "SHORT_BASE_URL. Заводить ссылки может только суперадминистратор.",
         group="Подборки", since="4.6.1", default=False),
    Flag("digest_paid", "Платная подписка на подборки",
         "Оплата через Telegram Stars. Цены задаёт суперадминистратор.",
         group="Новости", since="4.4", default=False),
    Flag("digest_suggestions", "Предложение источников новостей",
         "Пользователи предлагают каналы и ленты по тематикам.",
         group="Новости", since="4.4", default=False),

    # --- экстренная помощь ---
    Flag("sos", "Кнопка SOS",
         "Отправка геопозиции экстренному контакту по нажатию кнопки.",
         group="Экстренное", since="4.1", default=False),

    # --- медиа ---
    Flag("media_download", "Загрузка видео по ссылке",
         "Скачивание роликов с внешних площадок с выбором качества. "
         "Требует yt-dlp и ffmpeg в образе.",
         group="Медиа", since="4.2", default=False),

    # --- данные ---
    Flag("history", "История событий", "Журнал того, что приходило по адресу.",
         group="Данные", since="4.0"),
    Flag("source_export", "Выгрузка источников", "Скачивание и загрузка списка файлом.",
         group="Данные", since="3.3"),

    # --- инфраструктура ---
    Flag("egress_proxy", "Выход в сеть через внешний узел",
         "Исходящий трафик бота идёт через SOCKS5 от sing-box. "
         "Ключ добавляется в боте, сервер выбирается вручную.",
         group="Инфраструктура", since="4.3", default=False),
    Flag("provider_switch", "Смена провайдера ИИ",
         "Переключение между Gemini и DeepSeek на лету, с проверкой баланса.",
         group="Ядро", since="4.3"),
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
    Flag("promo_codes", "Промокоды",
         "Выдача промокодов партнёрских проектов: один код на человека "
         "на проект, повтор возвращает прежний. Режим и условия задаются "
         "в разделе управления.",
         group="Партнёры", since="4.7", default=False),

    # --- администрирование ---
    Flag("web_panel", "Веб-панель",
         "Панель администратора в браузере, вход через Telegram Login. "
         "Отдельный процесс: её сбой не влияет на бота.",
         group="Администрирование", since="4.5", default=False),
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
