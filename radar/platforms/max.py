"""Адаптер мессенджера MAX.

⚠️ РЕАЛИЗОВАНО, НО НЕ ПРОВЕРЕНО В РАБОТЕ.

Код написан по документации MAX Bot API и повторяет структуру рабочего
Telegram-адаптера, но ни один запрос не выполнялся против живого сервера:
для этого нужен токен, а он выдаётся только после регистрации приложения
и верификации владельца (юрлицо, ИП или самозанятый РФ).

Что заведомо потребует уточнения при первом запуске:

* **Базовый адрес.** В документации встречаются `platform-api.max.ru`
  и `platform-api2.max.ru`. Значение вынесено в `MAX_API_URL`.
* **Имена полей.** Ниже разбираются оба варианта, встречающиеся в примерах:
  `chat_id` и `chat.id`, `text` и `message.text`, `payload` и `callback_data`.
* **Разметка.** Полный HTML MAX не поддерживает, поэтому `render`
  срезает теги, оставляя чистый текст.
* **Long polling** годится для проверки, но для боевой работы MAX требует
  webhook, а он у нас появится вместе с белым IP.

Пока функция `platform_max` выключена по умолчанию; включать её стоит
только для испытаний.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Sequence

import aiohttp

from .. import config
from ..identity import MAX, make as make_identity
from .base import Button, EventKind, InboundEvent, Keyboard, OutboundMessage

log = logging.getLogger("radar.platform.max")

_TAG = re.compile(r"<[^>]+>")


class MaxTransport:
    """Реализация протокола Transport поверх MAX Bot API."""

    name = MAX

    def __init__(self, token: str = "", base_url: str = "") -> None:
        self.token = token or config.MAX_BOT_TOKEN
        self.base_url = (base_url or config.MAX_API_URL).rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._offset = 0
        self._running = False
        self._handler = None

    # -- служебное -------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                headers=self._headers(),
            )
        return self._session

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = await self._ensure_session()
        url = f"{self.base_url}/{path.lstrip('/')}"
        async with session.post(url, json=payload) as response:
            body = await response.text()
            if response.status != 200:
                log.warning("MAX %s → HTTP %s: %s", path, response.status, body[:200])
                return {}
            try:
                return await response.json(content_type=None)
            except Exception:  # noqa: BLE001
                log.warning("MAX %s вернул не JSON: %s", path, body[:200])
                return {}

    # -- преобразование --------------------------------------------------

    def render(self, text: str) -> str:
        """HTML-разметку MAX не принимает — отдаём чистый текст."""
        import html as html_module

        without_tags = _TAG.sub("", text or "")
        return html_module.unescape(without_tags)

    def to_keyboard(self, keyboard: Keyboard) -> list[list[dict[str, Any]]]:
        """Кнопки Telegram → формат MAX: callback_data становится payload."""
        result: list[list[dict[str, Any]]] = []
        for row in keyboard or []:
            converted: list[dict[str, Any]] = []
            for button in row:
                if button.is_link:
                    converted.append(
                        {"type": "link", "text": button.text, "url": button.url}
                    )
                else:
                    converted.append(
                        {
                            "type": "callback",
                            "text": button.text,
                            "payload": button.payload or button.text,
                        }
                    )
            if converted:
                result.append(converted)
        return result

    def parse_update(self, update: dict[str, Any]) -> InboundEvent | None:
        """Приводит событие MAX к общему виду.

        Имена полей в примерах документации расходятся, поэтому проверяются
        оба варианта: плоский `chat_id` и вложенный `chat.id`.
        """
        if not isinstance(update, dict):
            return None

        kind_raw = str(update.get("update_type") or update.get("type") or "")
        message = update.get("message") or {}
        if not isinstance(message, dict):
            message = {}

        chat = message.get("chat") or update.get("chat") or {}
        chat_id = (
            message.get("chat_id")
            or update.get("chat_id")
            or (chat.get("id") if isinstance(chat, dict) else None)
        )
        if chat_id is None:
            return None

        sender = message.get("from") or message.get("sender") or update.get("user") or {}
        user_id = sender.get("user_id") or sender.get("id") or chat_id
        username = str(sender.get("username") or sender.get("name") or "")

        text = str(message.get("text") or update.get("text") or "")
        payload = str(
            update.get("payload")
            or message.get("payload")
            or update.get("callback", {}).get("payload", "")
            if isinstance(update.get("callback"), dict)
            else update.get("payload") or message.get("payload") or ""
        )

        event = InboundEvent(
            platform=MAX,
            identity=make_identity(MAX, user_id),
            chat_id=str(chat_id),
            text=text,
            payload=payload,
            username=username,
            message_id=str(message.get("mid") or message.get("message_id") or ""),
            raw=update,
        )

        if payload or "callback" in kind_raw:
            event.kind = EventKind.CALLBACK
        elif text.startswith("/"):
            event.kind = EventKind.COMMAND
            head, _, tail = text.partition(" ")
            event.command = head[1:].split("@")[0]
            event.args = tail.strip()
        elif message.get("location") or update.get("location"):
            location = message.get("location") or update.get("location") or {}
            event.kind = EventKind.LOCATION
            event.latitude = location.get("latitude") or location.get("lat")
            event.longitude = location.get("longitude") or location.get("lon")
        elif "bot_added" in kind_raw or "joined" in kind_raw:
            event.kind = EventKind.JOINED
        elif text:
            event.kind = EventKind.MESSAGE

        return event

    # -- протокол Transport ----------------------------------------------

    async def send(self, chat_id: str, message: OutboundMessage) -> bool:
        if not self.configured:
            return False

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": self.render(message.text),
        }
        keyboard = self.to_keyboard(message.keyboard)
        if keyboard:
            payload["attachments"] = [
                {"type": "inline_keyboard", "payload": {"buttons": keyboard}}
            ]

        result = await self._post("messages/send", payload)
        return bool(result)

    async def set_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        if not self.configured:
            return
        await self._post(
            "me",
            {"commands": [{"name": name, "description": text} for name, text in commands]},
        )

    async def start(self, handler=None) -> None:
        """Long polling. Для боевой работы MAX требует webhook."""
        if not self.configured:
            log.info("MAX не настроен: MAX_BOT_TOKEN пуст — адаптер не запускается")
            return

        self._handler = handler
        self._running = True
        log.warning(
            "Запускаю адаптер MAX в тестовом режиме (long polling). "
            "Реализация не проверялась на живом сервере."
        )

        session = await self._ensure_session()
        while self._running:
            try:
                url = f"{self.base_url}/updates"
                params = {"offset": self._offset, "timeout": 30}
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        await asyncio.sleep(5)
                        continue
                    data = await response.json(content_type=None)

                for update in data.get("updates") or []:
                    marker = update.get("update_id") or update.get("marker")
                    if isinstance(marker, int):
                        self._offset = marker + 1
                    event = self.parse_update(update)
                    if event is not None and self._handler is not None:
                        try:
                            await self._handler(event, self)
                        except Exception:  # noqa: BLE001
                            log.exception("Ошибка обработки события MAX")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Сбой опроса MAX")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        if self._session is not None and not self._session.closed:
            await self._session.close()
