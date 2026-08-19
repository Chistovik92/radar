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


# --------------------------------------------------------------------------
#  Тематические источники (с 4.6.1)
# --------------------------------------------------------------------------
#
# Городские каналы про игры, науку или спорт не пишут — эти тематики
# кормятся отдельными лентами. Наборы общие для всех городов и включаются
# по тематикам, на которые подписан человек, а не по его местоположению.
#
# Подключаются только те наборы, чьи тематики кому-то нужны: опрашивать
# ленту про кино, когда на неё никто не подписан, — впустую тратить
# запросы на слабом сервере.

@dataclass
class ThematicPreset:
    """Источники одной тематики подборок."""

    topic: str                                   # ключ из digest.TOPICS
    title: str
    channels: list[str] = field(default_factory=list)
    rss: list[str] = field(default_factory=list)
    vk: list[str] = field(default_factory=list)
    note: str = ""


THEMATIC: tuple[ThematicPreset, ...] = (
    ThematicPreset(
        topic="it",
        title="IT и игры",
        channels=["ixbtgames", "ixbtnocomments", "makarenkoff_games"],
        rss=[
            "https://www.ixbt.com/export/news.rss",
            "https://3dnews.ru/news/rss/",
            "https://habr.com/ru/rss/news/?fl=ru",
        ],
        vk=["makarenkoff_games"],
        note="Каналы ixbt дают и игры, и железо; makarenkoff_games "
             "продублирован в VK — заодно проверка источника ВКонтакте.",
    ),
    ThematicPreset(
        topic="science",
        title="Наука и техника",
        rss=[
            "https://nplus1.ru/rss",
            "https://naked-science.ru/feed",
        ],
    ),
    ThematicPreset(
        topic="sport",
        title="Спорт",
        rss=[
            "https://www.sports.ru/rss/all_news.xml",
            "https://matchtv.ru/rss",
        ],
    ),
    ThematicPreset(
        topic="hobby",
        title="Хобби и авто",
        rss=[
            "https://www.drive2.ru/export/rss/",
            "https://motor.ru/exports/rss.xml",
        ],
    ),
    ThematicPreset(
        topic="cinema",
        title="Кино и сериалы",
        rss=[
            "https://www.kinopoisk.ru/media/rss/",
            "https://dtf.ru/rss/all",
        ],
    ),
    ThematicPreset(
        topic="finance",
        title="Деньги и рынки",
        rss=[
            "https://www.rbc.ru/v10/ajax/rss/feed/economics",
            "https://quote.rbc.ru/v10/ajax/rss/feed",
        ],
    ),
)

BY_TOPIC = {preset.topic: preset for preset in THEMATIC}


def thematic_for(topics: list[str]) -> ThematicPreset | None:
    """Набор для одной тематики. None, если тематика городская."""
    for key in topics:
        preset = BY_TOPIC.get(key)
        if preset:
            return preset
    return None


def thematic_sources(topics: set[str]) -> tuple[list[str], list[str], list[str]]:
    """Каналы, ленты и группы VK для набора тематик.

    Возвращает только то, что нужно перечисленным тематикам: опрос лент,
    на которые никто не подписан, — лишняя нагрузка без адресата.
    """
    channels: list[str] = []
    feeds: list[str] = []
    groups: list[str] = []
    for key in topics:
        preset = BY_TOPIC.get(key)
        if not preset:
            continue
        channels.extend(preset.channels)
        feeds.extend(preset.rss)
        groups.extend(preset.vk)
    return (
        list(dict.fromkeys(channels)),
        list(dict.fromkeys(feeds)),
        list(dict.fromkeys(groups)),
    )
