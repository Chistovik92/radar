"""Адаптер мессенджера MAX.

⚠️ НАПИСАН ПО ДОКУМЕНТАЦИИ, НА ЖИВОМ СЕРВЕРЕ НЕ ПРОВЕРЕН.

Переписан в 4.9.9.4 по действующему описанию Bot API (dev.max.ru): до этого
код был набором догадок — угадывались и адрес, и имена полей, и формат
кнопок. Теперь он повторяет документированный контракт:

* база — `https://platform-api.max.ru` (домен `botapi.max.ru` закрыт
  с октября 2025), адрес вынесен в `MAX_API_URL`;
* токен — заголовком `Authorization`, **без** префикса `Bearer`; передача
  токеном в строке запроса больше не поддерживается;
* `GET /updates` с `marker`, `limit`, `timeout`, `types`; ответ —
  `{"updates": [...], "marker": N}`, и `marker` берётся из ответа,
  а не считается самостоятельно;
* `POST /messages?chat_id=…` либо `?user_id=…`, тело — `text`,
  `attachments`, `format`, `notify`;
* `POST /answers?callback_id=…` — ответ на нажатие кнопки: без него
  у человека в интерфейсе остаётся «часики»;
* `PATCH /me` — список команд бота;
* предел 30 запросов в секунду — отсюда собственный ограничитель.

**Чего адаптер намеренно НЕ делает.** Он не подключает MAX к ядру бота:
разбор команд, роли, локации и оповещения написаны на aiogram и привязаны
к Telegram. Здесь — транспорт и встроенный ответчик (`maxbot.py`), который
честно говорит, что полноценный бот живёт в Telegram. Строить вторую
копию всей логики поверх непроверенного API было бы хуже, чем не строить
её вовсе.

**Что заведомо потребует уточнения на живом токене** — перечислено
в `docs/ROADMAP.md`, раздел «6.0 — MAX». Коротко: точная форма ответа
на callback, имя метода для команд бота (`PATCH /me` против
`PATCH /me/commands`) и то, какие HTML-теги MAX действительно понимает.
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
import time
from typing import Any, Sequence

import aiohttp

from .. import config
from ..identity import MAX, make as make_identity
from .base import EventKind, InboundEvent, Keyboard, OutboundMessage

log = logging.getLogger("radar.platform.max")

# Пределы из документации. Нарушать их незачем: ответ будет отклонён
# целиком, и человек не получит ничего вместо «почти всего».
MAX_BUTTONS = 210
MAX_ROWS = 30
PER_ROW = 7
PER_ROW_WIDE = 3        # ссылки и мини-приложения занимают больше места
RATE_LIMIT_RPS = 30

# Теги, которые оставляем при `format: "html"`. Список узкий намеренно:
# какие именно теги MAX понимает, по документации не ясно, а неизвестный
# тег — это отказ всего сообщения, а не потеря курсива.
KEEP_TAGS = {"b", "strong", "i", "em", "u", "s", "code", "pre", "a", "br"}

_TAG = re.compile(r"</?([a-zA-Z0-9-]+)[^>]*>")
_ANY_TAG = re.compile(r"<[^>]+>")


class MaxTransport:
    """Реализация протокола Transport поверх MAX Bot API."""

    name = MAX

    def __init__(self, token: str = "", base_url: str = "") -> None:
        self.token = token or config.MAX_BOT_TOKEN
        self.base_url = (base_url or config.MAX_API_URL).rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._marker: int | None = None
        self._running = False
        self._handler = None
        self._last_call = 0.0
        self._gate = asyncio.Lock()
        # Разметку выключаем на весь сеанс после первого отказа: если MAX
        # не понял наш HTML, он не поймёт его и в следующем сообщении,
        # а тревога важнее курсива.
        self._html_ok = True

    # -- служебное -------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        # Без «Bearer»: документация требует голый токен.
        return {"Authorization": self.token, "Accept": "application/json"}

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120, connect=15),
                headers=self._headers(),
            )
        return self._session

    async def _pace(self) -> None:
        """Держит предел в 30 запросов в секунду с запасом."""
        async with self._gate:
            interval = 1.0 / (RATE_LIMIT_RPS - 5)
            wait = interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def _request(self, method: str, path: str, *,
                       params: dict[str, Any] | None = None,
                       payload: dict[str, Any] | None = None
                       ) -> tuple[int, dict[str, Any]]:
        """Запрос к API. Возвращает (код, тело). Код 0 — не дошли."""
        session = await self._ensure_session()
        url = f"{self.base_url}/{path.lstrip('/')}"
        await self._pace()
        try:
            async with session.request(method, url, params=params,
                                       json=payload) as response:
                try:
                    body = await response.json(content_type=None)
                except Exception:  # noqa: BLE001
                    body = {}
                if response.status >= 400:
                    # Тело ответа в журнал пишем обрезанным и без токена:
                    # он в заголовке, а не в теле, но осторожность дешевле.
                    log.warning("MAX %s %s → HTTP %s: %s", method, path,
                                response.status, str(body)[:200])
                return response.status, body if isinstance(body, dict) else {}
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("MAX %s %s не выполнен: %s", method, path,
                        type(exc).__name__)
            return 0, {}

    # -- преобразование --------------------------------------------------

    def render(self, text: str) -> str:
        """Приводит нашу HTML-разметку к тому, что можно отдать MAX.

        Неизвестные теги срезаются, известные остаются. Если платформа
        однажды отказалась понимать разметку, дальше отдаём чистый текст.
        """
        value = text or ""
        if not self._html_ok:
            return self.plain(value)

        def keep(match: re.Match) -> str:
            return match.group(0) if match.group(1).lower() in KEEP_TAGS else ""

        return _TAG.sub(keep, value)

    @staticmethod
    def plain(text: str) -> str:
        """Совсем без разметки — запасной путь."""
        import html as html_module

        return html_module.unescape(_ANY_TAG.sub("", text or ""))

    def to_keyboard(self, keyboard: Keyboard) -> list[list[dict[str, Any]]]:
        """Кнопки в формат MAX, с соблюдением его пределов.

        Ряд длиннее допустимого не отбрасывается, а переносится: потерянная
        кнопка — это недоступное действие, и человеку неоткуда узнать,
        что оно вообще было.
        """
        result: list[list[dict[str, Any]]] = []
        total = 0
        for row in keyboard or []:
            converted: list[dict[str, Any]] = []
            for button in row:
                if button.is_link:
                    converted.append({"type": "link", "text": button.text,
                                      "url": button.url})
                else:
                    converted.append({"type": "callback", "text": button.text,
                                      "payload": button.payload or button.text})
            if not converted:
                continue
            width = PER_ROW_WIDE if any(item["type"] == "link"
                                        for item in converted) else PER_ROW
            for start in range(0, len(converted), width):
                chunk = converted[start:start + width]
                if len(result) >= MAX_ROWS or total + len(chunk) > MAX_BUTTONS:
                    log.info("MAX: часть кнопок не поместилась в предел")
                    return result
                result.append(chunk)
                total += len(chunk)
        return result

    def parse_update(self, update: dict[str, Any]) -> InboundEvent | None:
        """Событие MAX → общий вид.

        Разбираются задокументированные типы: `message_created`,
        `message_callback`, `bot_started`, `bot_added`. Остальные
        возвращают событие вида OTHER — не молчание: по журналу видно,
        что пришло что-то неучтённое.
        """
        if not isinstance(update, dict):
            return None

        kind_raw = str(update.get("update_type") or "")
        callback = update.get("callback") if isinstance(update.get("callback"), dict) else {}
        message = update.get("message") if isinstance(update.get("message"), dict) else {}
        body = message.get("body") if isinstance(message.get("body"), dict) else {}
        sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
        recipient = message.get("recipient") if isinstance(message.get("recipient"), dict) else {}

        user = callback.get("user") if isinstance(callback.get("user"), dict) else sender
        if not user:
            user = update.get("user") if isinstance(update.get("user"), dict) else {}

        chat_id = (
            recipient.get("chat_id")
            or update.get("chat_id")
            or user.get("user_id")
        )
        user_id = user.get("user_id") or chat_id
        if chat_id is None or user_id is None:
            return None

        text = str(body.get("text") or "")
        payload = str(callback.get("payload") or "")

        event = InboundEvent(
            platform=MAX,
            identity=make_identity(MAX, user_id),
            chat_id=str(chat_id),
            text=text,
            payload=payload,
            username=str(user.get("username") or user.get("name") or ""),
            message_id=str(body.get("mid") or ""),
            raw=update,
        )
        # Идентификатор нажатия нужен, чтобы ответить на него: без ответа
        # у человека в интерфейсе остаются «часики».
        if callback.get("callback_id"):
            event.args = str(callback["callback_id"])

        if kind_raw == "message_callback" or payload:
            event.kind = EventKind.CALLBACK
        elif kind_raw in ("bot_started", "bot_added"):
            event.kind = EventKind.JOINED
        elif text.startswith("/"):
            event.kind = EventKind.COMMAND
            head, _, tail = text.partition(" ")
            event.command = head[1:].split("@")[0]
            event.args = tail.strip()
        elif self._location_of(body):
            latitude, longitude = self._location_of(body)
            event.kind = EventKind.LOCATION
            event.latitude, event.longitude = latitude, longitude
        elif text:
            event.kind = EventKind.MESSAGE
        else:
            log.debug("MAX: неучтённое событие %s", kind_raw or "без типа")
        return event

    @staticmethod
    def _location_of(body: dict[str, Any]) -> tuple[float, float] | None:
        """Геопозиция из вложений сообщения, если она там есть."""
        for attachment in body.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            if attachment.get("type") != "location":
                continue
            latitude = attachment.get("latitude")
            longitude = attachment.get("longitude")
            if latitude is None or longitude is None:
                payload = attachment.get("payload") or {}
                latitude = payload.get("latitude")
                longitude = payload.get("longitude")
            if latitude is not None and longitude is not None:
                return float(latitude), float(longitude)
        return None

    # -- протокол Transport ----------------------------------------------

    async def send_text(self, user_id: str, text: str) -> bool:
        """Копия тревоги привязанному человеку (5.6): адресат — пользователь,
        а не чат, поэтому `?user_id=`, а не `?chat_id=`."""
        return await self.send(user_id, OutboundMessage(text=text), by_user=True)

    async def send(self, chat_id: str, message: OutboundMessage, *,
                   by_user: bool = False) -> bool:
        """Отправка сообщения. False — не доставлено.

        При отказе из-за разметки повторяем то же сообщение чистым
        текстом: содержание важнее оформления.
        """
        if not self.configured:
            return False

        body: dict[str, Any] = {
            "text": self.render(message.text),
            "notify": not message.silent,
        }
        if self._html_ok:
            body["format"] = "html"
        keyboard = self.to_keyboard(message.keyboard)
        if keyboard:
            body["attachments"] = [
                {"type": "inline_keyboard", "payload": {"buttons": keyboard}}
            ]

        target = {"user_id" if by_user else "chat_id": chat_id}
        status, _payload = await self._request(
            "POST", "messages", params=target, payload=body)
        if status == 200:
            return True

        if status == 400 and self._html_ok:
            # Скорее всего дело в разметке — на живом токене это первое,
            # что выяснится. Выключаем её и пробуем ещё раз.
            log.warning("MAX не принял разметку — перехожу на чистый текст")
            self._html_ok = False
            body.pop("format", None)
            body["text"] = self.plain(message.text)
            status, _payload = await self._request(
                "POST", "messages", params=target, payload=body)
            return status == 200
        return False

    async def answer_callback(self, callback_id: str, notification: str = "") -> bool:
        """Ответ на нажатие кнопки. Без него остаются «часики»."""
        if not self.configured or not callback_id:
            return False
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        status, _payload = await self._request(
            "POST", "answers", params={"callback_id": callback_id}, payload=body)
        return status == 200

    async def set_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        """Список команд бота.

        Документация упоминает и `PATCH /me`, и `PATCH /me/commands`;
        пробуем первый, при 404 — второй. Ошибка здесь не мешает работе:
        команды — удобство, а не условие.
        """
        if not self.configured:
            return
        payload = {"commands": [{"name": name, "description": text}
                                for name, text in commands]}
        status, _body = await self._request("PATCH", "me", payload=payload)
        if status == 404:
            await self._request("PATCH", "me/commands", payload=payload)

    async def whoami(self) -> dict[str, Any]:
        """Сведения о боте. Первый вызов, которым проверяется токен."""
        _status, body = await self._request("GET", "me")
        return body

    async def start(self, handler=None) -> None:
        """Long polling. Для боевой работы MAX требует webhook.

        Документация прямо называет опрос средством разработки: у него
        ограничены скорость и срок хранения событий. Webhook появится
        вместе с доменом и сертификатом — тем же, что у веб-панели.
        """
        if not self.configured:
            log.info("MAX не настроен: MAX_BOT_TOKEN пуст — адаптер не запускается")
            return

        if handler is None:
            from .maxbot import reply as handler  # встроенный ответчик

        self._handler = handler
        self._running = True

        me = await self.whoami()
        if me:
            log.info("MAX: токен принят, бот «%s»",
                     me.get("name") or me.get("username") or "?")
        else:
            log.warning("MAX: /me не ответил — проверьте MAX_BOT_TOKEN и адрес %s",
                        self.base_url)

        log.warning("Адаптер MAX запущен опросом. Реализация написана "
                    "по документации и на живом сервере не проверялась.")

        idle = 0
        while self._running:
            try:
                params: dict[str, Any] = {"limit": 100, "timeout": 30}
                if self._marker is not None:
                    params["marker"] = self._marker
                status, data = await self._request("GET", "updates", params=params)

                if status == 429:
                    idle = min(idle + 1, 6)
                    await asyncio.sleep(2 ** idle)
                    continue
                if status != 200:
                    idle = min(idle + 1, 6)
                    await asyncio.sleep(min(60, 5 * idle))
                    continue
                idle = 0

                # Маркер берём из ответа: считать его самостоятельно
                # («последний + 1») документация не предлагает, и такой
                # подсчёт однажды уже приводил к потере событий.
                marker = data.get("marker")
                if isinstance(marker, int):
                    self._marker = marker

                for update in data.get("updates") or []:
                    event = self.parse_update(update)
                    if event is None:
                        continue
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
