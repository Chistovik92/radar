"""Выбор провайдера ИИ на лету: Google Gemini или DeepSeek.

Зачем
-----
Сравнение в `aibench` показывает, кто точнее на реальных сообщениях служб.
Раньше результат оставался справкой: переключиться можно было только правкой
`.env` и перезапуском. Теперь провайдер меняется кнопкой, и следующий же
разбор идёт через выбранного.

Проверка баланса
----------------
У DeepSeek оплата по факту, и ключ с нулевым балансом не отличается от рабочего
до первого запроса — а первым запросом окажется разбор реальной тревоги.
Поэтому перед переключением баланс проверяется отдельным запросом. У Gemini
такого метода нет: там смотрим на успешность пробного вызова и остаток квоты.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from . import secrets

log = logging.getLogger("radar.provider")

GEMINI = "gemini"
DEEPSEEK = "deepseek"

TIMEOUT = 25


@dataclass(frozen=True)
class ProviderInfo:
    key: str
    title: str
    env: str
    note: str
    paid: bool


PROVIDERS: dict[str, ProviderInfo] = {
    GEMINI: ProviderInfo(
        GEMINI, "Google Gemini", "GEMINI_API_KEY",
        "Бесплатный тариф с ограничением по запросам. Умеет поиск в интернете.",
        paid=False,
    ),
    DEEPSEEK: ProviderInfo(
        DEEPSEEK, "DeepSeek", "DEEPSEEK_API_KEY",
        "Оплата по факту, очень низкая цена. Поиска в интернете нет.",
        paid=True,
    ),
}

# Текущий выбор. Пустая строка — используется значение из .env.
_selected: str = ""


def available() -> list[ProviderInfo]:
    return [item for item in PROVIDERS.values() if secrets.get(item.env)]


def current() -> str:
    """Активный провайдер для разбора новостей."""
    if _selected and secrets.get(PROVIDERS[_selected].env):
        return _selected
    stored = (secrets.get("AI_PROVIDER") or "").strip().lower()
    if stored in PROVIDERS and secrets.get(PROVIDERS[stored].env):
        return stored
    return GEMINI


def select(name: str, persist: bool = True) -> bool:
    """Переключает провайдера. Действует со следующего разбора."""
    global _selected

    key = (name or "").strip().lower()
    if key not in PROVIDERS:
        return False
    if not secrets.get(PROVIDERS[key].env):
        return False

    _selected = key
    if persist:
        secrets.write("AI_PROVIDER", key)
    log.info("Провайдер разбора новостей переключён на «%s»", key)
    return True


# --------------------------------------------------------------------------
#  Проверка доступности и баланса
# --------------------------------------------------------------------------

@dataclass
class Health:
    provider: str
    ok: bool = False
    balance: str = ""          # человекочитаемый остаток
    balance_low: bool = False
    detail: str = ""

    @property
    def icon(self) -> str:
        if not self.ok:
            return "❌"
        return "⚠️" if self.balance_low else "✅"


async def check_deepseek(session: aiohttp.ClientSession, api_key: str) -> Health:
    """Баланс DeepSeek: у него есть отдельный метод, и им стоит пользоваться."""
    health = Health(provider=DEEPSEEK)
    try:
        async with session.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        ) as response:
            if response.status == 401:
                health.detail = "ключ отклонён"
                return health
            if response.status != 200:
                health.detail = f"HTTP {response.status}"
                return health
            payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        health.detail = f"{type(exc).__name__}"
        return health

    infos = payload.get("balance_infos") or []
    if not infos:
        health.ok = bool(payload.get("is_available"))
        health.detail = "баланс не сообщён"
        return health

    info = infos[0]
    currency = str(info.get("currency") or "")
    total = info.get("total_balance")
    try:
        amount = float(total)
    except (TypeError, ValueError):
        amount = 0.0

    health.ok = bool(payload.get("is_available", amount > 0))
    health.balance = f"{amount:.2f} {currency}".strip()
    # Порог условный: при таком остатке разбора хватит на считаные дни
    health.balance_low = amount <= 0.5
    if amount <= 0:
        health.ok = False
        health.detail = "нулевой баланс"
    return health


async def check_gemini(session: aiohttp.ClientSession, api_key: str) -> Health:
    """У Gemini метода баланса нет — проверяем, что ключ принимается."""
    health = Health(provider=GEMINI)
    try:
        async with session.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
        ) as response:
            if response.status == 401 or response.status == 403:
                health.detail = "ключ отклонён"
                return health
            if response.status != 200:
                health.detail = f"HTTP {response.status}"
                return health
            payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        health.detail = f"{type(exc).__name__}"
        return health

    models = [
        str(item.get("name", "")).removeprefix("models/")
        for item in payload.get("models") or []
    ]
    usable = [name for name in models if "gemini" in name]
    health.ok = bool(usable)
    health.balance = "тариф по квоте"
    health.detail = f"моделей доступно: {len(usable)}" if usable else "моделей нет"

    # Остаток дневной квоты берём у собственного счётчика: у Gemini
    # нет метода, который сообщал бы его снаружи.
    try:
        from . import ai  # локальный импорт: избегаем цикла на старте

        snapshot = ai.limiter.snapshot()
        left = int(snapshot.get("limit_day", 0)) - int(snapshot.get("used_today", 0))
        health.balance = f"осталось запросов сегодня: {max(0, left)}"
        health.balance_low = left < 20
    except Exception:  # noqa: BLE001
        pass

    return health


async def check(name: str) -> Health:
    """Проверяет одного провайдера."""
    key = (name or "").strip().lower()
    info = PROVIDERS.get(key)
    if info is None:
        return Health(provider=key, detail="неизвестный провайдер")

    api_key = secrets.get(info.env)
    if not api_key:
        return Health(provider=key, detail="ключ не задан")

    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if key == DEEPSEEK:
            return await check_deepseek(session, api_key)
        return await check_gemini(session, api_key)


async def check_all() -> dict[str, Health]:
    results: dict[str, Health] = {}
    for info in PROVIDERS.values():
        if secrets.get(info.env):
            results[info.key] = await check(info.key)
    return results


def render(results: dict[str, Health]) -> str:
    """Состояние провайдеров для сообщения."""
    from .textutils import esc

    active = current()
    lines = ["🤖 <b>Провайдер разбора новостей</b>", ""]

    if not results:
        lines.append(
            "Ни одного ключа не задано. Добавьте их в разделе «Ключи доступа»."
        )
        return "\n".join(lines)

    for key, health in results.items():
        info = PROVIDERS[key]
        mark = " ← активен" if key == active else ""
        lines.append(f"{health.icon} <b>{esc(info.title)}</b>{mark}")
        if health.balance:
            lines.append(f"   {esc(health.balance)}")
        if health.detail:
            lines.append(f"   <i>{esc(health.detail)}</i>")
        lines.append("")

    if any(item.balance_low for item in results.values()):
        lines.append("⚠️ <i>Остаток на исходе — разбор скоро переключится "
                     "на эвристику по ключевым словам.</i>")
    return "\n".join(lines).strip()
