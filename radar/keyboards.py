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

from . import config, features, roles
from .matching import CATEGORY_ICONS, CATEGORY_TITLES

def main_menu(role: str | None) -> InlineKeyboardMarkup:
    """Главное меню.

    Собрано по назначению, а не по ролям: сначала то, чем пользуются каждый
    день, ниже — разделы управления. Каждый служебный раздел свёрнут в одну
    кнопку, иначе у суперадминистратора меню разрасталось до полутора
    десятков строк и переставало читаться.
    """
    rows = [
        [
            InlineKeyboardButton(text="📍 Мои локации", callback_data="loc:list"),
            InlineKeyboardButton(text="🌤 Погода", callback_data="loc:weather"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Оповещения", callback_data="menu:settings"),
            InlineKeyboardButton(text="📢 Предложить источник", callback_data="src:suggest"),
        ],
    ]

    if features.enabled("sos"):
        rows.append([InlineKeyboardButton(text="🆘 SOS", callback_data="sos:menu")])

    if roles.can_use_assistant(role):
        rows.append([InlineKeyboardButton(text="🧠 ИИ-ассистент", callback_data="menu:ai")])

    # Один вход в управление вместо россыпи кнопок
    if roles.is_moderator(role):
        rows.append([InlineKeyboardButton(text="🛠 Управление", callback_data="menu:manage")])

    rows.append([InlineKeyboardButton(text="ℹ️ О системе", callback_data="menu:about")])

    promo = promo_row()
    if promo:
        rows.append(promo)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manage_menu(role: str | None) -> InlineKeyboardMarkup:
    """Раздел управления: содержимое зависит от роли."""
    rows: list[list[InlineKeyboardButton]] = []

    if roles.is_moderator(role):
        rows.append([
            InlineKeyboardButton(text="📡 Источники", callback_data="menu:mod"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="usr:list:0"),
        ])

    if roles.is_admin(role):
        rows.append([
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats"),
            InlineKeyboardButton(text="🔗 Инвайт", callback_data="usr:invite"),
        ])

    if roles.is_superadmin(role):
        rows.append([
            InlineKeyboardButton(text="⚙️ Возможности", callback_data="feat:list"),
            InlineKeyboardButton(text="🔑 Ключи доступа", callback_data="key:list"),
        ])
        rows.append([
            InlineKeyboardButton(text="🧪 Проверка ИИ", callback_data="bench:menu"),
            InlineKeyboardButton(text="📋 Журналы", callback_data="log:list"),
        ])

    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_row() -> list[InlineKeyboardButton]:
    """Партнёрская кнопка. Ведёт по внешней ссылке, отключается через .env."""
    if not config.PROMO_ENABLED or not config.PROMO_URL:
        return []
    return [InlineKeyboardButton(text=config.PROMO_TITLE, url=config.PROMO_URL)]


def promo_only() -> InlineKeyboardMarkup | None:
    row = promo_row()
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


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


def weather_label(user: dict[str, Any]) -> str:
    if user.get("weather_mode") == "time":
        return f"в {user.get('weather_time', '08:00')}"
    minutes = int(user.get("weather_interval") or 0)
    if minutes <= 0:
        return "откл"
    if minutes >= 60 and minutes % 60 == 0:
        return f"каждые {minutes // 60} ч"
    return f"каждые {minutes} мин"


def settings_menu(user: dict[str, Any], target: str = "") -> InlineKeyboardMarkup:
    """target — id редактируемого пользователя (пусто, если правит себя)."""
    settings = user.get("settings") or {}
    suffix = f":{target}" if target else ""
    rows: list[list[InlineKeyboardButton]] = []
    keys = list(CATEGORY_TITLES)
    for index in range(0, len(keys), 2):
        row = []
        for key in keys[index:index + 2]:
            mark = "✅" if settings.get(key) else "❌"
            row.append(
                InlineKeyboardButton(
                    text=f"{mark} {CATEGORY_ICONS[key]} {CATEGORY_TITLES[key].split(' /')[0]}",
                    callback_data=f"set:toggle:{key}{suffix}",
                )
            )
        rows.append(row)
    if not target:
        rows.append(
            [InlineKeyboardButton(
                text=f"🌤 Погода: {weather_label(user)}", callback_data="set:weather"
            )]
        )
        rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    else:
        rows.append(
            [InlineKeyboardButton(text="◀️ К пользователю", callback_data=f"usr:card:{target}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def weather_menu(target: str = "") -> InlineKeyboardMarkup:
    """Меню режима погоды. target — чужой пользователь (правит администрация)."""
    suffix = f":{target}" if target else ""
    back = f"usr:card:{target}" if target else "menu:settings"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отключить", callback_data=f"set:wth:0{suffix}"),
                InlineKeyboardButton(text="Каждый час", callback_data=f"set:wth:60{suffix}"),
            ],
            [
                InlineKeyboardButton(text="Каждые 3 часа", callback_data=f"set:wth:180{suffix}"),
                InlineKeyboardButton(text="Каждые 6 часов", callback_data=f"set:wth:360{suffix}"),
            ],
            [
                InlineKeyboardButton(text="⏰ Точное время", callback_data=f"set:wthtime{suffix}"),
                InlineKeyboardButton(text="⏱ Свой интервал", callback_data=f"set:wthint{suffix}"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=back)],
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


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список пользователей", callback_data="usr:list:0")],
            [InlineKeyboardButton(text="🔗 Инвайт-ссылка", callback_data="usr:invite")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
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
