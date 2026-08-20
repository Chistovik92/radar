"""Журнал событий пользователя.

Функция `repo.history()` была написана давно и не вызывалась ниоткуда:
ни кнопки, ни команды, ни раздела в панели. Здесь появляется вход.

Показываем только то, что человеку действительно присылали: журнал
строится по доставкам, а не по всем событиям системы — иначе он увидел
бы аварии на другом конце города и решил, что бот шлёт лишнее.
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
from aiogram.types import CallbackQuery, Message

from .. import features, i18n
from ..textutils import esc
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.history")
router = Router(name="history")

DAYS = 30
LIMIT = 20

# Значки берём из общего словаря, а не заводим свой: иначе журнал начнёт
# помечать события не так, как их пометило само оповещение, и человек
# решит, что это разные события.
from ..matching import CATEGORY_ICONS as ICONS  # noqa: E402


async def _render(user_id: int, lang: str = "ru") -> str:
    from ..db import repo

    try:
        events = await repo.history(user_id, days=DAYS, limit=LIMIT)
    except Exception:  # noqa: BLE001
        log.exception("История событий недоступна")
        title = i18n.t("history.title", lang, "📖 Журнал")
        return f"<b>{title}</b>\n\n" + i18n.t(
            "common.error", lang,
            "Историю сейчас не получить — попробуйте позже.",
        )

    title = i18n.t("history.title", lang, "📖 Журнал")
    if not events:
        empty = i18n.t(
            "history.empty", lang,
            f"За последние {DAYS} дней вам ничего не приходило.",
        )
        note = i18n.t(
            "history.note", lang,
            "Это не значит, что бот молчал зря: значит, рядом с вашими "
            "локациями ничего не случилось.",
        )
        return f"<b>{title}</b>\n\n{empty}\n\n<i>{note}</i>"

    lines = [f"<b>{title}</b> — {DAYS}", ""]
    for event in events:
        # У события список категорий, не одна: берём первую известную,
        # чтобы значок соответствовал сути, а не порядку в списке.
        categories = getattr(event, "categories", None) or []
        icon = next((ICONS[key] for key in categories if key in ICONS), "•")
        when = event.created_at.strftime("%d.%m %H:%M")
        text = (getattr(event, "summary", "") or "").strip()
        lines.append(f"{icon} <b>{when}</b> — {esc(text[:160])}")

    if len(events) >= LIMIT:
        lines.append("")
        lines.append("<i>" + i18n.t(
            "history.trimmed", lang, f"Показаны последние {LIMIT} записей.",
        ) + "</i>")
    return "\n".join(lines)


@router.message(Command("history"))
async def cmd_history(message: Message, user: dict) -> None:
    if not features.enabled("history"):
        await message.answer("Журнал событий сейчас отключён.")
        return
    await message.answer(await _render(message.from_user.id, i18n.language_of(user)),
                         reply_markup=back_kb())


@router.callback_query(F.data == "menu:history")
async def menu_history(call: CallbackQuery, user: dict) -> None:
    if not features.enabled("history"):
        await call.answer("Журнал событий отключён.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, await _render(call.from_user.id, i18n.language_of(user)), back_kb())
