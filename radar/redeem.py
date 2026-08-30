#!/usr/bin/env python3
"""Погашение кодов, выданных на стороне.

Партнёрский проект раздаёт коды у себя, человек приносит код сюда
и получает подписку. От `radar/promo.py` это противоположное движение:
там коды выдаём мы и отдаём партнёру выгрузку, здесь код приходит
снаружи и мы его засчитываем.

Список кодов ведёт суперадминистратор — на стороне партнёра они
генерируются как угодно, а сюда попадают готовыми. Своей генерации нет
намеренно: код, который мы придумали сами, партнёр не сможет проверить
у себя, и сверять две выдумки было бы нечем.

Код одноразовый. Кто и когда его погасил, остаётся в записи: без этого
на вопрос «почему у него подписка» ответить нечем.

Про этот механизм ничего не сказано в интерфейсе бота, в README и в списке
изменений — так задумано. Код узнаёт тот, кому его дали на стороне
партнёра, и вводит его сообщением; для остальных ничего не меняется.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("radar.redeem")

META_KEY = "redeem_codes"

# Сколько дней даёт код по умолчанию.
DEFAULT_DAYS = 28

# Что вообще считаем кодом. Рамки нужны и для проверки при заведении,
# и для того, чтобы обычное сообщение не принималось за попытку погашения.
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{4,31}$")

MAX_CODES = 500


def normalize(code: str) -> str:
    """Приводит ввод к хранимому виду: регистр и пробелы человек не считает."""
    return re.sub(r"\s+", "", str(code or "")).upper()


def looks_like_code(text: str) -> bool:
    """Похоже ли сообщение на код. Нужна, чтобы не хватать чужой текст."""
    return bool(CODE_RE.match(normalize(text)))


async def load() -> list[dict[str, Any]]:
    from .db import repo

    try:
        raw = await repo.get_meta(META_KEY, None)
    except Exception:  # noqa: BLE001
        log.exception("Список кодов недоступен")
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("code")]


async def save(items: list[dict[str, Any]]) -> None:
    from .db import repo

    await repo.set_meta(META_KEY, items[:MAX_CODES])


async def add(codes: str, days: int = DEFAULT_DAYS) -> tuple[list[str], list[str]]:
    """Заводит коды из присланного текста. Возвращает (добавленные, пропущенные)."""
    items = await load()
    known = {str(item.get("code")) for item in items}

    added: list[str] = []
    skipped: list[str] = []
    for chunk in re.split(r"[,\n;\s]+", codes or ""):
        code = normalize(chunk)
        if not code:
            continue
        if not CODE_RE.match(code) or code in known:
            skipped.append(chunk.strip())
            continue
        items.append({"code": code, "days": max(1, int(days)),
                      "used_by": "", "used_at": ""})
        known.add(code)
        added.append(code)

    if added:
        await save(items)
        log.info("Заведено кодов: %d", len(added))
    return added, skipped


async def drop(code: str) -> bool:
    items = await load()
    code = normalize(code)
    rest = [item for item in items if str(item.get("code")) != code]
    if len(rest) == len(items):
        return False
    await save(rest)
    return True


async def redeem(code: str, user_key: str) -> int:
    """Гасит код. Возвращает число дней; 0 — код не подошёл.

    Одноразовость проверяется по записи, а не по факту начисления: иначе
    один и тот же код, введённый дважды подряд, дал бы дни дважды.
    """
    code = normalize(code)
    if not CODE_RE.match(code):
        return 0

    items = await load()
    for item in items:
        if str(item.get("code")) != code:
            continue
        if item.get("used_by"):
            return 0
        item["used_by"] = str(user_key)
        item["used_at"] = datetime.now(timezone.utc).isoformat()
        await save(items)
        days = max(1, int(item.get("days") or DEFAULT_DAYS))
        log.info("Код погашен: %s дней %d", code[:4] + "…", days)
        return days
    return 0


async def summary() -> str:
    """Состояние списка для суперадминистратора."""
    items = await load()
    if not items:
        return "Кодов пока нет."
    used = sum(1 for item in items if item.get("used_by"))
    return f"Кодов: {len(items)}, погашено: {used}, свободно: {len(items) - used}"
