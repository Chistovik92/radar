"""Проверка участников Discord-сервера (с 5.9.5): логика без сети.

Честно о том, что тут возможно. У Discord нет капчи для ботов, и надёжно
доказать, что за аккаунтом человек, нельзя. Реально — поднять цену
автоматического входа. Здесь три ступени, от дешёвой к дорогой:

1. **Кнопка и вопрос.** Новый участник видит только канал проверки; по
   кнопке «Я человек» открывается окно с вопросом (сумма, слово наоборот,
   число букв), три попытки. Останавливает примитивные скрипты, которые
   умеют только вступать и нажимать.
2. **Привязка через /link** (общий аккаунт 5.7). Аккаунт Discord, уже
   связанный с проверенным Telegram, ВК или MAX, проходит без вопроса:
   «живость» берётся от уже пройденной проверки.
3. **Проверка при вступлении** — возраст аккаунта (из самого id: он
   содержит время создания) и имя с приглашением на другой сервер. Нужно
   намерение «Server Members» — привилегированное, его включают в Developer
   Portal; без него шаг 3 и тайм-аут тихо отключаются, а кнопка работает.

Внешняя капча (Turnstile/hCaptcha) на домене панели не делалась: она
требует живого домена, ключей сервиса и привязки аккаунта через OAuth2.
Состояние живёт в памяти: после перезапуска кто не успел, пройдёт кнопку
заново — так проще и безопаснее, чем хранить ответы на вопросы.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Callable

DISCORD_EPOCH_MS = 1420070400000

MAX_ATTEMPTS = 3
# Сколько живёт выданный вопрос: человек открыл окно и ушёл пить чай.
QUESTION_TTL = 600

# Слова для вопросов: короткие, без ё, чтобы не спорить о написании.
WORDS = ("слон", "мост", "река", "дом", "лес", "ветер", "поле", "окно",
         "стол", "море", "гора", "звезда", "облако", "ключ", "город")

ADVERTISING = re.compile(
    r"(discord\.gg|discord\.com/invite|dsc\.gg|t\.me/|https?://|free\s*nitro|"
    r"@everyone|18\+)", re.IGNORECASE)


def account_created(user_id: int | str) -> float:
    """Когда создан аккаунт, секунды Unix: время зашито в старшие биты id."""
    return ((int(user_id) >> 22) + DISCORD_EPOCH_MS) / 1000.0


def account_age_days(user_id: int | str, now: float | None = None) -> float:
    return ((now if now is not None else time.time()) - account_created(user_id)) / 86400.0


def suspicious_name(*names: str) -> bool:
    """Имя или отображаемое имя — реклама, а не имя."""
    return any(ADVERTISING.search(name or "") for name in names)


# --------------------------------------------------------------------------
#  Вопросы
# --------------------------------------------------------------------------

def normalize(answer: str) -> str:
    return re.sub(r"\s+", "", (answer or "").strip().lower())


def make_question(rng: random.Random | None = None) -> tuple[str, str]:
    """(вопрос, ожидаемый ответ). Вопрос ≤ 45 знаков: таков предел подписи
    поля в окне Discord."""
    rng = rng or random
    kind = rng.choice(("sum", "diff", "reverse", "letters"))
    if kind == "sum":
        a, b = rng.randint(2, 19), rng.randint(2, 19)
        return f"Сколько будет {a} + {b}?", str(a + b)
    if kind == "diff":
        a = rng.randint(10, 29)
        b = rng.randint(2, 9)
        return f"Сколько будет {a} − {b}?", str(a - b)
    word = rng.choice(WORDS)
    if kind == "reverse":
        return f"Напишите слово «{word}» наоборот", word[::-1]
    return f"Сколько букв в слове «{word}»?", str(len(word))


# --------------------------------------------------------------------------
#  Состояние проверки
# --------------------------------------------------------------------------

OK = "ok"
WRONG = "wrong"
LOCKED = "locked"
EXPIRED = "expired"
NONE = "none"


@dataclass
class Pending:
    joined: float
    answer: str = ""
    issued: float = 0.0
    attempts: int = 0


class Gate:
    """Кто вошёл и ещё не прошёл проверку. По (сервер, человек)."""

    def __init__(self, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None) -> None:
        self.clock = clock
        self.rng = rng
        self.pending: dict[tuple[str, str], Pending] = {}

    def joined(self, guild: str, user: str) -> None:
        self.pending.setdefault((guild, user), Pending(joined=self.clock()))

    def passed(self, guild: str, user: str) -> None:
        self.pending.pop((guild, user), None)

    def ask(self, guild: str, user: str) -> str:
        """Выдаёт новый вопрос; число попыток при этом не сбрасывается."""
        entry = self.pending.setdefault((guild, user), Pending(joined=self.clock()))
        question, entry.answer = make_question(self.rng)
        entry.issued = self.clock()
        return question

    def check(self, guild: str, user: str, answer: str) -> str:
        entry = self.pending.get((guild, user))
        if entry is None or not entry.answer:
            return NONE
        if self.clock() - entry.issued > QUESTION_TTL:
            entry.answer = ""
            return EXPIRED
        if entry.attempts >= MAX_ATTEMPTS:
            return LOCKED
        if normalize(answer) == normalize(entry.answer):
            self.pending.pop((guild, user), None)
            return OK
        entry.attempts += 1
        entry.answer = ""          # на ту же попытку — новый вопрос, не подбор
        return LOCKED if entry.attempts >= MAX_ATTEMPTS else WRONG

    def attempts_left(self, guild: str, user: str) -> int:
        entry = self.pending.get((guild, user))
        return MAX_ATTEMPTS if entry is None else max(0, MAX_ATTEMPTS - entry.attempts)

    def overdue(self, minutes: int) -> list[tuple[str, str]]:
        """Не прошедшие за отведённое время. 0 — тайм-аута нет."""
        if minutes <= 0:
            return []
        limit = self.clock() - minutes * 60
        return [key for key, entry in self.pending.items() if entry.joined < limit]

    def locked(self) -> list[tuple[str, str]]:
        return [key for key, entry in self.pending.items()
                if entry.attempts >= MAX_ATTEMPTS]


# --------------------------------------------------------------------------
#  Проверка при вступлении
# --------------------------------------------------------------------------

@dataclass
class Verdict:
    action: str          # allow | kick
    reason: str = ""


def evaluate(user_id: int | str, username: str = "", global_name: str = "",
             min_days: int = 0, now: float | None = None) -> Verdict:
    """Решение по вступившему: пропустить к кнопке или исключить сразу."""
    if min_days > 0 and account_age_days(user_id, now) < min_days:
        days = account_age_days(user_id, now)
        return Verdict("kick", f"аккаунту {days:.1f} дн., нужно не меньше {min_days}")
    if suspicious_name(username, global_name):
        return Verdict("kick", "в имени реклама или приглашение")
    return Verdict("allow")
