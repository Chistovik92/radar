"""Объявления в группы от имени бота: правила отдельно от отправки.

Суперадминистратор пишет в администрируемую группу прямо из раздела
«Чаты». Сообщение уходит **от имени бота** — для участников это голос
системы, а не частное письмо, и цена ошибки соответствующая: опечатку
уже не отозвать, а прочитают её все.

Поэтому здесь, без сети и aiogram, живёт всё, что можно проверить
до отправки: длина, пустота, разметка и итоговый вид объявления. Сама
отправка и разбор отказов Telegram — в `radar/handlers/chats.py`.

Что намеренно НЕ делается:

* объявление не уходит без подтверждения — сначала показывается так,
  как его увидят в группе;
* текст не переписывается за автора: правится только то, что иначе
  не дойдёт (пустая строка, перебор длины, сломанная разметка).
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

# Предел Telegram на текст сообщения — 4096 символов. Берём с запасом:
# к тексту добавляется подпись, а разметка считается вместе с тегами.
MAX_LENGTH = 3500

# Сколько ждать подтверждения. Забытый черновик не должен уйти в группу
# через сутки, когда автор уже не помнит, что писал.
DRAFT_TTL = 600

# Теги, которые Telegram понимает в HTML. Остальное экранируется:
# неизвестный тег — это не разметка, а «Bad Request» на отправке,
# то есть объявление, не ушедшее никуда.
ALLOWED_TAGS = frozenset({
    "b", "strong", "i", "em", "u", "s", "strike", "del",
    "a", "code", "pre", "blockquote", "span", "tg-spoiler",
})

_TAG_RE = re.compile(r"</?([a-zA-Z0-9-]+)(?:\s[^>]*)?/?>")


@dataclass
class Draft:
    """Подготовленное объявление, ждущее подтверждения."""

    chat_id: int
    title: str
    text: str
    created: float = field(default_factory=time.time)

    def expired(self, now: float | None = None) -> bool:
        moment = now if now is not None else time.time()
        return moment - self.created > DRAFT_TTL


def unsupported_tags(text: str) -> list[str]:
    """Теги, которых Telegram не знает. Пустой список — разметка годная."""
    found = {
        match.group(1).lower() for match in _TAG_RE.finditer(text or "")
    }
    return sorted(found - ALLOWED_TAGS)


def validate(text: str) -> tuple[bool, str]:
    """Годится ли текст к отправке. Возвращает (годится, объяснение)."""
    body = (text or "").strip()
    if not body:
        return False, "Пустое сообщение отправлять некуда."
    if len(body) > MAX_LENGTH:
        return False, (
            f"Слишком длинно: {len(body)} символов при пределе {MAX_LENGTH}. "
            f"Разбейте на два объявления."
        )
    extra = unsupported_tags(body)
    if extra:
        listed = ", ".join(f"&lt;{tag}&gt;" for tag in extra[:5])
        return False, (
            f"Telegram не поймёт разметку: {listed}. Уберите её — иначе "
            f"сообщение не уйдёт совсем."
        )
    return True, ""


def preview(draft: Draft) -> str:
    """Как объявление покажут перед отправкой."""
    return (
        "✍️ <b>Объявление в группу</b>\n"
        f"Получатель: <b>{draft.title}</b>\n\n"
        "Так его увидят участники:\n\n"
        "———\n"
        f"{draft.text}\n"
        "———\n\n"
        "<i>Отправляется от имени бота и не отзывается. Проверьте текст.</i>"
    )
