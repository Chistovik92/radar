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

from .. import ai, config, keyboards, monitor, roles, storage
from ..textutils import esc
from ..tg import back_kb, safe_edit

router = Router(name="common")

def greeting(role: str) -> str:
    lines = [f"🎛 <b>Система «Радар» v{config.VERSION}</b>", f"Ваша роль: {roles.title(role)}"]
    if roles.can_use_assistant(role):
        lines.append("")
        lines.append(
            "🧠 <i>ИИ-ассистент активен: напишите вопрос в чат или используйте /ai.</i>"
        )
    if not ai.ENABLED and roles.is_admin(role):
        lines.append("")
        lines.append("⚠️ <i>GEMINI_API_KEY не задан — работает эвристический анализ без ИИ.</i>")
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    # Закреплённые кнопки ставятся отдельным сообщением: Telegram не позволяет
    # приложить reply-клавиатуру и inline-меню к одному и тому же сообщению.
    keyboard = keyboards.persistent_keyboard()
    if keyboard is not None:
        await message.answer(
            "Кнопки <b>Меню</b> и <b>HydraSite</b> закреплены под полем ввода.",
            reply_markup=keyboard,
        )
    await message.answer(greeting(role), reply_markup=keyboards.main_menu(role))


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    await message.answer(greeting(role), reply_markup=keyboards.main_menu(role))


@router.message(F.text == keyboards.BTN_MENU)
async def button_menu(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    await message.answer(greeting(role), reply_markup=keyboards.main_menu(role))


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
async def cmd_cancel(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    await message.answer("✅ Действие отменено.", reply_markup=keyboards.main_menu(role))


@router.message(Command("id"))
async def cmd_id(message: Message, role: str) -> None:
    await message.answer(
        f"🆔 Ваш ID: <code>{message.from_user.id}</code>\nРоль: {roles.title(role)}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message, role: str) -> None:
    lines = [
        "<b>Как это работает</b>",
        "1. Отправьте геопозицию (Скрепка → Геопозиция) — так добавляется локация. "
        "Их может быть сколько угодно.",
        "2. Военные угрозы (БПЛА, ракетная опасность) приходят на весь город одним "
        "сообщением по всем вашим локациям в нём.",
        "3. Аварии ЖКХ ищутся адресно — по улице и дому.",
        "4. Локации ближе 1 км друг к другу объединяются в одну сводку.",
        "",
        "<b>Команды</b>",
        "/menu — меню - /id — ваш ID и роль - /cancel — сбросить ввод",
        "/partner — партнёрский проект",
    ]
    if roles.can_use_assistant(role):
        lines.append("/ai &lt;вопрос&gt; — ИИ-ассистент - /aireset — очистить контекст")
        lines.append("/quota — расход квоты Gemini")
    if roles.is_admin(role):
        lines.append("/stats — статистика системы - /models — модели Gemini")
    await message.answer("\n".join(lines), reply_markup=back_kb())


@router.callback_query(F.data == "menu:main")
async def menu_main(call: CallbackQuery, state: FSMContext, role: str) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(call, greeting(role), keyboards.main_menu(role))


@router.callback_query(F.data == "menu:settings")
async def menu_settings(call: CallbackQuery, state: FSMContext, user: dict[str, Any]) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(
        call,
        "⚙️ <b>Оповещения</b>\nВыберите, какие события присылать, и режим погоды.",
        keyboards.settings_menu(user),
    )


@router.callback_query(F.data == "menu:mod")
async def menu_mod(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_moderator(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, "🛡 <b>Панель модератора</b>", keyboards.moderation_menu())


@router.callback_query(F.data == "menu:admin")
async def menu_admin(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, "👥 <b>Управление пользователями</b>", keyboards.admin_menu())


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
    await safe_edit(call, "\n".join(parts), keyboards.promo_only() or back_kb())


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
        lines.append(f"<b>Доступно ключу ({len(available)}):</b>")
        lines.extend(f"• <code>{esc(name)}</code>" for name in available[:40])
        if len(available) > 40:
            lines.append(f"…и ещё {len(available) - 40}")
    else:
        lines.append("")
        lines.append("<i>Список моделей получить не удалось — используются значения из .env.</i>")
    lines.append("")
    lines.append(
        "<i>Модель подбирается автоматически. Чтобы закрепить свою — задайте "
        "GEMINI_MODEL в .env и перезапустите контейнер.</i>"
    )
    await message.answer("\n".join(lines), reply_markup=back_kb())


@router.callback_query(F.data == "menu:stats")
async def stats_button(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _stats_text(), back_kb("menu:admin", "◀️ Назад"))
