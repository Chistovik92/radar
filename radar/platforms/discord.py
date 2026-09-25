"""Адаптер Discord (с 5.5): канал сообщества, а не оповещения по адресам.

⚠️ НАПИСАН ПО ИСХОДНИКАМ discord.py, С ЖИВЫМ DISCORD НЕ ПРОВЕРЕН.

Что умеет:

* **REST** (`https://discord.com/api/v10`, заголовок `Authorization: Bot …`):
  отправка сообщений в канал, ответ на слеш-команду и нажатие кнопки,
  регистрация слеш-команд;
* **Gateway** (WebSocket): HELLO → IDENTIFY, сердцебиение с проверкой
  подтверждений, RESUME по `resume_gateway_url` после обрыва, новая
  сессия после INVALID_SESSION, переподключение по RECONNECT. Коды
  операций и закрывающие коды, после которых переподключаться бессмысленно
  (4004, 4010–4014), сверены с `discord/gateway.py`.

Почему не discord.py. Он тянет свой стек и живёт своим циклом событий;
на машине, где весь бот укладывается в 512 МБ, нужная часть — три вызова
REST и один WebSocket — пишется на уже имеющемся `aiohttp`.

Чего адаптер намеренно не делает — рассылки оповещений по адресам. Без
подтверждённой географии тревога не отправляется, а локации привязаны
к учётной записи Telegram. Discord по дорожной карте — канал сообщества:
сводки и статус системы (см. `discordbot.py`).

Пределы площадки соблюдаются переносом, а не отбрасыванием там, где это
возможно: текст режется по 2000 знаков, кнопки — по 5 в ряд и 5 рядов
на сообщение. На взаимодействие нужно ответить за 3 секунды, поэтому
ответ уходит первым действием обработчика.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import re
from typing import Any, Awaitable, Callable, Sequence

from ..identity import DISCORD, make as make_identity
from .base import EventKind, InboundEvent, Keyboard, OutboundMessage

log = logging.getLogger("radar.platform.discord")

API = "https://discord.com/api/v10"
DEFAULT_GATEWAY = "wss://gateway.discord.gg"
GATEWAY_QUERY = "/?v=10&encoding=json"

# Коды операций Gateway — как в discord/gateway.py.
DISPATCH = 0
HEARTBEAT = 1
IDENTIFY = 2
RESUME = 6
RECONNECT = 7
INVALID_SESSION = 9
HELLO = 10
HEARTBEAT_ACK = 11

# Закрытия, после которых переподключение ничего не даст: неверный токен,
# неверный шард, запрещённые намерения. Бот останавливает адаптер и пишет
# в журнал, а не долбит Discord в цикле.
FATAL_CLOSE = {4004, 4010, 4011, 4012, 4013, 4014}

# Намерения: только GUILDS. Слеш-команды и кнопки приходят событием
# INTERACTION_CREATE без каких-либо намерений; содержимое чужих сообщений
# (Message Content Intent) боту не нужно и не запрашивается.
INTENTS = 1 << 0

# Ответ на взаимодействие.
CHANNEL_MESSAGE = 4
UPDATE_MESSAGE = 7
EPHEMERAL = 1 << 6

# Типы взаимодействий.
APPLICATION_COMMAND = 2
MESSAGE_COMPONENT = 3

TEXT_LIMIT = 2000
BUTTONS_PER_ROW = 5
ROWS_PER_MESSAGE = 5
CUSTOM_ID_LIMIT = 100
LABEL_LIMIT = 80


# --------------------------------------------------------------------------
#  Разметка и кнопки — отдельно от сети, проверяются офлайн
# --------------------------------------------------------------------------

def render(text: str) -> str:
    """Общая HTML-разметка бота → Markdown Discord."""
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"</?(b|strong)>", "**", text)
    text = re.sub(r"</?(i|em)>", "*", text)
    text = re.sub(r"</?(u|ins)>", "__", text)
    text = re.sub(r"</?(s|strike|del)>", "~~", text)
    text = re.sub(r"<pre>(.*?)</pre>", r"```\n\1\n```", text, flags=re.S)
    text = re.sub(r"</?code>", "`", text)
    text = re.sub(r'<a href="([^"]+)">(.*?)</a>', r"[\2](\1)", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def split_text(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """Режет текст по пределу Discord, стараясь не рвать строки."""
    text = text or ""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts.append(text)
    return parts


def components(keyboard: Keyboard) -> list[list[dict[str, Any]]]:
    """Клавиатура → ряды компонентов, по сообщениям.

    Возвращает список: для каждого сообщения — его ряды. Больше пяти
    кнопок в ряду переносятся на следующий ряд, больше пяти рядов —
    в следующее сообщение: потерянная кнопка — это действие, которое
    человек не найдёт.
    """
    buttons: list[list[dict[str, Any]]] = []
    for row in keyboard or []:
        converted = []
        for button in row:
            label = (button.text or "·")[:LABEL_LIMIT]
            if button.is_link:
                converted.append({"type": 2, "style": 5, "label": label,
                                  "url": button.url})
            elif button.payload:
                if len(button.payload) > CUSTOM_ID_LIMIT:
                    log.warning("Discord: данные кнопки длиннее %s — кнопка пропущена",
                                CUSTOM_ID_LIMIT)
                    continue
                converted.append({"type": 2, "style": 2, "label": label,
                                  "custom_id": button.payload})
        for start in range(0, len(converted), BUTTONS_PER_ROW):
            buttons.append(converted[start:start + BUTTONS_PER_ROW])
    rows = [{"type": 1, "components": row} for row in buttons if row]
    return [rows[start:start + ROWS_PER_MESSAGE]
            for start in range(0, len(rows), ROWS_PER_MESSAGE)] or [[]]


def payloads(message: OutboundMessage) -> list[dict[str, Any]]:
    """Сообщение бота → тела запросов Discord, по одному на сообщение."""
    texts = split_text(render(message.text))
    groups = components(message.keyboard)
    count = max(len(texts), len(groups))
    bodies = []
    for index in range(count):
        body: dict[str, Any] = {
            # Упоминания выключены: текст сводки не должен никого звать.
            "allowed_mentions": {"parse": []},
        }
        if index < len(texts) and texts[index]:
            body["content"] = texts[index]
        # Кнопки — к последнему куску текста, дальше — отдельными сообщениями.
        group_index = index - (len(texts) - 1)
        if 0 <= group_index < len(groups) and groups[group_index]:
            body["components"] = groups[group_index]
        if "content" not in body and "components" not in body:
            continue
        if message.silent:
            body["flags"] = 1 << 12   # SUPPRESS_NOTIFICATIONS
        bodies.append(body)
    return bodies


def parse_interaction(data: dict[str, Any]) -> InboundEvent | None:
    """Событие INTERACTION_CREATE → общий вид InboundEvent."""
    user = (data.get("member") or {}).get("user") or data.get("user") or {}
    user_id = str(user.get("id") or "")
    if not user_id:
        return None
    event = InboundEvent(
        platform=DISCORD,
        identity=make_identity(DISCORD, user_id),
        chat_id=str(data.get("channel_id") or ""),
        username=str(user.get("username") or ""),
        raw=data,
    )
    kind = data.get("type")
    payload = data.get("data") or {}
    if kind == APPLICATION_COMMAND:
        event.kind = EventKind.COMMAND
        event.command = str(payload.get("name") or "")
        event.text = f"/{event.command}"
    elif kind == MESSAGE_COMPONENT:
        event.kind = EventKind.CALLBACK
        event.payload = str(payload.get("custom_id") or "")
    else:
        return None
    return event


# --------------------------------------------------------------------------
#  Транспорт
# --------------------------------------------------------------------------

Handler = Callable[[InboundEvent, "DiscordTransport"], Awaitable[None]]


class GatewayClosed(Exception):
    def __init__(self, code: int | None, resume: bool = True) -> None:
        super().__init__(f"Gateway закрыт: {code}")
        self.code = code
        self.resume = resume


class DiscordTransport:
    """Реализация `Transport` для Discord."""

    name = DISCORD

    def __init__(self, token: str, handler: Handler | None = None) -> None:
        self.token = (token or "").strip()
        self.handler = handler
        self.session: Any = None
        self.application_id = ""
        self.session_id = ""
        self.sequence: int | None = None
        self.resume_url = ""
        self._stopping = False
        self._acked = True
        self._beat: asyncio.Task | None = None
        self._delay = 1.0

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bot {self.token}",
                "User-Agent": "DiscordBot (https://github.com/Chistovik92/radar, 5.5)"}

    async def _session(self) -> Any:
        import aiohttp

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    # --- REST ---

    async def request(self, method: str, path: str, body: Any = None,
                      *, attempts: int = 3) -> Any:
        """Запрос к REST. 429 — ждём сколько сказано и повторяем."""
        session = await self._session()
        for _ in range(attempts):
            async with session.request(method, f"{API}{path}", json=body,
                                       headers=self._headers()) as response:
                text = await response.text()
                if response.status == 429:
                    try:
                        wait = float(json.loads(text).get("retry_after", 1))
                    except (ValueError, AttributeError):
                        wait = 1.0
                    log.warning("Discord: предел запросов, жду %.1f с", wait)
                    await asyncio.sleep(min(wait, 60))
                    continue
                if response.status >= 400:
                    log.warning("Discord: %s %s → HTTP %s", method, path.split("?")[0],
                                response.status)
                    return None
                return json.loads(text) if text else {}
        return None

    async def send(self, chat_id: str, message: OutboundMessage) -> bool:
        ok = True
        for body in payloads(message):
            result = await self.request("POST", f"/channels/{chat_id}/messages", body)
            ok = ok and result is not None
        return ok

    async def respond(self, event: InboundEvent, message: OutboundMessage,
                      *, update: bool = False, ephemeral: bool = False) -> bool:
        """Ответ на взаимодействие. Обязателен в течение 3 секунд.

        В ответ помещается только первое сообщение; остальное (если текст
        длиннее 2000 знаков) уходит обычными сообщениями в тот же канал.
        """
        raw = event.raw or {}
        bodies = payloads(message) or [{"content": "…"}]
        first, rest = bodies[0], bodies[1:]
        if ephemeral:
            first["flags"] = first.get("flags", 0) | EPHEMERAL
        result = await self.request(
            "POST", f"/interactions/{raw.get('id')}/{raw.get('token')}/callback",
            {"type": UPDATE_MESSAGE if update else CHANNEL_MESSAGE, "data": first})
        for body in rest:
            await self.request("POST", f"/channels/{event.chat_id}/messages", body)
        return result is not None

    async def set_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        if not self.application_id:
            me = await self.request("GET", "/oauth2/applications/@me")
            self.application_id = str((me or {}).get("id") or "")
        if not self.application_id:
            log.warning("Discord: не узнал id приложения — слеш-команды не заданы")
            return
        body = [{"name": name, "description": description[:100], "type": 1}
                for name, description in commands]
        await self.request("PUT", f"/applications/{self.application_id}/commands", body)

    def render(self, text: str) -> str:
        return render(text)

    # --- Gateway ---

    async def gateway_url(self) -> str:
        info = await self.request("GET", "/gateway/bot")
        return str((info or {}).get("url") or DEFAULT_GATEWAY)

    def identify(self) -> dict[str, Any]:
        return {"op": IDENTIFY, "d": {
            "token": self.token, "intents": INTENTS,
            "properties": {"os": "linux", "browser": "radar", "device": "radar"},
        }}

    def resume(self) -> dict[str, Any]:
        return {"op": RESUME, "d": {"token": self.token, "session_id": self.session_id,
                                    "seq": self.sequence}}

    async def _heartbeat(self, ws: Any, interval: float) -> None:
        # Первое сердцебиение — со случайной задержкой, как требует Discord,
        # чтобы тысячи переподключившихся ботов не били в один момент.
        await asyncio.sleep(interval * random.random())
        while not ws.closed:
            if not self._acked:
                log.warning("Discord: нет подтверждения сердцебиения — переподключаюсь")
                await ws.close(code=4000)
                return
            self._acked = False
            await ws.send_json({"op": HEARTBEAT, "d": self.sequence})
            await asyncio.sleep(interval)

    async def handle(self, ws: Any, message: dict[str, Any]) -> None:
        """Одно сообщение Gateway. Вынесено отдельно ради офлайн-проверки."""
        op = message.get("op")
        if message.get("s") is not None:
            self.sequence = message["s"]
        if op == HELLO:
            interval = float(message["d"]["heartbeat_interval"]) / 1000
            self._acked = True
            if self._beat is not None:
                self._beat.cancel()
            self._beat = asyncio.ensure_future(self._heartbeat(ws, interval))
            await ws.send_json(self.resume() if self.session_id else self.identify())
        elif op == HEARTBEAT_ACK:
            self._acked = True
        elif op == HEARTBEAT:
            await ws.send_json({"op": HEARTBEAT, "d": self.sequence})
        elif op == RECONNECT:
            raise GatewayClosed(None, resume=True)
        elif op == INVALID_SESSION:
            if not message.get("d"):
                self.session_id, self.sequence, self.resume_url = "", None, ""
            await asyncio.sleep(1 + random.random() * 4)
            raise GatewayClosed(None, resume=bool(message.get("d")))
        elif op == DISPATCH:
            await self._dispatch(message.get("t") or "", message.get("d") or {})

    async def _dispatch(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "READY":
            self.session_id = str(data.get("session_id") or "")
            self.resume_url = str(data.get("resume_gateway_url") or "")
            self.application_id = str((data.get("application") or {}).get("id") or "")
            self._delay = 1.0
            log.info("Discord: сессия открыта")
        elif kind == "RESUMED":
            self._delay = 1.0
        elif kind == "INTERACTION_CREATE":
            event = parse_interaction(data)
            if event is not None and self.handler is not None:
                try:
                    await self.handler(event, self)
                except Exception:  # noqa: BLE001
                    log.exception("Discord: сбой обработчика взаимодействия")

    async def _run_once(self) -> None:
        session = await self._session()
        base = self.resume_url if self.session_id and self.resume_url else await self.gateway_url()
        try:
            async with session.ws_connect(base.rstrip("/") + GATEWAY_QUERY,
                                          heartbeat=None, max_msg_size=0) as ws:
                async for frame in ws:
                    if frame.type.name == "TEXT":
                        await self.handle(ws, json.loads(frame.data))
                    elif frame.type.name in ("CLOSE", "CLOSED", "ERROR"):
                        break
                raise GatewayClosed(ws.close_code)
        finally:
            if self._beat is not None:
                self._beat.cancel()
                self._beat = None

    async def start(self) -> None:
        """Цикл Gateway: переподключается сам, пока не остановят."""
        if not self.configured:
            log.warning("Discord: токен не задан — адаптер не запускается")
            return
        while not self._stopping:
            try:
                await self._run_once()
            except GatewayClosed as closed:
                if closed.code in FATAL_CLOSE:
                    log.error("Discord закрыл соединение кодом %s — проверьте токен "
                              "и намерения бота; адаптер остановлен", closed.code)
                    return
                if not closed.resume:
                    self.session_id, self.sequence = "", None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("Discord: обрыв Gateway (%s), переподключаюсь",
                            type(exc).__name__)
            if self._stopping:
                break
            await asyncio.sleep(self._delay)
            self._delay = min(self._delay * 2, 60)

    async def stop(self) -> None:
        self._stopping = True
        if self.session is not None:
            await self.session.close()
