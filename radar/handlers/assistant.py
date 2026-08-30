"""ИИ-ассистент в диалоге. Доступен начиная с роли «модератор».

Роутер подключается последним: перехватывает любой необработанный текст.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from collections import deque

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import ai, keyboards, roles
from ..textutils import esc, md_to_html, split_text, strip_tags
from ..tg import back_kb, safe_edit, send_html

log = logging.getLogger("radar.assistant")
router = Router(name="assistant")

MAX_HISTORY = 8
_history: dict[str, deque] = {}

def history_of(uid: str) -> deque:
    if uid not in _history:
        _history[uid] = deque(maxlen=MAX_HISTORY)
    return _history[uid]


async def run(message: Message, question: str) -> None:
    from .. import provider

    uid = str(message.from_user.id)
    # Раньше проверялся только клиент Gemini: с ключом любого другого
    # провайдера ассистент отвечал «не задан GEMINI_API_KEY», хотя
    # отвечать было кому.
    if not ai.ENABLED and not provider.available():
        await message.answer(
            "❌ ИИ-ассистент недоступен: не задан ни один ключ провайдера. "
            "Заведите его в разделе ключей — например <code>GEMINI_API_KEY</code>."
        )
        return

    placeholder = await message.answer("🧠 <i>Думаю…</i>")
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:  # noqa: BLE001
        pass

    history = history_of(uid)
    try:
        answer = await ai.assistant(list(history), question)
    except ai.AIError as exc:
        log.warning("Ассистент: %s", exc)
        try:
            await placeholder.edit_text(f"❌ <b>Ошибка ИИ:</b> {esc(exc)}")
        except TelegramBadRequest:
            pass
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Неожиданная ошибка ассистента")
        try:
            await placeholder.edit_text(f"❌ Неожиданная ошибка: {esc(exc)}")
        except TelegramBadRequest:
            pass
        return

    history.append(ai.user_turn(question))
    history.append(ai.model_turn(answer))

    chunks = split_text(md_to_html(answer))
    try:
        await placeholder.edit_text(chunks[0])
    except TelegramBadRequest:
        try:
            await placeholder.edit_text(strip_tags(chunks[0]), parse_mode=None)
        except TelegramBadRequest:
            pass
    for chunk in chunks[1:]:
        await send_html(message.chat.id, chunk)


@router.callback_query(F.data == "menu:ai")
async def open_assistant(call: CallbackQuery, role: str) -> None:
    if not roles.can_use_assistant(role):
        await call.answer("Ассистент доступен с роли «Модератор».", show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        "🧠 <b>ИИ-ассистент</b>\n\nНапишите вопрос обычным сообщением или используйте "
        "<code>/ai вопрос</code>.\n<code>/aireset</code> — очистить контекст диалога.",
        back_kb(),
    )


@router.message(Command("ai"))
async def cmd_ai(message: Message, state: FSMContext, role: str) -> None:
    if not roles.can_use_assistant(role):
        await message.answer("⛔️ Ассистент доступен начиная с роли «Модератор».")
        return
    await state.clear()
    question = re.sub(r"^/ai(@\w+)?\s*", "", message.text or "", flags=re.I).strip()
    if not question:
        await message.answer(
            "Напишите вопрос после команды, например:\n"
            "<code>/ai составь оповещение об отключении воды</code>"
        )
        return
    await run(message, question)


@router.message(Command("aireset"))
async def cmd_reset(message: Message, role: str) -> None:
    if not roles.can_use_assistant(role):
        return
    _history.pop(str(message.from_user.id), None)
    await message.answer("🧹 Контекст диалога очищен.")


@router.message(F.text)
async def free_chat(message: Message, state: FSMContext, role: str, user: dict) -> None:
    if await state.get_state() is not None:
        await message.answer("⏳ Завершите текущее действие или отправьте /cancel.")
        return

    text = (message.text or "").strip()
    if text.startswith("/"):
        await message.answer("❓ Неизвестная команда. /menu — меню, /help — справка.")
        return

    if not roles.can_use_assistant(role):
        await message.answer(
            "Воспользуйтесь меню — или отправьте геопозицию, чтобы добавить локацию.",
            reply_markup=keyboards.main_menu(role, user),
        )
        return

    await run(message, text)
