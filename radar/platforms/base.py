"""Единый формат событий и ответов, общий для всех мессенджеров.

Ядро системы — разбор новостей, сопоставление с локациями, роли, погода —
не должно знать, откуда пришло сообщение. Адаптер каждой платформы приводит
входящее событие к `InboundEvent`, а исходящий ответ `OutboundMessage`
переводит в вызовы своего API.

Соответствие понятий, из-за которого абстракция и нужна:

| Понятие          | Telegram (aiogram)      | MAX Bot API              |
|------------------|-------------------------|--------------------------|
| Чат              | message.chat.id (int)   | chat_id (str/int)        |
| Текст            | message.text            | message.text             |
| Кнопки           | InlineKeyboardMarkup    | массив массивов keyboard |
| Данные кнопки    | callback_data           | payload                  |
| Событие          | Update                  | update с полем type      |
| Разметка         | HTML / MarkdownV2       | ограниченная, см. адаптер|
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence

from ..identity import Identity


class EventKind(str, Enum):
    MESSAGE = "message"      # обычное текстовое сообщение
    COMMAND = "command"      # сообщение, начинающееся со слэша
    CALLBACK = "callback"    # нажатие кнопки
    LOCATION = "location"    # геопозиция
    DOCUMENT = "document"    # присланный файл
    JOINED = "joined"        # бот добавлен в чат
    OTHER = "other"


@dataclass
class InboundEvent:
    """Входящее событие в платформенно-независимом виде."""

    platform: str
    identity: Identity
    chat_id: str
    kind: EventKind = EventKind.OTHER
    text: str = ""
    command: str = ""
    args: str = ""
    payload: str = ""                 # данные нажатой кнопки
    latitude: float | None = None
    longitude: float | None = None
    document_name: str = ""
    document_size: int = 0
    username: str = ""
    message_id: str = ""
    raw: Any = None                   # исходный объект платформы

    @property
    def key(self) -> str:
        return self.identity.key


@dataclass
class Button:
    """Кнопка, не привязанная к платформе."""

    text: str
    payload: str = ""     # для callback-кнопок
    url: str = ""         # для кнопок-ссылок

    @property
    def is_link(self) -> bool:
        return bool(self.url)


Keyboard = Sequence[Sequence[Button]]


@dataclass
class OutboundMessage:
    """Ответ бота в платформенно-независимом виде."""

    text: str = ""
    keyboard: Keyboard = field(default_factory=list)
    persistent: Keyboard = field(default_factory=list)  # закреплённые кнопки
    image: bytes | None = None
    image_name: str = "image.png"
    document: bytes | None = None
    document_name: str = "file.bin"
    edit: bool = False                # заменить предыдущее сообщение
    disable_preview: bool = True
    silent: bool = False              # без звука: тихие часы


class Transport(Protocol):
    """Контракт адаптера мессенджера.

    Реализации: `telegram.TelegramTransport` (4.0) и `max.MaxTransport` (4.2).
    Новый мессенджер добавляется реализацией этого протокола — ядро не меняется.
    """

    name: str

    async def start(self) -> None:
        """Подключиться и начать получать события."""

    async def stop(self) -> None:
        """Корректно завершить работу."""

    async def send(self, chat_id: str, message: OutboundMessage) -> bool:
        """Отправить сообщение. False — доставить не удалось."""

    async def set_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        """Установить список команд в интерфейсе мессенджера."""

    def render(self, text: str) -> str:
        """Привести общую HTML-разметку к возможностям платформы."""
