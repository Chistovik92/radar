"""Источники: предложение пользователем, очередь модерации, ручное добавление."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import (
    config,
    exporting,
    features,
    i18n,
    keyboards,
    roles,
    sourcecheck,
    sourceedit,
    storage,
)
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, safe_edit, send_html

router = Router(name="sources")

# Разбор и проверка переехали в radar/sourceedit.py: те же действия делает
# веб-панель, и два набора правил разъехались бы. Имена оставлены здесь
# как псевдонимы — на них ссылается остальной модуль.
CHANNEL_RE = sourceedit.CHANNEL_RE
normalize_channel = sourceedit.normalize_channel


@router.callback_query(F.data == "src:suggest")
async def suggest(call: CallbackQuery, state: FSMContext, user: dict) -> None:
    lang = i18n.language_of(user)

    def _(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    await call.answer()
    title = _("suggest.title", "📢 <b>Предложить источник</b>")

    # Флаг «Предложение источников новостей» до 4.7.5 ничего не выключал.
    # Когда он снят, предложения не принимаются вовсе: список источников
    # тогда ведёт только администрация, и обещать людям обратное нельзя.
    if not features.enabled("digest_suggestions"):
        await safe_edit(
            call,
            f"{title}\n\n" + _(
                "suggest.closed",
                "Приём предложений сейчас закрыт — список источников ведёт "
                "администрация.",
            ),
            back_kb("menu:main", _("common.back", "Назад")),
        )
        return

    await safe_edit(
        call,
        f"{title}\n"
        + _(
            "suggest.prompt",
            "Пришлите юзернейм публичного канала, например "
            "<code>saratovzhkh</code> или ссылку на него.",
        )
        + "\n\n"
        + _(
            "suggest.thematic",
            "<i>Подойдут и тематические каналы — про игры, спорт, науку: "
            "они попадут в новостные подборки.</i>",
        ),
        back_kb("menu:main", _("common.cancel", "Отмена")),
    )
    await state.set_state(Form.suggest_source)


@router.message(Form.suggest_source)
async def save_suggestion(message: Message, state: FSMContext, user: dict) -> None:
    lang = i18n.language_of(user)
    channel = normalize_channel(message.text or "")
    await state.clear()
    if not CHANNEL_RE.match(channel):
        await message.answer(
            i18n.t("suggest.bad", lang, "❌ Некорректный юзернейм канала."),
            reply_markup=back_kb())
        return
    if channel in storage.channels() or channel in storage.pending():
        await message.answer(
            i18n.t("suggest.already", lang, "ℹ️ Источник уже в базе или в очереди."),
            reply_markup=back_kb())
        return
    storage.pending().append(channel)
    await storage.save()
    await message.answer(
        i18n.t("suggest.sent", lang, "✅ Канал @{channel} отправлен модераторам.")
        .format(channel=esc(channel)),
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "src:queue")
async def queue(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    items = storage.pending()
    if not items:
        await safe_edit(call, "📥 Очередь пуста.", back_kb("menu:mod", "◀️ Назад"))
        return
    channel = items[0]
    await safe_edit(
        call,
        f"📥 <b>Очередь: {len(items)}</b>\nПроверка: @{esc(channel)}\n"
        f"https://t.me/{esc(channel)}",
        keyboards.queue_item(),
    )


@router.callback_query(F.data.in_({"src:approve", "src:reject"}))
async def decide(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    items = storage.pending()
    if not items:
        await queue(call, role)
        return
    channel = items.pop(0)
    if call.data.endswith("approve") and channel not in storage.channels():
        storage.channels().append(channel)
    await storage.save()
    await call.answer("Принято" if call.data.endswith("approve") else "Отклонено")
    await queue(call, role)


@router.callback_query(F.data == "src:list")
async def show_list(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    channels = "\n".join(f"• @{esc(item)}" for item in storage.channels()) or "— пусто —"
    feeds = "\n".join(f"• {esc(item)}" for item in storage.rss_feeds()) or "— пусто —"
    await safe_edit(
        call,
        f"📋 <b>Telegram-каналы</b>\n{channels}\n\n🌐 <b>RSS-ленты</b>\n{feeds}",
        back_kb("menu:mod", "◀️ Назад"),
    )


@router.callback_query(F.data == "src:add")
async def ask_channel(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        "➕ Пришлите юзернейм канала. Можно несколько через запятую или с новой строки.",
        back_kb("menu:mod", "Отмена"),
    )
    await state.set_state(Form.add_channel)


@router.message(Form.add_channel)
async def add_channel(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    if not roles.can_moderate_sources(role):
        return
    added, skipped = sourceedit.add(sourceedit.TELEGRAM, message.text or "")
    await storage.save()
    lines = []
    if added:
        lines.append("✅ Добавлены: " + ", ".join(f"@{esc(c)}" for c in added))
    if skipped:
        lines.append("⚠️ Пропущены: " + ", ".join(esc(s) for s in skipped))
    await message.answer("\n".join(lines) or "Ничего не добавлено",
                         reply_markup=back_kb("menu:mod", "◀️ Назад"))


@router.callback_query(F.data == "src:addrss")
async def ask_rss(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        "🌐 Пришлите адрес RSS-ленты СМИ или официального сайта "
        "(например <code>https://example.ru/rss</code>).",
        back_kb("menu:mod", "Отмена"),
    )
    await state.set_state(Form.add_rss)


@router.message(Form.add_rss)
async def add_rss(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    if not roles.can_moderate_sources(role):
        return
    added, _skipped = sourceedit.add(sourceedit.RSS, message.text or "")
    await storage.save()
    text = (
        "✅ Добавлены ленты:\n" + "\n".join(f"• {esc(u)}" for u in added)
        if added else "⚠️ Корректных адресов не найдено."
    )
    await message.answer(text, reply_markup=back_kb("menu:mod", "◀️ Назад"))


# --------------------------------------------------------------------------
#  Выгрузка и загрузка списка источников
# --------------------------------------------------------------------------

MAX_IMPORT_BYTES = 1_000_000


def _export_enabled() -> bool:
    """Выгрузка и загрузка списка источников.

    Флаг существовал с 3.3.5 и ничего не выключал. Он нужен там, где
    список источников считается служебным и его не следует выносить
    наружу даже администратору.
    """
    return features.enabled("source_export")


@router.callback_query(F.data == "src:export")
async def export_sources(call: CallbackQuery, role: str) -> None:
    if not _export_enabled():
        await call.answer("Выгрузка источников отключена.", show_alert=True)
        return
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    await call.answer("Готовлю файл…")

    payload = exporting.export_bundle(
        storage.channels(), storage.rss_feeds(), storage.pending(), config.VERSION
    )
    document = BufferedInputFile(payload, filename=exporting.export_filename(config.VERSION))
    caption = (
        "📦 <b>Источники системы «Радар»</b>\n"
        f"Каналов: <b>{len(storage.channels())}</b>, "
        f"RSS: <b>{len(storage.rss_feeds())}</b>, "
        f"в очереди: <b>{len(storage.pending())}</b>\n\n"
        "<i>Файл читается будущими версиями бота. Чтобы восстановить список — "
        "просто пришлите его сюда.</i>"
    )
    await call.message.answer_document(document, caption=caption, reply_markup=back_kb("menu:mod", "◀️ Назад"))


@router.callback_query(F.data == "src:import")
async def ask_import(call: CallbackQuery, role: str) -> None:
    if not _export_enabled():
        await call.answer("Загрузка источников отключена.", show_alert=True)
        return
    if not roles.is_admin(role):
        await call.answer("Загрузка доступна администраторам.", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        "⬆️ <b>Загрузка источников</b>\n\n"
        "Пришлите файл, выгруженный кнопкой «Скачать список». "
        "Принимаются также простой список каналов текстовым файлом и "
        "<code>db.json</code> от версий 2.x.\n\n"
        "<i>Существующие источники сохраняются — новые добавляются к ним.</i>",
        back_kb("menu:mod", "Отмена"),
    )


@router.message(F.document)
async def import_sources(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        await message.answer("⛔️ Загрузка источников доступна администраторам.")
        return

    document = message.document
    if document.file_size and document.file_size > MAX_IMPORT_BYTES:
        await message.answer("❌ Файл слишком большой (лимит 1 МБ).")
        return

    try:
        buffer = await message.bot.download(document)
        raw = buffer.read()
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"❌ Не удалось скачать файл: {esc(exc)}")
        return

    try:
        bundle = exporting.parse_bundle(raw)
    except exporting.ImportError_ as exc:
        await message.answer(f"❌ {esc(exc)}", reply_markup=back_kb("menu:mod", "◀️ Назад"))
        return

    added_channels, added_rss = exporting.merge(
        bundle, storage.channels(), storage.rss_feeds()
    )
    added_pending = 0
    for name in bundle.pending:
        if name not in storage.channels() and name not in storage.pending():
            storage.pending().append(name)
            added_pending += 1
    await storage.save()

    lines = [
        "✅ <b>Список загружен</b>",
        f"Из файла: каналов {len(bundle.channels)}, лент {len(bundle.rss)}"
        + (f" (источник: {esc(bundle.origin)})" if bundle.origin else ""),
        f"Добавлено: <b>{added_channels}</b> каналов, <b>{added_rss}</b> лент",
    ]
    if added_pending:
        lines.append(f"В очередь модерации: <b>{added_pending}</b>")
    if not (added_channels or added_rss or added_pending):
        lines.append("<i>Все источники из файла уже были в базе.</i>")
    if bundle.warnings:
        lines.append("")
        lines.append("⚠️ " + "\n⚠️ ".join(esc(item) for item in bundle.warnings[:8]))
        if len(bundle.warnings) > 8:
            lines.append(f"…и ещё {len(bundle.warnings) - 8} замечаний")

    await message.answer("\n".join(lines), reply_markup=back_kb("menu:mod", "◀️ Назад"))


# --------------------------------------------------------------------------
#  Проверка доступности источников
# --------------------------------------------------------------------------

# Итог последней проверки на пользователя: нужен, чтобы кнопка «убрать
# недоступные» работала по свежему списку, а не пересканировала всё заново.
_last_check: dict[str, list[tuple[str, str]]] = {}


@router.callback_query(F.data == "src:check")
async def check_sources(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    channels = list(storage.channels())
    feeds = list(storage.rss_feeds())
    vk_groups = list(storage.vk_groups())
    total = len(channels) + len(feeds) + len(vk_groups)
    if not total:
        await call.answer("Источников нет.", show_alert=True)
        return

    await call.answer("Начинаю проверку…")
    estimate = int(total * (sourcecheck.POLITE_PAUSE + 1.2))
    notice = await call.message.answer(
        f"🔍 Проверяю источники: <b>{total}</b>\n"
        f"<i>Займёт примерно {estimate // 60} мин {estimate % 60} с — "
        f"запросы идут с паузой, чтобы не выглядеть перебором.</i>"
    )

    last_shown = 0

    async def progress(done: int, count: int, current: str) -> None:
        # Правим сообщение не чаще, чем раз в 10 источников: Telegram
        # ограничивает частоту редактирования.
        nonlocal last_shown
        if done - last_shown < 10 and done != count:
            return
        last_shown = done
        try:
            await notice.edit_text(
                f"🔍 Проверяю источники: <b>{done}/{count}</b>\n"
                f"<i>сейчас: {esc(current)}</i>"
            )
        except Exception:  # noqa: BLE001
            pass

    report = await sourcecheck.check_all(channels, feeds, vk_groups, progress=progress)

    # Отмечаем результат в базе — по нему потом видно проблемные источники
    for item in report.statuses:
        try:
            await storage_repo_mark(item)
        except Exception:  # noqa: BLE001
            pass

    try:
        await notice.delete()
    except Exception:  # noqa: BLE001
        pass

    text = sourcecheck.render(report)
    if report.dead:
        text += "\n\n<i>Удалить недоступные можно кнопкой ниже.</i>"
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🗑 Убрать недоступные ({len(report.dead)})",
                    callback_data="src:drop_dead",
                )],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:mod")],
            ]
        )
    else:
        markup = back_kb("menu:mod", "◀️ Назад")

    _last_check[str(call.from_user.id)] = [
        (item.kind, item.ref) for item in report.dead
    ]
    await send_html(call.message.chat.id, text, markup)


async def storage_repo_mark(item) -> None:
    """Отмечает результат проверки в таблице источников."""
    from ..db import repo

    await repo.mark_source(item.kind, item.ref, error="" if item.state != "dead" else item.note)


@router.callback_query(F.data == "src:drop_dead")
async def drop_dead(call: CallbackQuery, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    dead = _last_check.get(str(call.from_user.id)) or []
    if not dead:
        await call.answer("Список устарел — запустите проверку заново.", show_alert=True)
        return

    removed = sum(1 for kind, ref in dead if sourceedit.remove(kind, ref))

    await storage.save()
    _last_check.pop(str(call.from_user.id), None)
    await call.answer(f"Удалено источников: {removed}")
    await safe_edit(
        call,
        f"🗑 Удалено недоступных источников: <b>{removed}</b>.\n"
        f"Осталось: каналов {len(storage.channels())}, лент {len(storage.rss_feeds())}.",
        back_kb("menu:mod", "◀️ Назад"),
    )


@router.message(Command("checksources"))
async def cmd_check_sources(message: Message, role: str) -> None:
    if not roles.can_moderate_sources(role):
        await message.answer("⛔️ Проверка источников доступна модераторам и выше.")
        return

    channels = list(storage.channels())
    feeds = list(storage.rss_feeds())
    total = len(channels) + len(feeds)
    if not total:
        await message.answer("Источников нет.")
        return

    notice = await message.answer(f"🔍 Проверяю источники: <b>{total}</b>…")
    report = await sourcecheck.check_all(channels, feeds, list(storage.vk_groups()))
    try:
        await notice.delete()
    except Exception:  # noqa: BLE001
        pass
    await send_html(message.chat.id, sourcecheck.render(report), back_kb("menu:mod", "◀️ Назад"))
