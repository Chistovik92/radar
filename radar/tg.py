"""Экземпляр бота и безопасные обёртки отправки сообщений."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from . import config
from .textutils import split_text, strip_tags

log = logging.getLogger("radar.tg")

def _build_bot() -> Bot:
    """Экземпляр бота. При заданном TELEGRAM_API_SERVER — через свой сервер.

    Собственный Bot API Server снимает предел отправки с 50 МБ до 2 ГБ.
    Режим is_local означает, что сервер берёт файлы прямо с диска, минуя
    передачу по HTTP, — для видео это на порядок быстрее.
    """
    properties = DefaultBotProperties(parse_mode=ParseMode.HTML)
    if not config.TELEGRAM_API_SERVER:
        return Bot(token=config.BOT_TOKEN, default=properties)

    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    log.info("Использую собственный Bot API Server: %s", config.TELEGRAM_API_SERVER)
    session = AiohttpSession(
        api=TelegramAPIServer.from_base(
            config.TELEGRAM_API_SERVER, is_local=config.TELEGRAM_API_LOCAL
        )
    )
    return Bot(token=config.BOT_TOKEN, session=session, default=properties)


bot = _build_bot()
dp = Dispatcher(storage=MemoryStorage())

def back_kb(target: str = "menu:main", title: str = "🏠 В главное меню") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=title, callback_data=target)]]
    )


async def send_html(
    chat_id: int | str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Отправляет длинный HTML-текст частями, переживая ошибки разметки и лимиты."""
    chunks = split_text(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        for attempt in range(2):
            try:
                await bot.send_message(int(chat_id), chunk, reply_markup=markup)
                break
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                log.info("Пользователь %s недоступен (бот заблокирован)", chat_id)
                return False
            except TelegramBadRequest as exc:
                log.warning("Ошибка разметки (%s), отправляю обычным текстом", exc)
                try:
                    await bot.send_message(
                        int(chat_id), strip_tags(chunk), parse_mode=None, reply_markup=markup
                    )
                except Exception:  # noqa: BLE001
                    log.exception("Не удалось отправить сообщение %s", chat_id)
                break
            except Exception:  # noqa: BLE001
                log.exception("Сбой отправки сообщения %s", chat_id)
                return False
        await asyncio.sleep(0.05)
    return True


async def safe_edit(
    call: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    """edit_text, устойчивый к «message is not modified» и слишком длинным текстам."""
    chunks = split_text(text)
    try:
        await call.message.edit_text(chunks[0], reply_markup=markup if len(chunks) == 1 else None)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        try:
            await call.message.answer(chunks[0], reply_markup=markup if len(chunks) == 1 else None)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось обновить сообщение")
            return
    for index, chunk in enumerate(chunks[1:], start=1):
        await send_html(
            call.message.chat.id, chunk, markup if index == len(chunks) - 1 else None
        )
