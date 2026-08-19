"""Сокращение ссылок — суперадминистратору.

Публичным сервис намеренно не сделан: короткая ссылка, которую может
завести кто угодно, притягивает фишинг и спам, а расплачивается за это
домен — вместе со всем, что на нём живёт, включая ссылки в оповещениях
об опасности.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from .. import roles, shortener
from ..db import repo
from ..textutils import esc
from ..tg import back_kb

log = logging.getLogger("radar.handlers.shortlink")
router = Router(name="shortlink")


@router.message(Command("short"))
async def cmd_short(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Сокращение ссылок доступно суперадминистратору.")
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
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Доступно суперадминистратору.")
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
