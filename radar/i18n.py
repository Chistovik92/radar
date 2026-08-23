"""Язык интерфейса бота.

Русский по умолчанию, английский по выбору. Выбор хранится у пользователя
и спрашивается один раз: при первом запуске у новых, при первом обращении
после обновления — у тех, кто пользовался ботом раньше.

Как это устроено и почему именно так:

* строки лежат в одном словаре, а не рядом с кодом. Тексты были разбросаны
  по модулям, и перевод «по месту» гарантированно оставил бы половину
  интерфейса на русском — незаметно, потому что каждый отдельный экран
  выглядел бы переведённым;
* отсутствующий перевод возвращает русский вариант, а не ключ и не пустоту.
  Английский появляется постепенно, и человек в худшем случае увидит
  русскую строку среди английских — это неприятно, но понятно, в отличие
  от `menu.title.short` посреди сообщения;
* сообщения об опасности переводятся в первую очередь: если система
  умеет говорить по-английски, то начинать надо с того, ради чего она
  существует, а не с настроек.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("radar.i18n")

RU = "ru"
EN = "en"
LANGUAGES = (RU, EN)
DEFAULT = RU

TITLES = {RU: "🇷🇺 Русский", EN: "🇬🇧 English"}

# Словарь. Ключ — короткое имя строки, значение — перевод на английский.
# Русский текст живёт в самих вызовах как запасной вариант: так его видно
# при чтении кода, и ни одна строка не может «потеряться» без перевода.
EN_STRINGS: dict[str, str] = {
    # --- выбор языка ---
    "lang.ask": "Choose your language / Выберите язык",
    "lang.saved": "Language set to English.",
    "lang.button": "🌍 Language",

    # --- главное меню ---
    "menu.locations": "📍 My locations",
    "menu.weather": "🌤 Weather",
    "menu.alerts": "⚙️ Notifications",
    "menu.suggest": "📢 Suggest a source",
    "menu.invite": "🔗 Invite",
    "menu.digest": "📰 News digests",
    "menu.sos": "🆘 SOS",
    "menu.assistant": "🧠 AI assistant",
    "menu.manage": "🛠 Management",
    "menu.about": "ℹ️ About",
    "menu.history": "📖 History",
    "menu.media": "🎬 Download video",
    "menu.partners": "🤝 Partner projects",
    "menu.home": "🏠 Main menu",
    "menu.back": "◀️ Back",

    # --- оповещения: самое важное ---
    "alert.danger": "DANGER",
    "alert.utility": "Utilities and outages",
    "alert.all_clear": "All clear",
    "alert.matched": "Matched locations",
    "alert.citywide": "citywide",
    "alert.whitelist.title": "Mobile internet",
    "alert.whitelist.body": (
        "During an air threat operators switch to allow-lists: only "
        "government services, banks, maps and taxi keep working. "
        "Messengers and social networks may not open. Home wired internet "
        "and Wi-Fi usually keep working. For urgent contact use calls and SMS."
    ),
    "alert.not_official": "This system does not replace official warning channels.",
    "alert.read_source": "Read the source",
    "alert.no_ai": "(no AI)",

    # --- партнёрские проекты ---
    "partners.empty": "The list is empty for now.",
    "partners.promo": "🎁 Get a promo code",
    "partners.promo.issued": "Issued",
    "partners.promo.kept": "The code is yours: pressing again shows the same one.",

    # --- медиа ---
    "media.title": "🎬 Video download",
    "media.prompt": "Send a link — I will offer quality options and send the file.",
    "media.limit": "Sending limit",
    "media.quota.left": "Downloads left today",
    "media.quota.spent": "Daily limit reached",
    "media.quota.unlimited": "Unlimited until",
    "media.quota.buy": "⭐️ Unlimited for a month",
    "media.too_big": "The file is larger than the limit.",

    # --- подборки ---
    "digest.title": "News digests",
    "digest.buy": "⭐️ Subscribe",
    "digest.sources": "Sources",

    "digest.staff": "🛠 <b>Staff access</b> — all topics are open, no payment.",
    "digest.extra_days": "Paid days on top of that",
    "digest.paid": "Subscription active, days left",
    "digest.covers_media": "It also lifts the daily video download limit.",
    "digest.free": "Topics available for free",
    "digest.upsell": "A subscription opens all of them.",
    "digest.topics": "Your topics",
    "digest.no_topics": "No topics selected — the digest will not arrive.",
    "digest.times": "Delivery time",
    "digest.free_always": (
        "Danger alerts, utilities, weather and SOS stay free at all times "
        "and do not depend on the subscription."
    ),

    # --- названия тематик ---
    "topic.city": "City and government",
    "topic.incidents": "Incidents",
    "topic.utilities": "Utilities and infrastructure",
    "topic.transport": "Transport",
    "topic.health": "Health",
    "topic.education": "Education",
    "topic.social": "Social",
    "topic.economy": "Economy and business",
    "topic.culture": "Culture and leisure",
    "topic.weather_nature": "Weather and nature",
    "topic.region": "Region",
    "topic.federal": "National",
    "topic.it": "IT and games",
    "topic.science": "Science and tech",
    "topic.sport": "Sport",
    "topic.hobby": "Hobbies and cars",
    "topic.cinema": "Films and series",
    "topic.finance": "Money and markets",

    # --- погода ---
    "weather.feels": "feels like",
    "weather.wind": "wind",
    "weather.humidity": "humidity",
    "weather.sunrise": "sunrise",
    "weather.sunset": "sunset",
    "weather.now": "now",
    "weather.today": "today",
    "weather.tomorrow": "tomorrow",

    # --- SOS ---
    "sos.overview": "🆘 Emergency help",
    "sos.no_contacts": (
        "No trusted contacts yet. Add someone who will receive your location "
        "if you press the SOS button."
    ),
    "sos.contacts": "Trusted contacts",
    "sos.ready": "ready to receive the signal",
    "sos.pending": "not confirmed — has not opened the bot",
    "sos.none_confirmed": (
        "⚠️ No contact is confirmed. Telegram does not let a bot write first — "
        "the contact must open the bot via your link. Until then the signal "
        "goes to the system administrators."
    ),
    "sos.add": "➕ Add a contact",
    "sos.fire": "🆘 Send the signal",
    "sos.title": "🆘 SOS",
    "sos.send": "🆘 Send an alert",
    "sos.stop": "✅ Cancel the alert",
    "sos.sent": "Alert sent to your contacts.",

    # --- журнал ---
    "history.title": "📖 History",
    "history.empty": "Nothing was sent to you in the last 30 days.",
    "history.note": (
        "That does not mean the bot was idle: it means nothing happened "
        "near your locations."
    ),
    "history.trimmed": "Showing the most recent entries.",

    # --- настройки ---
    "settings.title": "⚙️ Notifications",
    "settings.prompt": "Choose which events to receive and the weather mode.",
    "settings.quiet": "Quiet hours",
    "settings.weather_mode": "Weather mode",
    "settings.weather_view": "Weather view",

    # --- общее ---
    "common.cancelled": "✅ Cancelled.",
    "common.only_superadmin": "⛔️ Superadministrator only.",
    "common.error": "Something went wrong — try again later.",
}


def normalize(value: Any) -> str:
    """Приводит что угодно к коду языка. Неизвестное — русский."""
    code = str(value or "").strip().lower()[:2]
    return code if code in LANGUAGES else DEFAULT


def language_of(user: dict[str, Any] | None) -> str:
    return normalize((user or {}).get("lang"))


def needs_choice(user: dict[str, Any] | None) -> bool:
    """Спрашивали ли уже про язык.

    Пустое поле означает «не спрашивали»: и у нового человека, и у того,
    кто пользовался ботом до появления выбора. Различать их незачем —
    вопрос одинаковый.
    """
    return not (user or {}).get("lang")


def t(key: str, lang: str, fallback: str) -> str:
    """Строка на нужном языке.

    fallback — русский текст, он же значение по умолчанию. Если перевода
    нет, вернётся он: русская строка среди английских понятнее, чем
    служебный ключ.
    """
    if normalize(lang) == EN:
        return EN_STRINGS.get(key, fallback)
    return fallback


# --------------------------------------------------------------------------
#  Перевод пользовательского содержимого (с 4.7.3.2)
# --------------------------------------------------------------------------
#
# Описания партнёрских проектов, условия промокодов, тексты оповещений
# из городских каналов — всё это пишут люди по-русски, и в словарь их
# не положить: они меняются без пересборки.
#
# Такие тексты переводит модель, по запросу и с кэшем. Решения, которые
# здесь важны:
#
#   * кэш обязателен. Без него каждое открытие раздела стоило бы запроса
#     к модели, а описания меняются раз в месяц — платить за это квотой,
#     которая нужна оповещениям об опасности, нельзя;
#   * при недоступности модели возвращается исходный текст, а не заглушка
#     и не пустота: русское описание английскому читателю понятнее, чем
#     «перевод недоступен»;
#   * оповещения об опасности НЕ переводятся на лету. Они срочные, а
#     обращение к модели добавляет секунды и может не вернуться вовсе.
#     Для них переводится каркас — заголовки и пояснения из словаря выше, —
#     а текст первоисточника идёт как есть. Лучше понятная наполовину
#     тревога сейчас, чем полностью переведённая через минуту.

_CACHE: dict[tuple[str, str], str] = {}
_CACHE_LIMIT = 500

TRANSLATE_SYSTEM = (
    "You are a translator. Translate the given text to {target}. "
    "Keep the meaning exactly, keep any HTML tags and links unchanged, "
    "keep the tone. Return only the translation, nothing else."
)


def cache_key(text: str, lang: str) -> tuple[str, str]:
    return (text.strip()[:400], normalize(lang))


async def translate(text: str, lang: str) -> str:
    """Перевести текст, написанный человеком. Ошибка — вернуть как есть."""
    text = (text or "").strip()
    lang = normalize(lang)
    if not text or lang == DEFAULT:
        return text

    key = cache_key(text, lang)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    from . import ai

    if not getattr(ai, "ENABLED", False):
        return text

    try:
        result = (await ai.generate(
            text[:1500],
            system=TRANSLATE_SYSTEM.format(target="English"),
            max_tokens=600,
            temperature=0.2,
            role=ai.ANALYSIS,
            priority=False,        # перевод уступает квоту оповещениям
        )).strip()
    except Exception as exc:  # noqa: BLE001
        log.info("Перевод не удался, отдаю исходный текст: %s", exc)
        return text

    if not result:
        return text

    if len(_CACHE) >= _CACHE_LIMIT:
        # Простое усечение вместо LRU: записей мало, обращения редкие,
        # и сложный вытеснитель здесь дороже пользы.
        _CACHE.clear()
    _CACHE[key] = result
    return result


def forget_translations() -> None:
    """Сбросить кэш — после правки описаний и в тестах."""
    _CACHE.clear()
