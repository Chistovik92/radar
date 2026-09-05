"""Команды /start, /menu, /help, /id, /cancel и главное меню."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from .. import ai, config, features, i18n, keyboards, monitor, roles, storage
from ..textutils import esc, split_text
from ..tg import back_kb, safe_edit

router = Router(name="common")

def greeting(role: str, user: dict | None = None) -> str:
    lang = i18n.language_of(user)
    role_line = i18n.t("manage.role_line", lang, "Ваша роль")
    lines = [
        f"🎛 <b>{i18n.t('app.title', lang, 'Система «Радар»')} v{config.VERSION}</b>",
        f"{role_line}: {roles.title(role, lang)}",
    ]
    if roles.can_use_assistant(role):
        lines.append("")
        lines.append(i18n.t(
            "greeting.assistant",
            lang,
            "🧠 <i>ИИ-ассистент активен: напишите вопрос в чат или используйте /ai.</i>",
        ))
    if not ai.ENABLED and roles.is_admin(role):
        lines.append("")
        lines.append(i18n.t(
            "greeting.no_key",
            lang,
            "⚠️ <i>GEMINI_API_KEY не задан — работает эвристический анализ без ИИ.</i>",
        ))
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, role: str, user: dict) -> None:
    await state.clear()
    # Закреплённые кнопки ставятся отдельным сообщением: Telegram не позволяет
    # приложить reply-клавиатуру и inline-меню к одному и тому же сообщению.
    # /start ставит кнопки заново всегда: человек мог их убрать сам.
    user.setdefault("settings", {})["pinned"] = False
    await ensure_pinned(message, user)
    await message.answer(greeting(role, user), reply_markup=keyboards.main_menu(role, user))


async def ensure_pinned(message: Message, user: dict) -> None:
    """Ставит закреплённые кнопки тем, у кого их ещё нет.

    Раньше они появлялись только на /start, и у всех, кто начал раньше
    их появления, кнопки «Меню» просто не было: человек знал про неё
    из чужих скриншотов, а у себя не находил. Спросить у Telegram,
    показана ли reply-клавиатура, нельзя, поэтому помечаем у себя —
    и отправляем ровно один раз.
    """
    if (user.get("settings") or {}).get("pinned"):
        return
    keyboard = keyboards.persistent_keyboard()
    if keyboard is None:
        return
    await message.answer(
        i18n.t(
            "common.pinned_buttons",
            i18n.language_of(user),
            "Кнопки <b>Меню</b> и <b>HydraSite</b> закреплены под полем ввода.",
        ),
        reply_markup=keyboard,
    )
    user.setdefault("settings", {})["pinned"] = True
    await storage.save(message.from_user.id)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, role: str, user: dict) -> None:
    await state.clear()
    await ensure_pinned(message, user)
    await message.answer(greeting(role, user), reply_markup=keyboards.main_menu(role, user))


@router.message(F.text == keyboards.BTN_MENU)
async def button_menu(message: Message, state: FSMContext, role: str, user: dict) -> None:
    await state.clear()
    await message.answer(greeting(role, user), reply_markup=keyboards.main_menu(role, user))


@router.message(F.text == keyboards.BTN_PROMO)
async def button_promo(message: Message) -> None:
    if not config.PROMO_ENABLED or not config.PROMO_URL:
        return
    await message.answer(
        config.PROMO_TEXT,
        reply_markup=keyboards.promo_only(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(Command("partner", "vpn"))
async def cmd_partner(message: Message) -> None:
    await button_promo(message)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, role: str, user: dict) -> None:
    await state.clear()
    await message.answer(
        i18n.t("common.cancelled", i18n.language_of(user), "✅ Действие отменено."),
        reply_markup=keyboards.main_menu(role, user),
    )


@router.message(Command("id"))
async def cmd_id(message: Message, role: str, user: dict) -> None:
    lang = i18n.language_of(user)
    await message.answer(
        f"{i18n.t('common.your_id', lang, '🆔 Ваш ID')}: "
        f"<code>{message.from_user.id}</code>\n"
        f"{i18n.t('common.role', lang, 'Роль')}: {roles.title(role, lang)}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message, role: str, user: dict) -> None:
    lang = i18n.language_of(user)

    def _(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    lines = [
        f"<b>{_('help.title', 'Как это работает')}</b>",
        _(
            "help.step1",
            "1. Отправьте геопозицию (Скрепка → Геопозиция) — так добавляется "
            "локация. Их может быть сколько угодно.",
        ),
        _(
            "help.step2",
            "2. Военные угрозы (БПЛА, ракетная опасность) приходят на весь город "
            "одним сообщением по всем вашим локациям в нём.",
        ),
        _("help.step3", "3. Аварии ЖКХ ищутся адресно — по улице и дому."),
        _("help.step4", "4. Локации ближе 1 км друг к другу объединяются в одну сводку."),
        "",
        f"<b>{_('help.commands_title', 'Команды')}</b>",
        _("help.cmd_basic", "/menu — меню - /id — ваш ID и роль - /cancel — сбросить ввод"),
        _("help.cmd_partner", "/partner — партнёрский проект"),
    ]
    if features.enabled("linkcheck"):
        lines.append(_(
            "help.cmd_linkcheck",
            "/check &lt;ссылка&gt; — проверить ссылку на признаки мошенничества",
        ))
    if roles.can_use_assistant(role):
        lines.append(_(
            "help.cmd_assistant",
            "/ai &lt;вопрос&gt; — ИИ-ассистент - /aireset — очистить контекст",
        ))
        lines.append(_("help.cmd_quota", "/quota — расход квоты Gemini"))
    if roles.is_admin(role):
        lines.append(_("help.cmd_admin1", "/stats — статистика системы - /models — модели Gemini"))
        lines.append(_("help.cmd_admin2", "/digest — новостные подборки - /sos — тревожная кнопка"))
        lines.append(_(
            "help.cmd_admin3", "/media — скачать видео по ссылке - /panel — веб-панель"
        ))
    if roles.is_superadmin(role):
        lines.append(_(
            "help.cmd_super1",
            "/features — возможности системы\n"
            "/logs — журналы - /logtail — последние строки - /logclear — очистить",
        ))
        lines.append(_(
            "help.cmd_super2", "/perf — время цикла и ресурсы - /bench — сравнение ИИ-провайдеров"
        ))
        lines.append(_(
            "help.cmd_super3",
            "/keys — ключи и настройки - /provider — выбор провайдера\n"
            "/network — сеть и прокси - /backup — резервная копия - "
            "/cookies — файл cookies",
        ))
    await message.answer("\n".join(lines), reply_markup=back_kb())


@router.callback_query(F.data == "menu:main")
async def menu_main(call: CallbackQuery, state: FSMContext, role: str, user: dict) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(call, greeting(role, user), keyboards.main_menu(role, user))


@router.callback_query(F.data == "menu:settings")
async def menu_settings(call: CallbackQuery, state: FSMContext, user: dict[str, Any]) -> None:
    await state.clear()
    await call.answer()
    lang = i18n.language_of(user)
    await safe_edit(
        call,
        f"<b>{i18n.t('settings.title', lang, '⚙️ Оповещения')}</b>\n"
        + i18n.t(
            "settings.prompt",
            lang,
            "Выберите, какие события присылать, и режим погоды.",
        ),
        keyboards.settings_menu(user),
    )


@router.callback_query(F.data == "menu:manage")
async def menu_manage(call: CallbackQuery, state: FSMContext, role: str, user: dict) -> None:
    lang = i18n.language_of(user)

    def _(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    if not roles.is_moderator(role):
        await call.answer(_("common.insufficient_rights", "Недостаточно прав."), show_alert=True)
        return
    await state.clear()
    await call.answer()

    lines = [
        f"<b>{_('menu.manage', '🛠 Управление')}</b>", "",
        f"{_('manage.role_line', 'Ваша роль')}: {roles.title(role, lang)}", "",
    ]
    if roles.is_superadmin(role):
        lines.append(_(
            "manage.all_sections", "Доступны все разделы, включая ключи доступа и журналы."
        ))
    elif roles.is_admin(role):
        lines.append(_(
            "manage.admin_sections", "Доступны источники, пользователи, статистика, ссылки и приглашения."
        ))
    else:
        lines.append(_(
            "manage.mod_sections", "Доступны источники и правка настроек пользователей."
        ))
    await safe_edit(call, "\n".join(lines), keyboards.manage_menu(role, user))


@router.callback_query(F.data == "menu:mod")
async def menu_mod(call: CallbackQuery, state: FSMContext, role: str, user: dict) -> None:
    if not roles.is_moderator(role):
        await call.answer(
            i18n.t("common.insufficient_rights", i18n.language_of(user), "Недостаточно прав."),
            show_alert=True,
        )
        return
    await state.clear()
    await call.answer()
    await safe_edit(
        call,
        "📡 <b>Источники</b>\n\n"
        "Здесь добавляются каналы и ленты, проверяется их доступность "
        "и разбирается очередь предложений от пользователей.",
        keyboards.moderation_menu(),
    )


@router.callback_query(F.data == "menu:about")
async def menu_about(call: CallbackQuery) -> None:
    await call.answer()
    parts = [
        f"ℹ️ <b>Система «Радар» v{config.VERSION}</b>",
        "",
        "Мониторит публичные Telegram-каналы служб ЖКХ, МЧС, администраций города, "
        "района и области, а также ленты СМИ. Сообщения разбирает ИИ Google Gemini, "
        "после чего события сопоставляются с вашими локациями.",
        "",
        "🛸 Военные угрозы — на весь город.",
        "🛠 ЖКХ — адресно, по улице и дому.",
        "📵 При угрозе с воздуха предупреждаем о «белых списках» связи.",
        "🌤 Погода — по каждой группе локаций.",
        "",
        "<i>Система не заменяет официальные каналы оповещения.</i>",
    ]
    if config.PROMO_ENABLED and config.PROMO_TEXT:
        parts += ["", "———", "", config.PROMO_TEXT]
    await safe_edit(call, "\n".join(parts), keyboards.promo_with_back())


def _quota_line() -> str:
    quota = ai.quota_snapshot()
    state = " ⏸ пауза после 429" if quota["paused"] else ""
    return (
        f"Квота Gemini: <b>{quota['used_today']}/{quota['limit_day']}</b> за сутки, "
        f"<b>{quota['in_minute']}/{quota['limit_minute']}</b> за минуту{state}"
    )


def _stats_text() -> str:
    counters: dict[str, int] = {}
    locations = 0
    for user in storage.users().values():
        counters[user.get("role", "user")] = counters.get(user.get("role", "user"), 0) + 1
        locations += len(user.get("locs") or [])
    data = monitor.stats()
    parts = [
        f"📊 <b>Статистика «Радар» v{config.VERSION}</b>",
        f"Пользователей: <b>{len(storage.users())}</b> "
        f"({', '.join(f'{roles.title(r)}: {c}' for r, c in sorted(counters.items()))})",
        f"Локаций: <b>{locations}</b>",
        f"Каналов: <b>{len(storage.channels())}</b>, RSS: <b>{len(storage.rss_feeds())}</b>, "
        f"в очереди: <b>{len(storage.pending())}</b>",
        f"ИИ: <b>{esc(ai.current_model(ai.ASSISTANT)) if ai.ENABLED else 'выключен (эвристика)'}</b>"
        + (f" | разбор: <b>{esc(ai.current_model(ai.ANALYSIS))}</b>" if ai.ENABLED else ""),
        f"Циклов: <b>{data['cycles']}</b>, сообщений: <b>{data['items']}</b>, "
        f"оповещений: <b>{data['alerts']}</b>",
        f"Кэш анализов: <b>{data['cache']}</b>, помечено прочитанным: <b>{data['seen']}</b>",
        f"Разбор: ИИ <b>{data['ai']}</b>, из кэша <b>{data['cached']}</b>, "
        f"отсеяно фильтром <b>{data['prefiltered']}</b>, эвристикой <b>{data['heuristic']}</b>",
        _quota_line(),
        f"Интервал опроса: <b>{config.POLL_INTERVAL} с</b>",
        f"Время сервера: <b>{datetime.now():%Y-%m-%d %H:%M:%S}</b>",
    ]
    return "\n".join(parts)


@router.message(Command("stats"))
async def cmd_stats(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        return
    await message.answer(_stats_text(), reply_markup=back_kb())


@router.message(Command("quota"))
async def cmd_quota(message: Message, role: str) -> None:
    if not roles.is_moderator(role):
        return
    counters = ai.counters()
    lines = [
        "📉 <b>Расход квоты Gemini</b>",
        _quota_line(),
        f"Запросов к модели: <b>{counters['requests']}</b> "
        f"(разобрано сообщений: {counters['ai']})",
        f"Сэкономлено: фильтр <b>{counters['prefiltered']}</b>, "
        f"кэш <b>{counters['cached']}</b>, эвристика <b>{counters['heuristic']}</b>",
        "",
        f"Анализ: <code>{esc(ai.current_model(ai.ANALYSIS))}</code>, "
        f"ассистент: <code>{esc(ai.current_model(ai.ASSISTANT))}</code>",
        "<i>Суточный лимит обнуляется в полночь по тихоокеанскому времени "
        "(около 10–11 утра по Москве).</i>",
    ]
    await message.answer("\n".join(lines), reply_markup=back_kb())


@router.message(Command("models"))
async def cmd_models(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        return
    await message.answer("🔎 Запрашиваю список моделей у Google…")
    await ai.discover_models()
    report = ai.models_report()
    lines = [
        "🤖 <b>Модели Gemini</b>",
        f"Ассистент: <code>{esc(report['assistant'])}</code>",
        f"Разбор новостей: <code>{esc(report['analysis'])}</code>",
    ]
    if report["unavailable"]:
        lines.append(
            "Отключены ключом: " + ", ".join(f"<code>{esc(m)}</code>" for m in report["unavailable"])
        )
    available = [m for m in report["available"] if "gemini" in m]
    if available:
        lines.append("")
        lines.append(f"<b>Доступно вашему ключу ({len(available)}):</b>")
        lines.extend(f"• <code>{esc(name)}</code>" for name in available)
    else:
        lines.append("")
        lines.append("<i>Список моделей получить не удалось — используются значения из .env.</i>")
    lines.append("")
    lines.append(
        "<i>Модель подбирается автоматически из доступных. Закрепить свою: "
        "<code>/setmodel имя</code> — для ассистента, "
        "<code>/setmodel имя analysis</code> — для разбора новостей.</i>"
    )
    for chunk in split_text("\n".join(lines)):
        await message.answer(chunk, reply_markup=back_kb())


@router.message(Command("setmodel"))
async def cmd_setmodel(message: Message, role: str) -> None:
    """Закрепить конкретную модель Gemini из доступных ключу."""
    if not roles.is_admin(role):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "Укажите модель: <code>/setmodel gemini-3.6-flash</code>\n"
            "Для разбора новостей: <code>/setmodel gemini-3.5-flash-lite analysis</code>\n"
            "Список доступных — команда /models."
        )
        return

    name = parts[1].strip()
    target = ai.ANALYSIS if len(parts) > 2 and parts[2].startswith("anal") else ai.ASSISTANT

    available = ai.models_report()["available"]
    if available and name not in available:
        await message.answer(
            f"❌ Модель <code>{esc(name)}</code> недоступна вашему ключу.\n"
            "Посмотрите список: /models"
        )
        return

    if not ai.pin_model(target, name):
        await message.answer("❌ Не удалось закрепить модель.")
        return

    role_title = "разбора новостей" if target == ai.ANALYSIS else "ассистента"
    await message.answer(
        f"✅ Модель {role_title}: <code>{esc(name)}</code>\n"
        "<i>Действует сразу. Чтобы сохранить после перезапуска, задайте "
        f"{'GEMINI_MODEL_ANALYSIS' if target == ai.ANALYSIS else 'GEMINI_MODEL'} "
        "в разделе «Ключи доступа».</i>",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "menu:stats")
async def stats_button(call: CallbackQuery, role: str, user: dict) -> None:
    if not roles.is_admin(role):
        await call.answer(
            i18n.t("common.insufficient_rights", i18n.language_of(user), "Недостаточно прав."),
            show_alert=True,
        )
        return
    await call.answer()
    await safe_edit(call, _stats_text(), back_kb("menu:manage", "◀️ Назад"))
