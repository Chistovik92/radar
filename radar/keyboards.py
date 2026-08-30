"""Инлайн-клавиатуры. Формат callback_data: «раздел:действие:аргумент»."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from typing import Any, Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from . import config, features, i18n, roles, timezones
from .matching import CATEGORY_ICONS, CATEGORY_TITLES

def main_menu(role: str | None, user: dict | None = None) -> InlineKeyboardMarkup:
    """Главное меню.

    Собрано по назначению, а не по ролям: сначала то, чем пользуются каждый
    день, ниже — разделы управления. Каждый служебный раздел свёрнут в одну
    кнопку, иначе у суперадминистратора меню разрасталось до полутора
    десятков строк и переставало читаться.
    """
    # Язык берётся из записи пользователя. Раньше меню собиралось без него,
    # и при английском интерфейсе кнопки оставались русскими — интерфейс
    # выглядел переведённым наполовину, что хуже, чем не переведённым вовсе.
    lang = i18n.language_of(user)

    def label(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    rows = [
        [
            InlineKeyboardButton(text=label("menu.locations", "📍 Мои локации"),
                                 callback_data="loc:list"),
            InlineKeyboardButton(text=label("menu.weather", "🌤 Погода"),
                                 callback_data="loc:weather"),
        ],
        [
            InlineKeyboardButton(text=label("menu.alerts", "⚙️ Оповещения"),
                                 callback_data="menu:settings"),
            InlineKeyboardButton(text=label("menu.suggest", "📢 Предложить источник"),
                                 callback_data="src:suggest"),
        ],
        [InlineKeyboardButton(text=label("menu.invite", "🔗 Пригласить"),
                              callback_data="usr:invite")],
    ]

    if features.enabled("digest"):
        rows.append([InlineKeyboardButton(
            text=label("menu.digest", "📰 Новостные подборки"),
            callback_data="dig:menu")])
    if features.enabled("sos"):
        rows.append([InlineKeyboardButton(text=label("menu.sos", "🆘 SOS"),
                                          callback_data="sos:menu")])

    # Журнал и загрузка видео жили без входа: журнал не вызывался ниоткуда,
    # видео открывалось только командой /media, о которой надо было знать.
    extra = []
    if features.enabled("history"):
        extra.append(InlineKeyboardButton(text=label("menu.history", "📖 Журнал"),
                                          callback_data="menu:history"))
    if features.enabled("media_download"):
        extra.append(InlineKeyboardButton(text=label("menu.media", "🎬 Скачать видео"),
                                          callback_data="med:menu"))
    if extra:
        rows.append(extra)

    if roles.can_use_assistant(role):
        rows.append([InlineKeyboardButton(text=label("menu.assistant", "🧠 ИИ-ассистент"),
                                          callback_data="menu:ai")])

    # Один вход в управление вместо россыпи кнопок
    if roles.is_moderator(role):
        rows.append([InlineKeyboardButton(text=label("menu.manage", "🛠 Управление"),
                                          callback_data="menu:manage")])

    rows.append([
        InlineKeyboardButton(text=label("menu.about", "ℹ️ О системе"),
                             callback_data="menu:about"),
        InlineKeyboardButton(text=label("lang.button", "🌍 Язык"),
                             callback_data="menu:lang"),
    ])

    promo = promo_row()
    if promo:
        rows.append(promo)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manage_menu(role: str | None, user: dict | None = None) -> InlineKeyboardMarkup:
    """Раздел управления: содержимое зависит от роли."""
    lang = i18n.language_of(user)

    def label(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    rows: list[list[InlineKeyboardButton]] = []

    if roles.is_moderator(role):
        rows.append([
            InlineKeyboardButton(text=label("manage.sources", "📡 Источники"),
                                 callback_data="menu:mod"),
            InlineKeyboardButton(text=label("manage.users", "👥 Пользователи"),
                                 callback_data="usr:list:0"),
        ])

    if roles.is_admin(role):
        rows.append([
            InlineKeyboardButton(text=label("manage.stats", "📊 Статистика"),
                                 callback_data="menu:stats")
        ])

    if roles.is_superadmin(role):
        rows.append([
            InlineKeyboardButton(text=label("manage.features", "⚙️ Возможности"),
                                 callback_data="feat:list"),
            InlineKeyboardButton(text=label("manage.keys", "🔑 Ключи доступа"),
                                 callback_data="key:list"),
        ])
        # Всё, что касается ИИ, — за одним входом: раньше проверка провайдеров
        # открывалась и отсюда, и из раздела ключей.
        rows.append([
            InlineKeyboardButton(text=label("manage.ai", "🧠 Управление ИИ"),
                                 callback_data="ai:menu")
        ])
        # Выход в сеть — за своим флагом: раздел меняет маршрут всего
        # трафика, и когда он не нужен, кнопке в меню не место.
        network_row = [InlineKeyboardButton(text=label("manage.backups", "💾 Копии"),
                                            callback_data="bak:menu")]
        if features.enabled("egress_proxy"):
            network_row.insert(0, InlineKeyboardButton(
                text=label("manage.network", "🌐 Выход в сеть"), callback_data="net:menu"))
        rows.append(network_row)
        rows.append([InlineKeyboardButton(text=label("manage.logs", "📋 Журналы"),
                                          callback_data="log:list")])
        # Подписка отдельной кнопкой: раньше тарифы правились из раздела
        # подборок, хотя подписка давно одна на бота и подборками
        # не исчерпывается.
        rows.append([InlineKeyboardButton(
            text=label("manage.subscription", "💳 Подписка"),
            callback_data="sub:admin")])
        # Управление разделами живёт здесь, а не внутри самих разделов:
        # иначе настройки расползаются по боту и их приходится искать.
        if features.enabled("partners"):
            rows.append([InlineKeyboardButton(
                text=label("menu.partners", "🤝 Партнёрские проекты"),
                callback_data="prj:manage",
            )])

    if roles.is_moderator(role) and features.enabled("web_panel"):
        rows.append([
            InlineKeyboardButton(text=label("manage.panel", "🖥 Веб-панель"),
                                 callback_data="menu:panel")
        ])

    rows.append([InlineKeyboardButton(text=label("menu.home", "🏠 В главное меню"),
                                      callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_row() -> list[InlineKeyboardButton]:
    """Партнёрская кнопка. Ведёт по внешней ссылке, отключается через .env.

    С 4.6.5 при включённом флаге `partners` вместо прямой ссылки ведёт
    в раздел со списком проектов: одна кнопка вмещала только один проект.
    """
    if features.enabled("partners"):
        return [InlineKeyboardButton(
            text="🤝 Партнёрские проекты", callback_data="menu:partners",
        )]
    # Флаг «Кнопка партнёра» и переменная PROMO_ENABLED существовали
    # параллельно: флаг значился в списке возможностей и ничего не делал,
    # выключалась кнопка только правкой .env. Теперь достаточно любого
    # из двух — выключенный тумблер обязан выключать.
    if not features.enabled("promo_button"):
        return []
    if not config.PROMO_ENABLED or not config.PROMO_URL:
        return []
    return [InlineKeyboardButton(text=config.PROMO_TITLE, url=config.PROMO_URL)]


def promo_only() -> InlineKeyboardMarkup | None:
    row = promo_row()
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def promo_with_back(target: str = "menu:main") -> InlineKeyboardMarkup:
    """Возврат в меню и партнёрская ссылка рядом.

    Раньше промо-кнопка вытесняла возврат целиком: из раздела «О системе»
    выйти было нечем, кроме как заново звать меню. Возврат обязателен,
    промо — нет, поэтому первый стоит всегда, второй добавляется.
    """
    rows = [[InlineKeyboardButton(text="🏠 В главное меню", callback_data=target)]]
    row = promo_row()
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Подписи закреплённых кнопок. Reply-кнопки не умеют открывать ссылки напрямую,
# поэтому «HydraSite» присылает сообщение с обычной inline-кнопкой-ссылкой.
BTN_MENU = "☰ Меню"
BTN_PROMO = "🐙 HydraSite"


def persistent_keyboard() -> ReplyKeyboardMarkup | None:
    """Две кнопки, закреплённые под полем ввода после запуска бота."""
    row = [KeyboardButton(text=BTN_MENU)]
    if config.PROMO_ENABLED and config.PROMO_URL:
        row.append(KeyboardButton(text=BTN_PROMO))
    return ReplyKeyboardMarkup(
        keyboard=[row],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Отправьте геопозицию или задайте вопрос",
    )


def weather_label(user: dict[str, Any], lang: str = "") -> str:
    lang = lang or i18n.language_of(user)
    if user.get("weather_mode") == "time":
        at = i18n.t("settings.weather.at", lang, "в")
        return f"{at} {user.get('weather_time', '08:00')}"
    minutes = int(user.get("weather_interval") or 0)
    if minutes <= 0:
        return i18n.t("settings.weather.off", lang, "откл")
    every = i18n.t("settings.weather.every", lang, "каждые")
    if minutes >= 60 and minutes % 60 == 0:
        hours = i18n.t("settings.weather.hours_short", lang, "ч")
        return f"{every} {minutes // 60} {hours}"
    return f"{every} {minutes} {i18n.t('settings.weather.minutes', lang, 'мин')}"


def settings_menu(user: dict[str, Any], target: str = "") -> InlineKeyboardMarkup:
    """target — id редактируемого пользователя (пусто, если правит себя)."""
    from .matching import category_title

    lang = i18n.language_of(user)

    def label(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    settings = user.get("settings") or {}
    suffix = f":{target}" if target else ""
    rows: list[list[InlineKeyboardButton]] = []
    keys = list(CATEGORY_TITLES)
    for index in range(0, len(keys), 2):
        row = []
        for key in keys[index:index + 2]:
            mark = "✅" if settings.get(key) else "❌"
            name = category_title(key, lang).split(" /")[0]
            row.append(
                InlineKeyboardButton(
                    text=f"{mark} {CATEGORY_ICONS[key]} {name}",
                    callback_data=f"set:toggle:{key}{suffix}",
                )
            )
        rows.append(row)
    if not target:
        rows.append(
            [InlineKeyboardButton(
                text=f"{label('settings.weather_button', '🌤 Погода')}: "
                     f"{weather_label(user, lang)}",
                callback_data="set:weather",
            )]
        )
        if features.enabled("weather_image"):
            if features.enabled("weather_image_all"):
                # Выбор перекрыт администрацией — кнопка не должна показывать
                # «текст», когда всё равно придёт картинка.
                mode = label("settings.wformat.image_all", "картинка (для всех)")
            else:
                picture = user.get("weather_format") != "text"
                mode = (label("settings.wformat.image", "картинка") if picture
                        else label("settings.wformat.text", "текст"))
            rows.append([InlineKeyboardButton(
                text=f"{label('settings.wformat.label', '🖼 Вид погоды')}: {mode}",
                callback_data="set:wformat",
            )])
        if features.enabled("quiet_hours"):
            from .quiet import quiet_summary

            rows.append([InlineKeyboardButton(
                text=f"{label('settings.quiet.label', '🌙 Тихие часы')}: "
                     f"{quiet_summary(user, lang)}",
                callback_data="set:quiet",
            )])
        # Часовой пояс стоит рядом с погодой и тихими часами не случайно:
        # он задаёт смысл обоим. «Погода в 8:00» без пояса — восемь утра
        # у сервера, а не у человека.
        rows.append([InlineKeyboardButton(
            text=f"{label('settings.tz.label', '🕓 Часовой пояс')}: "
                 f"{timezones.user_label(user, lang)}",
            callback_data="set:tz",
        )])
        rows.append([InlineKeyboardButton(
            text=label("menu.home", "🏠 В главное меню"), callback_data="menu:main")])
    else:
        rows.append(
            [InlineKeyboardButton(text="◀️ К пользователю", callback_data=f"usr:card:{target}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def timezone_menu(user: dict[str, Any], extra: bool = False) -> InlineKeyboardMarkup:
    """Выбор часового пояса.

    Целые часы на первом экране, получасовые — на втором: вместе они дают
    список в полтора раза длиннее ради нескольких стран, и человек из
    Саратова пролистывал бы Непал каждый раз.
    """
    lang = i18n.language_of(user)
    current = timezones.offset_of(user)
    values = timezones.FRACTIONAL if extra else timezones.WHOLE_HOURS

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for minutes in values:
        mark = "✅ " if minutes == current else ""
        row.append(InlineKeyboardButton(
            text=f"{mark}{timezones.label(minutes, lang)}",
            callback_data=f"set:tz:{timezones.render(minutes)}",
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if extra:
        rows.append([InlineKeyboardButton(
            text=i18n.t("settings.tz.whole", lang, "◀️ Целые часы"),
            callback_data="set:tz",
        )])
    else:
        rows.append([InlineKeyboardButton(
            text=i18n.t("settings.tz.fractional", lang, "⏱ Получасовые пояса"),
            callback_data="set:tz:extra",
        )])
    rows.append([InlineKeyboardButton(
        text=i18n.t("settings.back", lang, "◀️ К настройкам"),
        callback_data="menu:settings",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ai_menu() -> InlineKeyboardMarkup:
    """Единый раздел управления ИИ."""
    rows = []
    # Смена провайдера — за своим флагом: без него список провайдеров
    # только путает, а сам флаг до 4.7.4.3 ничего не выключал.
    if features.enabled("provider_switch"):
        rows.append([InlineKeyboardButton(
            text="🤖 Провайдер разбора", callback_data="prov:menu")])
    rows.extend([
        [InlineKeyboardButton(text="🤖 Модель провайдера", callback_data="ai:pickmodel")],
        [InlineKeyboardButton(text="🧪 Сравнить провайдеров", callback_data="bench:menu")],
        [InlineKeyboardButton(text="📊 Модели и квота", callback_data="ai:models")],
        [InlineKeyboardButton(text="🔑 Ключи ИИ", callback_data="key:group:ИИ")],
        [InlineKeyboardButton(text="◀️ К управлению", callback_data="menu:manage")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_settings(lang: str = "ru") -> InlineKeyboardMarkup:
    """Только возврат — когда выбирать нечего."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t("common.back", lang, "◀️ Назад"),
                              callback_data="menu:settings")],
    ])


def weather_format_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    """Вид сводки погоды: текст или картинка."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=i18n.t("settings.wformat.as_text", lang, "📄 Текстом"),
            callback_data="set:wfmt:text")],
        [InlineKeyboardButton(
            text=i18n.t("settings.wformat.as_image", lang, "🖼 Картинкой"),
            callback_data="set:wfmt:image")],
        [InlineKeyboardButton(text=i18n.t("common.back", lang, "◀️ Назад"),
                              callback_data="menu:settings")],
    ])


def weather_menu(target: str = "", lang: str = "ru") -> InlineKeyboardMarkup:
    """Меню режима погоды. target — чужой пользователь (правит администрация)."""
    suffix = f":{target}" if target else ""
    back = f"usr:card:{target}" if target else "menu:settings"

    def label(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label("settings.weather.disable", "Отключить"),
                    callback_data=f"set:wth:0{suffix}"),
                InlineKeyboardButton(
                    text=label("settings.weather.hour", "Каждый час"),
                    callback_data=f"set:wth:60{suffix}"),
            ],
            [
                InlineKeyboardButton(
                    text=label("settings.weather.hours3", "Каждые 3 часа"),
                    callback_data=f"set:wth:180{suffix}"),
                InlineKeyboardButton(
                    text=label("settings.weather.hours6", "Каждые 6 часов"),
                    callback_data=f"set:wth:360{suffix}"),
            ],
            [
                InlineKeyboardButton(
                    text=label("settings.weather.fixed_time", "⏰ Точное время"),
                    callback_data=f"set:wthtime{suffix}"),
                InlineKeyboardButton(
                    text=label("settings.weather.own_interval", "⏱ Свой интервал"),
                    callback_data=f"set:wthint{suffix}"),
            ],
            [InlineKeyboardButton(text=label("common.back", "◀️ Назад"), callback_data=back)],
        ]
    )


def locations_menu(locations: Sequence[dict[str, Any]], owner: str = "") -> InlineKeyboardMarkup:
    """Список локаций с кнопками удаления. owner — чужой пользователь (для модератора)."""
    suffix = f":{owner}" if owner else ""
    rows = [
        [
            InlineKeyboardButton(
                text=f"🗑 {loc.get('name', '')[:40]}",
                callback_data=f"loc:del:{loc.get('id')}{suffix}",
            )
        ]
        for loc in locations
    ]
    if owner:
        rows.append(
            [InlineKeyboardButton(text="➕ Добавить локацию", callback_data=f"usr:addloc:{owner}")]
        )
        rows.append([InlineKeyboardButton(text="◀️ К пользователю", callback_data=f"usr:card:{owner}")])
    else:
        rows.append(
            [
                InlineKeyboardButton(text="🌤 Погода", callback_data="loc:weather"),
                InlineKeyboardButton(text="🗑 Очистить все", callback_data="loc:clear"),
            ]
        )
        rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderation_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Очередь источников", callback_data="src:queue")],
            [InlineKeyboardButton(text="📋 Список источников", callback_data="src:list")],
            [InlineKeyboardButton(text="🔍 Проверить доступность", callback_data="src:check")],
            [InlineKeyboardButton(text="➕ Добавить канал", callback_data="src:add")],
            [InlineKeyboardButton(text="🌐 Добавить RSS СМИ", callback_data="src:addrss")],
            [
                InlineKeyboardButton(text="⬇️ Скачать список", callback_data="src:export"),
                InlineKeyboardButton(text="⬆️ Загрузить список", callback_data="src:import"),
            ],
            [InlineKeyboardButton(text="◀️ К управлению", callback_data="menu:manage")],
        ]
    )


def user_card(target: str, target_role: str, actor_role: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="📍 Локации", callback_data=f"usr:locs:{target}"),
            InlineKeyboardButton(text="⚙️ Оповещения", callback_data=f"usr:sets:{target}"),
        ],
        [InlineKeyboardButton(text="➕ Добавить локацию", callback_data=f"usr:addloc:{target}")],
        [InlineKeyboardButton(text="🌤 Погода пользователя", callback_data=f"usr:wth:{target}")],
    ]
    assignable = [
        role for role in roles.assignable_roles(actor_role)
        if roles.can_assign(actor_role, target_role, role) and role != target_role
    ]
    if assignable:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"→ {roles.title(role)}", callback_data=f"usr:role:{target}:{role}"
                )
                for role in assignable
            ]
        )
    if roles.can_delete_user(actor_role, target_role):
        rows.append(
            [InlineKeyboardButton(text="🔨 Удалить пользователя", callback_data=f"usr:del:{target}")]
        )
    rows.append([InlineKeyboardButton(text="◀️ К списку", callback_data="usr:list:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def users_page(
    items: Sequence[tuple[str, str, int]], page: int, pages: int
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{roles.title(role).split()[0]} {uid} · {count} лок.",
                callback_data=f"usr:card:{uid}",
            )
        ]
        for uid, role, count in items
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"usr:list:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"usr:list:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def geocode_choices(results: list[dict[str, str]], target: str) -> InlineKeyboardMarkup:
    """Варианты найденных адресов: выбор администратором."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{index + 1}. {item['name'][:45]}",
                callback_data=f"usr:pickloc:{target}:{index}",
            )
        ]
        for index, item in enumerate(results)
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"usr:card:{target}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm(action: str, argument: str, back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"{action}:{argument}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=back),
            ]
        ]
    )


def queue_item() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data="src:approve"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data="src:reject"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:mod")],
        ]
    )
