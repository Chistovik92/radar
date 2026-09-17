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


# Сколько помнить, что человеку уже отвечали. Значения совпадают
# с интервалами повторного ответа ниже: запись, пережившая свой интервал,
# ни на что не влияет и только занимает память.
NOTIFY_EVERY = 600.0
MAINTENANCE_EVERY = 300.0
LANGUAGE_EVERY = 3600.0

# Потолок на случай наплыва: чистка идёт по времени, но если писать боту
# будут быстрее, чем стареют записи, словарь не должен расти без предела.
MEMORY_CAP = 2000


def _prune(store: dict[int, float], ttl: float, now: float) -> None:
    """Выбрасывает отметки, которые уже ничего не держат.

    До 4.9.8.14 эти словари не чистились никогда: запись заводил КАЖДЫЙ
    посторонний, написавший боту, — то есть кто угодно. Рост медленный,
    но ничем не ограниченный и снаружи, а бот живёт на одноплатнике.
    """
    stale = [key for key, stamp in store.items() if now - stamp > ttl]
    for key in stale:
        store.pop(key, None)
    if len(store) > MEMORY_CAP:
        # Наплыв: оставляем самых свежих, остальные всё равно получат
        # ответ заново — это вежливость, а не состояние системы.
        keep = sorted(store.items(), key=lambda pair: pair[1])[-MEMORY_CAP:]
        store.clear()
        store.update(keep)


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

        # Групповые чаты проходят мимо всего этого. Иначе бот, добавленный
        # в группу, здоровается с каждым участником «Доступ закрыт» раз
        # в десять минут, регистрирует знакомых как своих пользователей
        # и спрашивает у них язык прямо в чате. Модерацией занимается
        # отдельный роутер, и ему ни запись пользователя, ни роль
        # «Радара» не нужны: права он спрашивает у самого Telegram.
        chat = getattr(event, "chat", None) or getattr(
            getattr(event, "message", None), "chat", None)
        if chat is not None and getattr(chat, "type", "private") != "private":
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
            _prune(self._notified, NOTIFY_EVERY, now)
            if now - self._notified.get(user.id, 0) > NOTIFY_EVERY:
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
            _prune(self._maintenance_notified, MAINTENANCE_EVERY, now)
            if now - self._maintenance_notified.get(user.id, 0) > MAINTENANCE_EVERY:
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
        _prune(self._language_asked, LANGUAGE_EVERY, now)
        if now - self._language_asked.get(key, 0) < LANGUAGE_EVERY:
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
