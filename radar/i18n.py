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

    # --- медиа ---
    "media.title": "🎬 Video download",
    "media.prompt": "Send a link — I will offer quality options and send the file.",
    "media.limit": "Sending limit",
    "media.quota.left": "Downloads left today",
    "media.quota.spent": "Daily limit reached",
    "media.quota.unlimited": "Unlimited until",
    "media.quota.buy": "⭐️ Unlimited for a month",
    "media.too_big": "The file is larger than the limit.",

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
