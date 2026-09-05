"""Сокращение ссылок — администрации.

Публичным сервис намеренно не сделан: короткая ссылка, которую может
завести кто угодно, притягивает фишинг и спам, а расплачивается за это
домен — вместе со всем, что на нём живёт, включая ссылки в оповещениях
об опасности.

С 4.9.3 это привилегия роли «администратор» и выше, а не только
суперадминистратора: ссылка без срока годности с именем владельца —
ровно то, за что роль и существует. Автоссылки подборок живут
в той же таблице и видны всем администраторам.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import roles, shortener
from ..db import repo
from ..states import Form
from ..textutils import esc
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.shortlink")
router = Router(name="shortlink")


def _denied() -> str:
    return "⛔️ Сокращение ссылок доступно администратору и выше."


def _not_configured_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ К управлению", callback_data="menu:manage"),
    ]])


def _section_kb(total: int) -> InlineKeyboardMarkup:
    """Клавиатура раздела «Ссылки». total — сколько их сейчас."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Сократить ссылку",
                              callback_data="short:new")],
    ]
    if total:
        rows.append([InlineKeyboardButton(text="📋 Список ссылок",
                                          callback_data="short:list")])
        rows.append([InlineKeyboardButton(text="🗑 Очистить все",
                                          callback_data="short:clearask")])
    rows.append([InlineKeyboardButton(text="◀️ К управлению",
                                      callback_data="menu:manage")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("short"))
async def cmd_short(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        await message.answer(_denied())
        return

    if not shortener.enabled():
        await message.answer(
            "🔗 <b>Сокращение ссылок не настроено</b>\n\n"
            "Задайте <code>SHORT_BASE_URL</code> в разделе ключей — адрес, "
            "на котором открыта веб-панель. Например: "
            "<code>https://example.ru</code>\n\n"
            "Пока адрес не задан, сокращение отключено: короткая ссылка "
            "в никуда хуже длинной рабочей.",
            reply_markup=back_kb(),
        )
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Укажите ссылку: <code>/short https://пример.рф/страница</code>",
            reply_markup=back_kb(),
        )
        return

    url = parts[1].strip()
    if not shortener.valid(url):
        await message.answer(
            "Это не похоже на ссылку. Нужен полный адрес со схемой "
            "<code>http://</code> или <code>https://</code>.",
            reply_markup=back_kb(),
        )
        return

    code = shortener.code_for(url)
    try:
        await repo.save_short_link(code, url, message.from_user.id)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось сохранить короткую ссылку")
        await message.answer("Не удалось сохранить ссылку — смотрите журнал.")
        return

    short = shortener.short_url(code)
    await message.answer(
        f"🔗 <code>{esc(short)}</code>\n\n<i>{esc(url[:200])}</i>",
        reply_markup=back_kb(),
    )


@router.message(Command("shorts"))
async def cmd_shorts(message: Message, role: str) -> None:
    """Последние сокращения и число переходов."""
    if not roles.is_admin(role):
        await message.answer(_denied())
        return

    try:
        rows = await repo.short_link_stats(15)
    except Exception:  # noqa: BLE001
        log.exception("Статистика ссылок недоступна")
        await message.answer("Статистика недоступна — смотрите журнал.")
        return

    if not rows:
        await message.answer("Сокращённых ссылок пока нет.", reply_markup=back_kb())
        return

    lines = ["🔗 <b>Последние ссылки</b>", ""]
    for row in rows:
        lines.append(
            f"<code>{esc(row['code'])}</code> — переходов: {row['hits']}\n"
            f"  <i>{esc(str(row['url'])[:90])}</i>"
        )
    await message.answer("\n".join(lines), reply_markup=back_kb())


# --------------------------------------------------------------------------
#  Очистка (с 4.9.3)
# --------------------------------------------------------------------------
#
# Ссылки бессрочные, и накопившиеся — от разовых сокращений, от прошлых
# рассылок — со временем превращают таблицу в свалку. Чистить по одной
# из бота неудобно: здесь их не видно целиком. Поэтому в боте — только
# «удалить все», а выборочная чистка — на странице «Ссылки» веб-панели.

@router.message(Command("shortclear"))
async def cmd_shortclear(message: Message, role: str) -> None:
    if not roles.is_admin(role):
        await message.answer(_denied())
        return

    try:
        total = len(await repo.short_link_list())
    except Exception:  # noqa: BLE001
        log.exception("Список ссылок недоступен")
        await message.answer("Список ссылок недоступен — смотрите журнал.")
        return

    if not total:
        await message.answer("Сокращённых ссылок и так нет.", reply_markup=back_kb())
        return

    await message.answer(
        "🔗 <b>Удалить все сокращённые ссылки?</b>\n\n"
        f"Сейчас их <b>{total}</b>. Разосланные в старых сообщениях "
        "перестанут открываться. Автоссылки подборок появятся снова "
        "при следующем выпуске.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить все",
                                  callback_data="short:clearall")],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="menu:main")],
        ]),
    )


@router.callback_query(F.data == "short:clearall")
async def clear_all(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Доступно администратору и выше.", show_alert=True)
        return

    try:
        removed = await repo.clear_short_links()
    except Exception:  # noqa: BLE001
        log.exception("Очистка ссылок не удалась")
        await call.answer("Не удалось — смотрите журнал.", show_alert=True)
        return

    log.info("Очищено коротких ссылок: %d", removed)
    await call.answer(f"Удалено: {removed}")
    await call.message.edit_text(
        f"✅ Сокращённые ссылки удалены: <b>{removed}</b>.\n"
        "Выборочно их можно чистить на странице «Ссылки» веб-панели.",
        reply_markup=back_kb("menu:manage", "◀️ К управлению"),
    )


# --------------------------------------------------------------------------
#  Раздел «Ссылки» в управлении (с 4.9.3.2)
# --------------------------------------------------------------------------
#
# До этого раздел жил только командами /short, /shorts, /shortclear —
# о них надо было знать заранее. Управление собирает все служебные
# разделы под одной кнопкой, и ссылки — не исключение.

@router.callback_query(F.data == "short:menu")
async def section_menu(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Доступно администратору и выше.", show_alert=True)
        return
    await call.answer()

    if not shortener.enabled():
        await safe_edit(
            call,
            "🔗 <b>Ссылки</b>\n\n"
            "Сокращение не настроено: задайте <code>SHORT_BASE_URL</code> "
            "в разделе ключей — адрес, на котором открыта веб-панель.",
            _not_configured_kb(),
        )
        return

    try:
        total = len(await repo.short_link_list())
    except Exception:  # noqa: BLE001
        log.exception("Список ссылок недоступен")
        total = -1

    lines = [
        "🔗 <b>Ссылки</b>", "",
        "Сокращённые ссылки: без срока годности, с именем владельца.",
        f"Сейчас их: <b>{total}</b>." if total >= 0 else "Список недоступен.",
        "",
        f"Команды: /short &lt;адрес&gt;, /shorts, /shortclear.",
        "Выборочная чистка — на странице «Ссылки» веб-панели.",
    ]
    await safe_edit(call, "\n".join(lines), _section_kb(max(total, 0)))


@router.callback_query(F.data == "short:new")
async def ask_url(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Доступно администратору и выше.", show_alert=True)
        return
    if not shortener.enabled():
        await call.answer("Сокращение не настроено.", show_alert=True)
        return

    await call.answer()
    await state.set_state(Form.short_link)
    await safe_edit(
        call,
        "➕ <b>Сокращение ссылки</b>\n\n"
        "Пришлите полный адрес одним сообщением — должен начинаться "
        "с <code>http://</code> или <code>https://</code>.\n"
        "<i>/cancel — отмена.</i>",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Отмена", callback_data="short:menu"),
        ]]),
    )


@router.message(Form.short_link)
async def take_url(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    if not roles.is_admin(role):
        await message.answer(_denied())
        return
    if not shortener.valid(text):
        await message.answer(
            "Это не похоже на ссылку. Нужен полный адрес со схемой "
            "<code>http://</code> или <code>https://</code> — попробуйте ещё раз.",
        )
        await state.set_state(Form.short_link)
        return

    code = shortener.code_for(text)
    try:
        await repo.save_short_link(code, text, message.from_user.id)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось сохранить короткую ссылку")
        await message.answer("Не удалось сохранить ссылку — смотрите журнал.",
                             reply_markup=back_kb("short:menu", "◀️ К ссылкам"))
        return

    short = shortener.short_url(code)
    log.info("Сокращена ссылка: %s", code)
    await message.answer(
        f"🔗 <code>{esc(short)}</code>\n\n<i>{esc(text[:200])}</i>",
        reply_markup=back_kb("short:menu", "◀️ К ссылкам"),
    )


@router.callback_query(F.data == "short:list")
async def section_list(call: CallbackQuery, role: str) -> None:
    if not roles.is_admin(role):
        await call.answer("Доступно администратору и выше.", show_alert=True)
        return
    await call.answer()

    await _show_list(call)


async def _show_list(call: CallbackQuery) -> None:
    try:
        rows = await repo.short_link_stats(15)
    except Exception:  # noqa: BLE001
        log.exception("Статистика ссылок недоступна")
        await safe_edit(call, "Статистика недоступна — смотрите журнал.",
                        back_kb("short:menu", "◀️ К ссылкам"))
        return

    if not rows:
        await safe_edit(call, "Сокращённых ссылок пока нет.",
                        back_kb("short:menu", "◀️ К ссылкам"))
        return

    lines = ["🔗 <b>Последние ссылки</b>", ""]
    for row in rows:
        lines.append(
            f"<code>{esc(row['code'])}</code> — переходов: {row['hits']}\n"
            f"  <i>{esc(str(row['url'])[:90])}</i>"
        )
    lines.append("")
    lines.append("Выборочная чистка — на странице «Ссылки» веб-панели.")
    await safe_edit(call, "\n".join(lines), back_kb("short:menu", "◀️ К ссылкам"))


@router.callback_query(F.data == "short:clearask")
async def section_clear_ask(call: CallbackQuery, role: str) -> None:
    """Подтверждение очистки из раздела: возврат ведёт назад в раздел."""
    if not roles.is_admin(role):
        await call.answer("Доступно администратору и выше.", show_alert=True)
        return
    await call.answer()

    try:
        total = len(await repo.short_link_list())
    except Exception:  # noqa: BLE001
        log.exception("Список ссылок недоступен")
        await safe_edit(call, "Список ссылок недоступен — смотрите журнал.",
                        back_kb("short:menu", "◀️ К ссылкам"))
        return

    if not total:
        await safe_edit(call, "Сокращённых ссылок и так нет.",
                        back_kb("short:menu", "◀️ К ссылкам"))
        return

    await safe_edit(
        call,
        "🔗 <b>Удалить все сокращённые ссылки?</b>\n\n"
        f"Сейчас их <b>{total}</b>. Разосланные в старых сообщениях "
        "перестанут открываться. Автоссылки подборок появятся снова "
        "при следующем выпуске.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить все",
                                  callback_data="short:clearall")],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="short:menu")],
        ]),
    )
