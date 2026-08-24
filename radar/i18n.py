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
    "weather.hour_suffix": "h",
    "weather.error.no_coords": "no coordinates — send your location again",
    "weather.error.bad_status": "the weather service returned code",
    "weather.error.fetch_failed": "failed to get the weather",
    "weather.error.no_data": "no weather data",

    # --- погода: описания кодов WMO ---
    "weather.wmo.0": "clear sky",
    "weather.wmo.1": "mostly clear",
    "weather.wmo.2": "partly cloudy",
    "weather.wmo.3": "overcast",
    "weather.wmo.45": "fog",
    "weather.wmo.48": "depositing rime fog",
    "weather.wmo.51": "light drizzle",
    "weather.wmo.53": "drizzle",
    "weather.wmo.55": "dense drizzle",
    "weather.wmo.56": "light freezing drizzle",
    "weather.wmo.57": "dense freezing drizzle",
    "weather.wmo.61": "slight rain",
    "weather.wmo.63": "rain",
    "weather.wmo.65": "heavy rain",
    "weather.wmo.66": "light freezing rain",
    "weather.wmo.67": "heavy freezing rain",
    "weather.wmo.71": "slight snow",
    "weather.wmo.73": "snow",
    "weather.wmo.75": "heavy snow",
    "weather.wmo.77": "snow grains",
    "weather.wmo.80": "slight rain showers",
    "weather.wmo.81": "rain showers",
    "weather.wmo.82": "violent rain showers",
    "weather.wmo.85": "slight snow showers",
    "weather.wmo.86": "heavy snow showers",
    "weather.wmo.95": "thunderstorm",
    "weather.wmo.96": "thunderstorm with slight hail",
    "weather.wmo.99": "thunderstorm with heavy hail",

    # --- погода картинкой ---
    "weather.image.title": "Weather",
    "weather.image.feels_like": "feels like",
    "weather.image.gusts_to": "gusts up to",
    "weather.image.humidity": "humidity",
    "weather.image.mmhg": "mmHg",
    "weather.image.ms": "m/s",
    "weather.image.now": "now",
    "weather.sky.night": "night",
    "weather.sky.dawn": "dawn",
    "weather.sky.day": "day",
    "weather.sky.dusk": "dusk",

    # --- роза ветров ---
    "wind.n": "northerly",
    "wind.ne": "north-easterly",
    "wind.e": "easterly",
    "wind.se": "south-easterly",
    "wind.s": "southerly",
    "wind.sw": "south-westerly",
    "wind.w": "westerly",
    "wind.nw": "north-westerly",

    # --- сила ветра ---
    "wind.calm": "calm",
    "wind.light": "light",
    "wind.moderate": "moderate",
    "wind.fresh": "fresh",
    "wind.strong": "strong",
    "wind.storm": "stormy",

    # --- фазы луны ---
    "moon.new": "new moon",
    "moon.waxing_crescent": "waxing crescent",
    "moon.first_quarter": "first quarter",
    "moon.waxing_gibbous": "waxing gibbous",
    "moon.full": "full moon",
    "moon.waning_gibbous": "waning gibbous",
    "moon.last_quarter": "last quarter",
    "moon.waning_crescent": "waning crescent",

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
    "common.insufficient_rights": "Insufficient permissions.",

    # --- справка (/help) ---
    "help.title": "How it works",
    "help.step1": (
        "1. Send your location (paperclip → Location) — this adds a location. "
        "You can add as many as you like."
    ),
    "help.step2": (
        "2. Military threats (drones, missile danger) arrive as one citywide "
        "message covering all your locations in it."
    ),
    "help.step3": "3. Utility outages are searched by address — street and house number.",
    "help.step4": "4. Locations closer than 1 km to each other are merged into one summary.",
    "help.commands_title": "Commands",
    "help.cmd_basic": "/menu — menu - /id — your ID and role - /cancel — reset input",
    "help.cmd_partner": "/partner — partner project",
    "help.cmd_assistant": "/ai &lt;question&gt; — AI assistant - /aireset — clear context",
    "help.cmd_quota": "/quota — Gemini quota usage",
    "help.cmd_admin1": "/stats — system statistics - /models — Gemini models",
    "help.cmd_admin2": "/digest — news digests - /sos — SOS button",
    "help.cmd_admin3": "/media — download video by link - /panel — web panel",
    "help.cmd_super1": (
        "/features — system features\n"
        "/logs — logs - /logtail — recent lines - /logclear — clear"
    ),
    "help.cmd_super2": "/perf — cycle time and resources - /bench — AI provider comparison",
    "help.cmd_super3": (
        "/keys — keys and settings - /provider — choose provider\n"
        "/network — network and proxy - /backup — backup"
    ),

    # --- приветствие и общие подписи ---
    "app.title": "Radar",
    "greeting.assistant": (
        "🧠 <i>The AI assistant is active: write a question in the chat "
        "or use /ai.</i>"
    ),
    "greeting.no_key": (
        "⚠️ <i>GEMINI_API_KEY is not set — heuristic analysis is running "
        "without AI.</i>"
    ),
    "restart.missed": (
        "🛠 <b>The bot was down for maintenance</b>\n\n"
        "Your message arrived while it was restarting and was not processed "
        "— please send it again.\n\n"
        "<i>Danger alerts were not lost: the bot re-reads its sources after "
        "every restart.</i>"
    ),
    "common.your_id": "🆔 Your ID",
    "common.role": "Role",
    "common.pinned_buttons": (
        "The <b>Menu</b> and <b>HydraSite</b> buttons are pinned below the "
        "input field."
    ),

    # --- роли ---
    "role.user": "👤 User",
    "role.moderator": "🛡 Moderator",
    "role.admin": "👑 Administrator",
    "role.superadmin": "⭐️ Superadministrator",

    # --- категории оповещений ---
    "category.bpla": "Drones / missile danger",
    "category.mchs": "Emergency service alerts",
    "category.jkh": "Utilities and network failures",
    "category.whitelist": "Warn about allow-lists",

    # --- настройки: погода ---
    "settings.weather_button": "🌤 Weather",
    "settings.weather_mode.title": "⏱ <b>Weather mode</b>",
    "settings.weather_mode.prompt": "Choose an interval or set your own value.",
    "settings.weather.off": "off",
    "settings.weather.every": "every",
    "settings.weather.at": "at",
    "settings.weather.minutes": "min",
    "settings.weather.hours_short": "h",
    "settings.weather.hour": "hourly",
    "settings.weather.hours3": "every 3 hours",
    "settings.weather.hours6": "every 6 hours",
    "settings.weather.disable": "Turn off",
    "settings.weather.own_interval": "Own interval",
    "settings.weather.fixed_time": "At a fixed time",
    "settings.weather.disabled": "Weather turned off",
    "settings.weather.interval_set": "Interval",
    "settings.weather.ask_time": (
        "⏰ Enter the time in <code>HH:MM</code> format (for example, 08:30):"
    ),
    "settings.weather.ask_interval": (
        "⏱ Enter an interval: <code>45</code> (minutes) or <code>2h</code> (hours):"
    ),
    "settings.weather.bad_time": (
        "❌ Wrong format. Example: <code>08:30</code>. /cancel to abort."
    ),
    "settings.weather.bad_interval": (
        "❌ Enter a number of minutes, or something like <code>2h</code>."
    ),
    "settings.weather.range": "❌ The interval must be between 15 minutes and 24 hours.",
    "settings.weather.daily_at": "✅ Weather will arrive daily at",
    "settings.weather.interval_ok": "✅ Interval",

    # --- настройки: вид погоды ---
    "settings.wformat.title": "🖼 <b>Weather summary format</b>",
    "settings.wformat.now": "Currently",
    "settings.wformat.text": "text",
    "settings.wformat.image": "image",
    "settings.wformat.image_all": "image (for everyone)",
    "settings.wformat.as_text": "📄 As text",
    "settings.wformat.as_image": "🖼 As an image",
    "settings.wformat.forced": (
        "Personal choice is temporarily unavailable. When the administration "
        "lifts the global setting, your previous choice comes back."
    ),
    "settings.wformat.why": (
        "An image is clearer, but it will not load under mobile-internet "
        "restrictions — which is exactly the situation this system exists "
        "for. Text always gets through."
    ),
    "settings.wformat.off": "Weather as an image is turned off.",
    "settings.wformat.label": "🖼 Weather format",

    # --- настройки: тихие часы ---
    "settings.quiet.title": "🌙 <b>Quiet hours</b>",
    "settings.quiet.label": "🌙 Quiet hours",
    "settings.quiet.prompt": (
        "Send an interval, for example <code>23:00-07:00</code>.\n"
        "A \"-\" turns quiet hours off."
    ),
    "settings.quiet.always": (
        "<b>Military threats and emergency alerts always get through</b> — "
        "only utilities and weather are held back."
    ),
    "settings.quiet.bad_format": (
        "❌ Format: <code>23:00-07:00</code>. A \"-\" turns it off. /cancel to abort."
    ),
    "settings.quiet.cleared": "✅ Quiet hours turned off.",
    "settings.quiet.set": "✅ Quiet hours",
    "settings.quiet.note": (
        "<i>Military threats and emergency alerts will arrive at any time.</i>"
    ),
    "settings.quiet.disabled": "Quiet hours are turned off.",
    "settings.quiet.none": "off",

    # --- предложение источника ---
    "suggest.title": "📢 <b>Suggest a source</b>",
    "suggest.prompt": (
        "Send the username of a public channel, for example "
        "<code>saratovzhkh</code>, or a link to it."
    ),
    "suggest.thematic": (
        "<i>Topic channels work too — gaming, sport, science: they go into "
        "the news digests.</i>"
    ),
    "suggest.closed": (
        "Suggestions are closed at the moment — the source list is curated "
        "by the administration."
    ),
    "suggest.sent": "✅ Channel @{channel} has been sent to the moderators.",
    "suggest.already": "ℹ️ The source is already in the list or in the queue.",
    "suggest.bad": "❌ Invalid channel username.",

    # --- общее (продолжение) ---
    "common.on": "Enabled",
    "common.off": "Disabled",
    "common.user_not_found": "User not found.",
    "common.cancel": "Cancel",
    "common.back": "◀️ Back",

    # --- раздел «Управление» ---
    "manage.sources": "📡 Sources",
    "manage.users": "👥 Users",
    "manage.stats": "📊 Statistics",
    "manage.features": "⚙️ Features",
    "manage.keys": "🔑 Access keys",
    "manage.ai": "🧠 AI management",
    "manage.backups": "💾 Backups",
    "manage.network": "🌐 Network access",
    "manage.logs": "📋 Logs",
    "manage.panel": "🖥 Web panel",
    "manage.role_line": "Your role",
    "manage.all_sections": "All sections are available, including access keys and logs.",
    "manage.admin_sections": "Sources, users, statistics and invites are available.",
    "manage.mod_sections": "Sources and user settings editing are available.",
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
