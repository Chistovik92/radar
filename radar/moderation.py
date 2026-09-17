"""Правила модерации групп: решение отдельно от Telegram.

Здесь нет ни aiogram, ни сети — только «текст плюс состояние автора
плюс настройки чата» → решение. Так правила можно прогнать таблицей
случаев в офлайн-тестах, а ошибка в них обнаруживается на тесте,
а не на живом человеке, которого забанили ни за что.

Почему решение возвращается, а не исполняется: удаление, мут и бан —
разные права в Telegram, и у бота их может не быть. Исполнитель
(`radar/handlers/group.py`) разбирается с правами и отказами, правила
об этом не знают вовсе.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# Действия по возрастанию строгости.
NONE = "none"
DELETE = "delete"
WARN = "warn"
MUTE = "mute"
BAN = "ban"

# Ссылка считается спамом начиная с этого уровня проверки ссылок
# (multitool/linkcheck). «attention» не трогаем: там слишком много
# обычных ссылок, и удалять их значило бы мешать разговору.
SPAM_LEVELS = ("suspect", "danger")

_URL_RE = re.compile(r"https?://\S+|\bt\.me/\S+|\b[\w-]+\.(?:ru|com|net|org|io)\b",
                     re.I)


@dataclass
class Settings:
    """Настройки одного чата. Значения по умолчанию — осознанно мягкие:
    свежеподключённый бот не должен начать с раздачи банов."""

    delete_spam_links: bool = True
    links_from_newcomers: bool = True   # новичкам ссылки нельзя вовсе
    stopwords: list[str] = field(default_factory=list)
    antiflood: bool = True
    flood_messages: int = 6             # столько сообщений
    flood_seconds: int = 10             # за столько секунд — флуд
    warns_before_mute: int = 3
    mute_minutes: int = 60
    warns_before_ban: int = 5
    newcomer_hours: int = 24            # сколько человек считается новичком


@dataclass
class Author:
    """Что известно об авторе сообщения на момент решения."""

    user_id: int
    joined_ago_hours: float = 999.0     # давно в чате — не новичок
    warns: int = 0
    is_admin: bool = False

    @property
    def newcomer(self) -> bool:
        return self.joined_ago_hours < 24.0


@dataclass
class Decision:
    """Что сделать и почему. Причина уходит в журнал и в сообщение чату:
    молчаливое удаление выглядит как поломка чата, а не как модерация."""

    action: str = NONE
    reason: str = ""
    delete_message: bool = False

    @property
    def acts(self) -> bool:
        return self.action != NONE or self.delete_message


def extract_urls(text: str) -> list[str]:
    """Ссылки из текста — включая t.me и голые домены: спам чаще всего
    приходит именно так, без схемы."""
    return _URL_RE.findall(text or "")


def _link_level(url: str) -> str:
    """Уровень ссылки по общей проверке проекта. Вторую реализацию
    заводить нечего — она уже написана и покрыта тестами."""
    try:
        from multitool.linkcheck.analyze import analyze

        return analyze(url).level
    except Exception:  # noqa: BLE001
        # Разбор ссылки не должен ронять модерацию: не смогли — не судим.
        return "ok"


class FloodTracker:
    """Счётчик частоты сообщений. В памяти намеренно: переживать
    перезапуск ему незачем, а таблица ради десяти секунд — это запись
    на диск на каждое сообщение чата."""

    def __init__(self) -> None:
        self._seen: dict[tuple[int, int], list[float]] = {}

    def hit(self, chat_id: int, user_id: int, window: int,
            now: float | None = None) -> int:
        moment = time.monotonic() if now is None else now
        key = (chat_id, user_id)
        recent = [stamp for stamp in self._seen.get(key, [])
                  if moment - stamp < window]
        recent.append(moment)
        self._seen[key] = recent
        return len(recent)

    def forget(self, chat_id: int, user_id: int) -> None:
        self._seen.pop((chat_id, user_id), None)


def decide(text: str, author: Author, settings: Settings,
           flood_count: int = 0) -> Decision:
    """Одно решение по одному сообщению.

    Порядок проверок — от дешёвых к дорогим и от мягких к строгим.
    Администраторы чата не модерируются вовсе: бот не должен спорить
    с теми, кто его назначил.
    """
    if author.is_admin:
        return Decision()

    lowered = (text or "").lower()

    # Стоп-слова — самое дешёвое и самое однозначное.
    for word in settings.stopwords:
        needle = word.strip().lower()
        if needle and needle in lowered:
            return _escalate(author, settings,
                             f"стоп-слово «{word.strip()}»", delete=True)

    # Ссылки.
    urls = extract_urls(text)
    if urls:
        if settings.links_from_newcomers and author.newcomer:
            return _escalate(author, settings,
                             "ссылка от новичка", delete=True)
        if settings.delete_spam_links:
            for url in urls:
                if _link_level(url) in SPAM_LEVELS:
                    return _escalate(author, settings,
                                     "подозрительная ссылка", delete=True)

    # Флуд — считается снаружи, здесь только порог.
    if settings.antiflood and flood_count > settings.flood_messages:
        return _escalate(author, settings, "флуд", delete=False)

    return Decision()


def _escalate(author: Author, settings: Settings, reason: str,
              delete: bool) -> Decision:
    """Лестница наказаний. Считаем по УЖЕ накопленным предупреждениям
    плюс текущее: иначе первое нарушение выглядело бы как нулевое."""
    warns = author.warns + 1

    if warns >= settings.warns_before_ban:
        return Decision(BAN, f"{reason}; предупреждений: {warns}", delete)
    if warns >= settings.warns_before_mute:
        return Decision(MUTE, f"{reason}; предупреждений: {warns}", delete)
    return Decision(WARN, f"{reason}; предупреждение {warns}", delete)


def describe(decision: Decision, settings: Settings) -> str:
    """Человеческая формулировка для сообщения в чат."""
    if decision.action == WARN:
        return f"⚠️ Предупреждение: {decision.reason}"
    if decision.action == MUTE:
        return (f"🔇 Ограничение на {settings.mute_minutes} мин: "
                f"{decision.reason}")
    if decision.action == BAN:
        return f"⛔️ Блокировка: {decision.reason}"
    if decision.delete_message:
        return f"🧹 Удалено: {decision.reason}"
    return ""
