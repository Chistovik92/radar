"""Настройки системы для суперадминистратора: ключи доступа и проверка ИИ.

Здесь же запускается сравнение провайдеров: раньше это был отдельный скрипт
в `bench/`, который на сервере никто не запускал. Теперь тот же набор
тест-кейсов прогоняется прямо из бота по кнопке.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import ai, aibench, backup, config, features, roles, secrets
from ..states import Form
from ..textutils import esc, split_text
from ..tg import back_kb, safe_edit, send_html

log = logging.getLogger("radar.handlers.settings_admin")
router = Router(name="admin_settings")


# --------------------------------------------------------------------------
#  Ключи доступа
# --------------------------------------------------------------------------

def _groups_menu() -> InlineKeyboardMarkup:
    rows = []
    for group in secrets.GROUPS:
        items = secrets.by_group()[group]
        rows.append([
            InlineKeyboardButton(
                text=f"{group} — {secrets.filled(group)}/{len(items)}",
                callback_data=f"key:group:{group}",
            )
        ])
    rows.append([InlineKeyboardButton(text="◀️ К управлению", callback_data="menu:manage")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _group_menu(group: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if secrets.get(item.key) else '➕'} {item.title}",
                callback_data=f"key:edit:{item.key}",
            )
        ]
        for item in secrets.by_group().get(group, [])
    ]
    rows.append([InlineKeyboardButton(text="◀️ К разделам", callback_data="key:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _overview() -> str:
    lines = [
        "🔑 <b>Ключи доступа</b>",
        f"Заполнено: <b>{secrets.filled()}</b> из {len(secrets.SETTINGS)}",
        "",
    ]
    if not secrets.writable():
        lines.append(
            "⚠️ Файл <code>.env</code> недоступен на запись — сохранить "
            "значения из бота не получится. Проверьте права на файл."
        )
        lines.append("")
    lines.append(
        "<i>Ключи хранятся в .env рядом с ботом. Значения показаны "
        "замаскированными.</i>"
    )
    return "\n".join(lines)


@router.message(Command("keys"))
async def cmd_keys(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Ключи доступа настраивает суперадминистратор.")
        return
    await message.answer(_overview(), reply_markup=_groups_menu())


@router.callback_query(F.data == "key:list")
async def show_groups(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, _overview(), _groups_menu())


@router.callback_query(F.data.startswith("key:group:"))
async def show_group(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    group = call.data.split(":", 2)[2]
    await call.answer()

    lines = [f"🔑 <b>{esc(group)}</b>", ""]
    for item in secrets.by_group().get(group, []):
        lines.append(f"<b>{esc(item.title)}</b> — {esc(secrets.display(item))}")
        lines.append(f"<i>{esc(item.hint)}</i>")
        if item.where:
            lines.append(f"<i>Получить: {esc(item.where)}</i>")
        if item.restart:
            lines.append("<i>Применится после перезапуска контейнера.</i>")
        lines.append("")
    await safe_edit(call, "\n".join(lines).strip(), _group_menu(group))


@router.callback_query(F.data.startswith("key:edit:"))
async def ask_value(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    key = call.data.split(":", 2)[2]
    setting = secrets.BY_KEY.get(key)
    if setting is None:
        await call.answer("Неизвестный параметр.", show_alert=True)
        return

    await call.answer()
    await state.set_state(Form.secret_value)
    await state.update_data(secret_key=key)

    lines = [
        f"🔑 <b>{esc(setting.title)}</b>",
        f"Сейчас: {esc(secrets.display(setting))}",
        "",
        esc(setting.hint),
    ]
    if setting.where:
        lines.append(f"\n<b>Где взять:</b> {esc(setting.where)}")
    if setting.restart:
        lines.append("\n⚠️ <i>Применится после перезапуска контейнера.</i>")
    lines.append("\nПришлите значение одним сообщением.")
    lines.append("<i>«-» очистит поле. /cancel — отмена.</i>")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"key:group:{setting.group}")]
    ])
    await safe_edit(call, "\n".join(lines), kb)


@router.message(Form.secret_value)
async def save_value(message: Message, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await state.clear()
        return

    data = await state.get_data()
    key = data.get("secret_key") or ""
    setting = secrets.BY_KEY.get(key)
    value = (message.text or "").strip()

    if value.startswith("/"):
        return
    if setting is None:
        await state.clear()
        await message.answer("❌ Параметр не найден.")
        return

    await state.clear()

    # Само сообщение с ключом лучше убрать из переписки
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass

    if value == "-":
        secrets.clear(key)
        await message.answer(
            f"🧹 <b>{esc(setting.title)}</b> очищено.",
            reply_markup=back_kb(f"key:group:{setting.group}", "◀️ Назад"),
        )
        return

    if not secrets.write(key, value):
        await message.answer(
            "❌ Не удалось записать в .env — проверьте права на файл.",
            reply_markup=back_kb("key:list", "◀️ Назад"),
        )
        return

    note = (
        "\n\n⚠️ <i>Изменение применится после перезапуска:</i> "
        "<code>docker compose restart</code>"
        if setting.restart else "\n\n<i>Применяется сразу.</i>"
    )
    await message.answer(
        f"✅ <b>{esc(setting.title)}</b> сохранено: {esc(secrets.display(setting))}{note}",
        reply_markup=back_kb(f"key:group:{setting.group}", "◀️ Назад"),
    )


# --------------------------------------------------------------------------
#  Сравнение провайдеров ИИ
# --------------------------------------------------------------------------

def _bench_menu() -> InlineKeyboardMarkup:
    ready = aibench.configured_providers()
    rows = [[
        InlineKeyboardButton(
            text=f"▶️ Запустить проверку ({len(ready)} провайдеров)",
            callback_data="bench:run",
        )
    ]]
    if aibench.last_report() is not None:
        rows.append([
            InlineKeyboardButton(text="📊 Последний отчёт", callback_data="bench:last")
        ])
    rows.append([InlineKeyboardButton(text="◀️ К управлению ИИ", callback_data="ai:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _bench_overview() -> str:
    ready = aibench.configured_providers()
    lines = [
        "🧪 <b>Сравнение провайдеров ИИ</b>",
        "",
        "Одинаковые сообщения городских служб прогоняются через все "
        "провайдеры, у которых задан ключ. Сравнивается точность разбора: "
        "категории, улицы и дома, отсутствие ложных тревог.",
        "",
    ]
    if ready:
        lines.append("<b>Готовы к проверке:</b>")
        lines += [f"• {esc(item.title)}" for item in ready]
    else:
        lines.append(
            "⚠️ Ни у одного провайдера не задан ключ. Добавьте их "
            "в разделе «ИИ»."
        )
    lines.append("")
    lines.append(
        "<i>Важно: смотрите на колонку «военные темы». Провайдер, который "
        "срезает сообщения о БПЛА, для оповещений непригоден, каким бы "
        "точным он ни был в остальном.</i>"
    )
    return "\n".join(lines)


@router.message(Command("bench"))
async def cmd_bench(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Проверка провайдеров доступна суперадминистратору.")
        return
    await message.answer(_bench_overview(), reply_markup=_bench_menu())


@router.callback_query(F.data == "bench:menu")
async def bench_menu(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _bench_overview(), _bench_menu())


@router.callback_query(F.data == "bench:last")
async def bench_last(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    report = aibench.last_report()
    if report is None:
        await call.answer("Отчётов ещё нет.", show_alert=True)
        return
    await call.answer()
    for chunk in split_text(aibench.render(report)):
        await send_html(call.message.chat.id, chunk)


@router.callback_query(F.data == "bench:run")
async def bench_run(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    ready = aibench.configured_providers()
    if not ready:
        await call.answer("Нет провайдеров с ключами.", show_alert=True)
        return
    if aibench.is_running():
        await call.answer("Проверка уже идёт.", show_alert=True)
        return

    await call.answer("Запускаю проверку…")
    notice = await call.message.answer(
        f"🧪 Проверяю {len(ready)} провайдеров…\n"
        "<i>Займёт несколько минут: запросы идут с паузами.</i>"
    )

    async def progress(done: int, total: int, current: str) -> None:
        try:
            await notice.edit_text(
                f"🧪 Проверка: <b>{done}/{total}</b>\n<i>сейчас: {esc(current)}</i>"
            )
        except Exception:  # noqa: BLE001
            pass

    try:
        report = await aibench.run(progress=progress)
    except Exception as exc:  # noqa: BLE001
        log.exception("Проверка провайдеров не удалась")
        await notice.edit_text(f"❌ Проверка не удалась: {esc(exc)}")
        return

    try:
        await notice.delete()
    except Exception:  # noqa: BLE001
        pass

    for chunk in split_text(aibench.render(report)):
        await send_html(call.message.chat.id, chunk)
    await send_html(
        call.message.chat.id,
        "<i>Провайдер для разбора новостей задаётся переменной "
        "GEMINI_MODEL_ANALYSIS; смена провайдера по умолчанию появится "
        "в версии 4.3.</i>",
        back_kb("ai:menu", "◀️ К управлению ИИ"),
    )


# --------------------------------------------------------------------------
#  Веб-панель
# --------------------------------------------------------------------------

@router.callback_query(F.data == "menu:panel")
async def panel_info(call: CallbackQuery, role: str) -> None:
    if not roles.is_moderator(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _panel_text(role), back_kb("menu:manage", "◀️ Назад"))


@router.message(Command("panel"))
async def cmd_panel(message: Message, role: str) -> None:
    """Как попасть в панель: адрес и состояние доступа."""
    if not roles.is_moderator(role):
        await message.answer("⛔️ Панель доступна модераторам и выше.")
        return

    await message.answer(_panel_text(role), reply_markup=back_kb())


def _panel_text(role: str) -> str:
    if not features.enabled("web_panel"):
        return (
            "🖥 <b>Веб-панель выключена</b>\n\n"
            "Включить: /features → Администрирование → Веб-панель.\n"
            "После включения перезапустите контейнер: "
            "<code>docker compose restart</code>"
        )

    host = secrets.get("WEB_PUBLIC_URL")
    port = config.WEB_PORT
    lines = ["🖥 <b>Веб-панель</b>", ""]

    if host:
        lines.append(f"Адрес: {esc(host)}")
    else:
        lines.append(f"Порт: <code>{port}</code>")
        lines.append("")
        lines.append(
            "По умолчанию панель слушает только сам сервер — это безопасно. "
            "Открыть с ноутбука можно через SSH-туннель:"
        )
        lines.append(f"<code>ssh -L {port}:127.0.0.1:{port} root@ваш-сервер</code>")
        lines.append(f"затем откройте <code>http://localhost:{port}</code>")
        lines.append("")
        lines.append(
            "Чтобы открыть панель наружу, задайте <code>WEB_BIND=0.0.0.0</code>, "
            "<code>WEB_HTTPS=1</code> и поставьте reverse proxy с сертификатом. "
            "Без HTTPS cookie сессии уходит открытым текстом."
        )

    lines.append("")
    lines.append(
        "Вход — кнопкой Telegram, паролей нет. Разделы зависят от роли: "
        "модератор видит источники и пользователей, администратор — ещё "
        "события, суперадминистратор — возможности, копии и журнал."
    )
    lines.append("")
    lines.append(
        "<i>Панель — дублирующий контур. Основное управление остаётся в боте.</i>"
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
#  Резервные копии
# --------------------------------------------------------------------------

def _backup_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="💾 Создать копию", callback_data="bak:make")]]
    items = backup.listing()
    if items:
        rows.append([
            InlineKeyboardButton(text="⬇️ Скачать последнюю", callback_data="bak:get")
        ])
    rows.append([InlineKeyboardButton(
        text="🔍 Проверить целостность", callback_data="bak:verify")])
    rows.append([InlineKeyboardButton(text="◀️ К управлению", callback_data="menu:manage")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "bak:verify")
async def backup_verify(call: CallbackQuery, role: str) -> None:
    """Пересчёт данных — пункт 6 раздела 4.7 дорожной карты.

    Нужен после восстановления и переезда: успешно запустившаяся система
    с пустой базой выглядит точно так же, как с полной. Без пересчёта
    потеря обнаруживается только когда кто-то пожалуется на пропавшие
    оповещения — то есть слишком поздно.
    """
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    await call.answer("Считаю…")
    from ..db import repo

    try:
        users = await repo.count_users()
        locations = await repo.count_locations()
        sources = await repo.count_sources()
    except Exception as exc:  # noqa: BLE001
        log.exception("Проверка целостности не удалась")
        await safe_edit(call, f"❌ Проверка не удалась: {esc(str(exc))}",
                        _backup_menu())
        return

    lines = [
        "🔍 <b>Целостность данных</b>",
        "",
        f"Пользователей: <b>{users}</b>",
        f"Локаций: <b>{locations}</b>",
        f"Источников: <b>{sources}</b>",
        "",
    ]
    if users == 0:
        lines.append(
            "⚠️ <b>Пользователей ноль.</b> Если это не первая установка — "
            "данные не перенеслись. Копия цела: разверните её заново."
        )
    elif locations == 0:
        lines.append(
            "⚠️ Локаций нет: оповещения никому не уйдут, пока люди "
            "не добавят адреса."
        )
    else:
        lines.append("✅ Данные на месте.")

    await safe_edit(call, "\n".join(lines), _backup_menu())


@router.message(Command("backup"))
async def cmd_backup(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Резервные копии делает суперадминистратор.")
        return
    await message.answer(backup.summary(), reply_markup=_backup_menu())


@router.callback_query(F.data == "bak:menu")
async def backup_menu(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, backup.summary(), _backup_menu())


@router.callback_query(F.data == "bak:make")
async def backup_make(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    await call.answer("Собираю копию…")
    notice = await call.message.answer("💾 Собираю копию: база, настройки, версия…")

    path, error = await backup.create(f"бот:{call.from_user.id}")
    if path is None:
        await notice.edit_text(f"❌ Копию создать не удалось: {esc(error)}")
        return

    size = path.stat().st_size
    await notice.edit_text(
        f"✅ <b>Копия создана</b>\n<code>{esc(path.name)}</code>\n"
        f"Размер: {size // 1024} КБ\n\n"
        "<i>Восстановление — установщиком: "
        "<code>bash install.sh --rollback</code></i>",
        reply_markup=_backup_menu(),
    )


@router.callback_query(F.data == "bak:get")
async def backup_download(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    items = backup.listing()
    if not items:
        await call.answer("Копий нет.", show_alert=True)
        return

    latest = items[0]
    # Telegram не примет файл больше 50 МБ без своего Bot API Server
    limit = 1900 if config.uses_local_api() else 50
    if latest.size > limit * 1024 * 1024:
        await call.answer()
        await call.message.answer(
            f"⚠️ Копия весит {latest.size_human} — больше предела отправки "
            f"({limit} МБ). Заберите её с сервера:\n"
            f"<code>scp root@сервер:~/radar_bot/backups/{esc(latest.name)} .</code>"
        )
        return

    await call.answer("Отправляю…")
    from aiogram.types import FSInputFile

    await call.message.answer_document(
        FSInputFile(str(latest.path)),
        caption=f"💾 {esc(latest.name)}\n{latest.when} · {latest.size_human}",
        reply_markup=_backup_menu(),
    )


# --------------------------------------------------------------------------
#  Единый раздел управления ИИ
# --------------------------------------------------------------------------

def _ai_overview() -> str:
    from .. import provider

    active = provider.PROVIDERS.get(provider.current())
    report = ai.models_report()
    snapshot = ai.limiter.snapshot()
    left = int(snapshot.get("limit_day", 0)) - int(snapshot.get("used_today", 0))

    lines = [
        "🧠 <b>Управление ИИ</b>",
        "",
        f"<b>Разбор новостей:</b> {esc(active.title if active else 'не выбран')}",
        f"<b>Ассистент:</b> Google Gemini "
        f"<i>(только он умеет искать в интернете)</i>",
        "",
        f"Модель ассистента: <code>{esc(report.get('assistant') or '—')}</code>",
        f"Модель разбора: <code>{esc(report.get('analysis') or '—')}</code>",
        f"Запросов сегодня: {snapshot.get('used_today', 0)} из "
        f"{snapshot.get('limit_day', 0)} <i>(осталось {max(0, left)})</i>",
    ]
    if snapshot.get("paused"):
        lines.append("")
        lines.append("⚠️ <i>Фоновый разбор приостановлен: превышена квота.</i>")
    return "\n".join(lines)


@router.message(Command("ai_admin"))
async def cmd_ai_admin(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Управление ИИ доступно суперадминистратору.")
        return
    from .. import keyboards

    await message.answer(_ai_overview(), reply_markup=keyboards.ai_menu())


@router.callback_query(F.data == "ai:menu")
async def ai_menu(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    from .. import keyboards

    await state.clear()
    await call.answer()
    await safe_edit(call, _ai_overview(), keyboards.ai_menu())


@router.callback_query(F.data == "ai:models")
async def ai_models(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    from .. import keyboards

    await call.answer("Запрашиваю список моделей…")
    await ai.discover_models()
    report = ai.models_report()

    available = [name for name in report.get("available", []) if "gemini" in name]
    lines = [
        "📊 <b>Модели Gemini</b>",
        "",
        f"Ассистент: <code>{esc(report.get('assistant') or '—')}</code>",
        f"Разбор: <code>{esc(report.get('analysis') or '—')}</code>",
        "",
        f"<b>Доступно ключу: {len(available)}</b>",
    ]
    lines += [f"• <code>{esc(name)}</code>" for name in available[:30]]
    if len(available) > 30:
        lines.append(f"<i>…и ещё {len(available) - 30}</i>")
    lines.append("")
    lines.append(
        "Закрепить: <code>/setmodel имя</code> — ассистент, "
        "<code>/setmodel имя analysis</code> — разбор."
    )

    for chunk in split_text("\n".join(lines)):
        await send_html(call.message.chat.id, chunk)
    await send_html(
        call.message.chat.id, "<i>Готово.</i>", keyboards.ai_menu()
    )
