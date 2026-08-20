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

from . import features, i18n, roles, storage

log = logging.getLogger("radar.access")

def _is_language_choice(event: TelegramObject) -> bool:
    return isinstance(event, CallbackQuery) and str(event.data or "").startswith("lng:")


class AccessMiddleware(BaseMiddleware):
    """Пропускает только зарегистрированных; по /start join регистрирует нового."""

    def __init__(self) -> None:
        self._notified: dict[int, float] = {}
        self._maintenance_notified: dict[int, float] = {}
        self._language_asked: dict[int, float] = {}

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

        # Язык ещё не выбран — спрашиваем один раз и пропускаем дальше.
        # Пустое поле есть и у нового человека, и у того, кто пользовался
        # ботом до появления выбора: вопрос для обоих одинаковый.
        # Сам выбор языка (lng:*) не перехватываем, иначе получилось бы
        # кольцо: вопрос → нажатие → снова вопрос.
        if i18n.needs_choice(record) and not _is_language_choice(event):
            await self._ask_language(event)

        return await handler(event, data)

    async def _ask_language(self, event: TelegramObject) -> None:
        now = time.monotonic()
        key = getattr(getattr(event, "from_user", None), "id", 0)
        if now - self._language_asked.get(key, 0) < 3600:
            return
        self._language_asked[key] = now

        from .handlers.language import ASK_TEXT, language_keyboard

        try:
            if isinstance(event, Message):
                await event.answer(ASK_TEXT, reply_markup=language_keyboard())
            elif isinstance(event, CallbackQuery) and event.message is not None:
                await event.message.answer(ASK_TEXT, reply_markup=language_keyboard())
        except TelegramForbiddenError:
            pass
        except Exception:  # noqa: BLE001
            log.debug("Не удалось спросить про язык")
