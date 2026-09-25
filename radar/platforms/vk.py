"""Адаптер ВКонтакте как мессенджера (с 5.6, раздел 7.0 дорожной карты).

⚠️ СВЕРЕН С ИСХОДНИКАМИ vkbottle, С ЖИВЫМ СООБЩЕСТВОМ НЕ ПРОВЕРЕН.

Путь проверенный и бесплатный: бот — это сообщество с ключом доступа
(«Управление → Работа с API → Ключи доступа», право «сообщения»),
события приходят через Bots Long Poll API — без входящего адреса:

* `groups.getLongPollServer(group_id)` → `server`, `key`, `ts`;
* `POST {server}?act=a_check&key=…&ts=…&wait=25` → `{"ts", "updates"}`
  или `{"failed": N}`: 1 — история устарела, взять новый `ts` из ответа;
  2 — ключ истёк, запросить сервер, `ts` оставить; 3 — информация потеряна,
  запросить сервер целиком (как в `vkbottle/polling/base.py`);
* `messages.send(peer_id, random_id, message)` — ответ и копия тревоги.

Ключ сообщества уходит телом POST-запроса, а не строкой адреса: адрес
попадает в журналы прокси, тело — нет.

Разметки ВК в сообщениях бота не понимает, поэтому HTML общего текста
превращается в чистый текст: ссылка — «текст (адрес)».
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import html
import logging
import re
import secrets as pysecrets
import time
from typing import Any, Awaitable, Callable, Sequence

from ..identity import make as make_identity
from .base import EventKind, InboundEvent, OutboundMessage

log = logging.getLogger("radar.platform.vk")

API = "https://api.vk.com/method"
VERSION = "5.199"
WAIT = 25
TEXT_LIMIT = 4096
# Предел сообщества — 20 запросов в секунду; держимся с запасом.
RATE = 15

HISTORY_OUTDATED = 1
KEY_EXPIRED = 2
INFORMATION_LOST = 3

VK = "vk"


class VkError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"VK {code}: {message}")
        self.code = code


def render(text: str) -> str:
    """HTML общего текста → чистый текст ВК."""
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r'<a href="([^"]+)">(.*?)</a>', r"\2 (\1)", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def split_text(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text or not parts:
        parts.append(text)
    return parts


def parse_update(update: dict[str, Any]) -> InboundEvent | None:
    """Событие Long Poll → общий вид. Берём только личные сообщения."""
    if update.get("type") != "message_new":
        return None
    message = (update.get("object") or {}).get("message") or {}
    from_id = message.get("from_id")
    peer_id = message.get("peer_id")
    # Беседы (peer_id ≥ 2·10⁹) и сообщения от сообществ (from_id < 0)
    # пропускаем: бот работает только в личной переписке.
    if not from_id or from_id < 0 or not peer_id or peer_id >= 2_000_000_000:
        return None
    text = str(message.get("text") or "").strip()
    event = InboundEvent(platform=VK, identity=make_identity(VK, str(from_id)),
                         chat_id=str(peer_id), text=text, raw=update,
                         message_id=str(message.get("id") or ""))
    # Геопозиция (5.7): `geo.coordinates` — как в описании объекта
    # сообщения ВК и в моделях vkbottle (`Geo.coordinates`).
    coordinates = ((message.get("geo") or {}).get("coordinates") or {})
    try:
        latitude = float(coordinates["latitude"])
        longitude = float(coordinates["longitude"])
    except (KeyError, TypeError, ValueError):
        latitude = longitude = None
    if latitude is not None and longitude is not None:
        event.kind = EventKind.LOCATION
        event.latitude, event.longitude = latitude, longitude
    elif text.startswith("/"):
        command, _, args = text[1:].partition(" ")
        event.kind, event.command, event.args = EventKind.COMMAND, command.lower(), args.strip()
    else:
        event.kind = EventKind.MESSAGE
    return event


Handler = Callable[[InboundEvent, "VkTransport"], Awaitable[None]]


class VkTransport:
    """Реализация `Transport` для ВКонтакте."""

    name = VK

    def __init__(self, token: str, group_id: str | int,
                 handler: Handler | None = None) -> None:
        self.token = (token or "").strip()
        self.group_id = str(group_id or "").strip().lstrip("-")
        self.handler = handler
        self.session: Any = None
        self._stopping = False
        self._sent: list[float] = []

    @property
    def configured(self) -> bool:
        return bool(self.token and self.group_id.isdigit())

    async def _session(self) -> Any:
        import aiohttp

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=WAIT + 15))
        return self.session

    async def _throttle(self) -> None:
        now = time.monotonic()
        self._sent = [moment for moment in self._sent if now - moment < 1]
        if len(self._sent) >= RATE:
            await asyncio.sleep(1 - (now - self._sent[0]))
        self._sent.append(time.monotonic())

    async def call(self, method: str, **params: Any) -> Any:
        """Метод API. Ошибка ВК приходит с HTTP 200 и полем error."""
        await self._throttle()
        session = await self._session()
        data = {key: str(value) for key, value in params.items() if value is not None}
        data.update(access_token=self.token, v=VERSION)
        async with session.post(f"{API}/{method}", data=data) as response:
            payload = await response.json(content_type=None)
        error = payload.get("error") if isinstance(payload, dict) else None
        if error:
            raise VkError(int(error.get("error_code") or 0), str(error.get("error_msg") or ""))
        return payload.get("response") if isinstance(payload, dict) else None

    async def send(self, chat_id: str, message: OutboundMessage) -> bool:
        ok = True
        for part in split_text(render(message.text)):
            if not part:
                continue
            try:
                await self.call("messages.send", peer_id=chat_id,
                                random_id=pysecrets.randbits(31), message=part,
                                dont_parse_links=1)
            except VkError as exc:
                # 901 — человек не разрешил сообществу писать ему первым.
                log.warning("VK: сообщение не доставлено (%s)", exc.code)
                ok = False
            except Exception as exc:  # noqa: BLE001
                log.warning("VK: сбой отправки: %s", type(exc).__name__)
                ok = False
        return ok

    async def send_text(self, peer_id: str, text: str) -> bool:
        """Для зеркала тревог: текст → сообщение."""
        return await self.send(peer_id, OutboundMessage(text=text))

    async def set_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        # У ВК нет списка команд бота — подсказка идёт текстом /help.
        return None

    def render(self, text: str) -> str:
        return render(text)

    # --- Long Poll ---

    async def server(self) -> dict[str, Any]:
        return dict(await self.call("groups.getLongPollServer", group_id=self.group_id) or {})

    async def poll(self, server: dict[str, Any]) -> dict[str, Any]:
        session = await self._session()
        async with session.post(server["server"], data={
            "act": "a_check", "key": server["key"], "ts": server["ts"], "wait": str(WAIT),
        }) as response:
            return await response.json(content_type=None)

    async def step(self, server: dict[str, Any]) -> dict[str, Any]:
        """Один запрос Long Poll и разбор ответа. Возвращает сервер для следующего."""
        payload = await self.poll(server)
        failed = payload.get("failed")
        if failed == HISTORY_OUTDATED:
            return dict(server, ts=payload.get("ts", server["ts"]))
        if failed == KEY_EXPIRED:
            fresh = await self.server()
            return dict(fresh, ts=server["ts"])
        if failed:
            return await self.server()
        for update in payload.get("updates") or []:
            event = parse_update(update)
            if event is not None and self.handler is not None:
                try:
                    await self.handler(event, self)
                except Exception:  # noqa: BLE001
                    log.exception("VK: сбой обработчика сообщения")
        return dict(server, ts=payload.get("ts", server["ts"]))

    async def start(self) -> None:
        if not self.configured:
            log.warning("VK: не заданы VK_BOT_TOKEN и VK_BOT_GROUP_ID — адаптер не запускается")
            return
        delay = 1.0
        server: dict[str, Any] = {}
        while not self._stopping:
            try:
                if not server:
                    server = await self.server()
                server = await self.step(server)
                delay = 1.0
                continue
            except VkError as exc:
                if exc.code in (5, 15, 27):
                    # Неверный ключ, нет доступа, ключ сообщества без прав —
                    # переподключение этого не исправит.
                    log.error("VK: %s — проверьте ключ сообщества и включённый "
                              "Long Poll; адаптер остановлен", exc)
                    return
                log.warning("VK: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("VK: обрыв Long Poll (%s)", type(exc).__name__)
            server = {}
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def stop(self) -> None:
        self._stopping = True
        if self.session is not None:
            await self.session.close()
