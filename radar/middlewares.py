"""Middleware доступа: регистрация по инвайту и отсев посторонних."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import features, roles, storage

log = logging.getLogger("radar.access")

class AccessMiddleware(BaseMiddleware):
    """Пропускает только зарегистрированных; по /start join регистрирует нового."""

    def __init__(self) -> None:
        self._notified: dict[int, float] = {}
        self._maintenance_notified: dict[int, float] = {}

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

        # Доверенный контакт SOS открывает бота по ссылке ?start=sos_<код>.
        # Регистрируем его и отмечаем подтверждённым — иначе Telegram
        # не позволит боту написать ему первым при тревоге.
        if text.startswith("/start") and "sos_" in text:
            from . import sos

            invite = text.split("sos_", 1)[1].split()[0].strip()
            found = sos.find_by_invite(storage.users(), invite)
            if found is not None:
                owner, _contact = found
                if uid not in storage.users():
                    storage.register(uid, user.username or "")
                owner_data = storage.get_user(owner)
                if owner_data is not None:
                    sos.confirm_by_invite(owner_data, invite, uid)
                    await storage.save(owner)
                await storage.save(uid)
                log.info("Контакт SOS подтверждён: %s для %s", uid, owner)

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

        role = record.get("role", "user")

        # Режим обслуживания. Суперадминистратор проходит: иначе он не сможет
        # выключить режим из самого бота и останется без единственного пульта.
        if features.enabled("maintenance") and not roles.is_superadmin(role):
            now = time.monotonic()
            if now - self._maintenance_notified.get(user.id, 0) > 300:
                self._maintenance_notified[user.id] = now
                try:
                    if isinstance(event, Message):
                        await event.answer(
                            "🛠 <b>Идут технические работы</b>\n\n"
                            "Оповещения временно приостановлены. "
                            "Бот сообщит, когда работа возобновится."
                        )
                    elif isinstance(event, CallbackQuery):
                        await event.answer(
                            "🛠 Идут технические работы.", show_alert=True
                        )
                except TelegramForbiddenError:
                    pass
            return None

        data["user"] = record
        data["role"] = role
        return await handler(event, data)
