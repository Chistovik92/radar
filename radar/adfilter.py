"""Реклама VPN-сервисов в пересылаемых текстах (с 4.9.9.3).

Городские каналы и СМИ всё чаще вставляют в посты рекламу VPN:
«быстрый VPN без блокировок, промокод…», «Реклама. erid: …». Бот
пересказывает и пересылает эти посты — и без фильтра раздавал бы чужую
рекламу от своего имени.

Два разных места, и в них разные замены:

* **новостные подборки** — рекламный пост заменяется одной заглушкой
  партнёрского проекта (кнопка «HydraSite» из настроек `PROMO_*`).
  Подборка — новостной продукт, и партнёрская строка в нём допустима;
* **оповещения, памятки и сводки** — рекламный абзац вырезается
  и заменяется **нейтральной** пометкой, без партнёра. Правило проекта
  «реклама не появляется внутри тревожных сообщений» (CLAUDE.md,
  «Что не обсуждается», п.2) касается и нашей рекламы тоже: вместо
  чужой вставлять свою — та же реклама в тревоге.

Распознавание — по абзацу, а не по всему тексту: пост про отключение
воды с рекламным хвостом должен дойти без хвоста, а не пропасть целиком.
Абзац считается рекламой VPN, только если в нём есть и VPN, и признак
рекламы: слово «VPN» в новости о блокировках — это новость, а не реклама.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable, TypeVar

# Упоминание VPN или его синонима «для обхода блокировок».
VPN_RE = re.compile(
    r"\bvpn\b|\bвпн\b|\bv\s*p\s*n\b|обход\w*\s+блокиров|"
    r"без\s+блокировок|впн-сервис|vpn-сервис",
    re.I,
)

# Признаки рекламы: маркировка по закону, промокоды, призывы, цены.
AD_RE = re.compile(
    r"\bреклама\b|\berid\b|промокод|скидк\w*|бесплатн\w*\s+(?:пробн|период|дн)|"
    r"пробн\w*\s+период|подключ\w*\s+(?:по\s+ссылке|сейчас|здесь)|"
    r"переход\w*\s+по\s+ссылке|жми|подпис\w*\s+на|тариф\w*|"
    r"\d+\s*(?:₽|руб)|@\w*bot\b|t\.me/\w*(?:vpn|bot)\w*|"
    r"купи\w*|оформ\w*\s+подписк",
    re.I,
)

NEUTRAL_STUB = "[реклама VPN-сервиса скрыта]"

_PARAGRAPHS = re.compile(r"\n\s*\n|\n")


def is_vpn_ad(text: str) -> bool:
    """Реклама ли это VPN: и VPN упомянут, и признаки рекламы есть."""
    value = text or ""
    return bool(VPN_RE.search(value)) and bool(AD_RE.search(value))


def enabled() -> bool:
    try:
        from . import features

        return features.enabled("vpn_ad_filter")
    except Exception:  # noqa: BLE001
        return True


def strip(text: str, stub: str = NEUTRAL_STUB) -> tuple[str, int]:
    """Вырезает рекламные абзацы. Возвращает (текст, сколько вырезано).

    Подряд идущие рекламные абзацы сливаются в одну пометку: три строки
    рекламы не должны превращаться в три одинаковые заглушки.
    """
    value = text or ""
    if not value or not enabled() or not VPN_RE.search(value):
        return value, 0

    pieces = [piece for piece in _PARAGRAPHS.split(value)]
    result: list[str] = []
    removed = 0
    previous_was_stub = False
    for piece in pieces:
        if piece.strip() and is_vpn_ad(piece):
            removed += 1
            if not previous_was_stub:
                result.append(stub)
            previous_was_stub = True
            continue
        result.append(piece)
        previous_was_stub = False

    # Рекламный признак бывает в соседнем абзаце, а не в том же, где VPN:
    # «Быстрый VPN без ограничений.» + «Реклама. erid: 2Vtzq…». Если
    # по абзацам ничего не нашлось, а текст целиком — реклама, режем целиком.
    if not removed and is_vpn_ad(value) and len(value) <= 600:
        return stub, 1

    return "\n".join(result).strip(), removed


def partner_stub() -> str:
    """Заглушка партнёрского проекта для подборок. Пусто — партнёр выключен."""
    from . import config

    if not config.PROMO_ENABLED or not config.PROMO_URL:
        return ""
    from .textutils import esc, esc_attr

    title = config.PROMO_TITLE or "Партнёр"
    return (f'🐙 Реклама VPN из новостей скрыта. Надёжный доступ — '
            f'<a href="{esc_attr(config.PROMO_URL)}">{esc(title)}</a>, '
            f'наш партнёр.')


Item = TypeVar("Item")


def split_entries(entries: Iterable[Item]) -> tuple[list[Item], int]:
    """Отделяет рекламные новости подборки. Возвращает (чистые, сколько убрано).

    Новость с рекламным хвостом остаётся, но без хвоста; новость,
    которая целиком реклама, уходит из подборки — её заменит одна
    партнёрская строка в конце.
    """
    clean: list[Item] = []
    removed = 0
    for entry in entries:
        summary = str(getattr(entry, "summary", "") or "")
        if not enabled() or not VPN_RE.search(summary):
            clean.append(entry)
            continue
        text, cut = strip(summary, stub="")
        if not cut:
            clean.append(entry)
            continue
        removed += 1
        if text.strip():
            clean.append(replace(entry, summary=text.strip()))
    return clean, removed
