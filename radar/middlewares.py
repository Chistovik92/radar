"""Middleware доступа: регистрация по инвайту и отсев посторонних."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import storage

log = logging.getLogger("radar.access")


class AccessMiddleware(BaseMiddleware):
    """Пропускает только зарегистрированных; по /start join регистрирует нового."""

    def __init__(self) -> None:
        self._notified: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        uid = str(user.id)
        text = (getattr(event, "text", "") or "").strip()

        if uid not in storage.users() and text.startswith("/start") and "join" in text:
            storage.register(uid, user.username or "")
            await storage.save()
            log.info("Регистрация по инвайту: %s (@%s)", uid, user.username)

        record = storage.get_user(uid)
        if record is None:
            now = time.monotonic()
            if now - self._notified.get(user.id, 0) > 600:
                self._notified[user.id] = now
                try:
                    if isinstance(event, Message):
                        await event.answer(
                            "⛔️ Доступ к системе «Радар» закрыт.\n"
                            f"Ваш ID: <code>{user.id}</code> — передайте его администратору."
                        )
                    elif isinstance(event, CallbackQuery):
                        await event.answer("Доступ закрыт.", show_alert=True)
                except TelegramForbiddenError:
                    pass
            return None

        if user.username and record.get("username") != user.username:
            record["username"] = user.username

        data["user"] = record
        data["role"] = record.get("role", "user")
        return await handler(event, data)
