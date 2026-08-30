"""Выбор провайдера ИИ на лету и модели у него.

Зачем
-----
Сравнение в `aibench` показывает, кто точнее на реальных сообщениях служб.
Раньше результат оставался справкой: переключиться можно было только правкой
`.env` и перезапуском. Теперь провайдер меняется кнопкой, и следующий же
разбор идёт через выбранного.

Девять провайдеров вместо двух (с 4.8.2)
----------------------------------------
До 4.8.2 в списке были только Gemini и DeepSeek — при том что `.env`
предлагал завести ключи OpenRouter, Mistral, Moonshot, Qwen, Z.ai,
Cerebras и OpenAI. Ключ завести было можно, а выбрать провайдера нельзя:
**ключ, который никуда не подключается, ничем не лучше тумблера,
не включающего функцию.**

Все они, кроме Gemini, говорят совместимым с OpenAI протоколом, поэтому
различаются одним полем `kind`, а не отдельной реализацией на каждого.

Свой агент
----------
`CUSTOM` — любой сервис с совместимым интерфейсом: локальная модель,
корпоративный шлюз, собственный прокси. Адрес задаётся человеком
в `CUSTOM_AI_URL`. Без адреса провайдер в списке не показывается: ключ
без адреса никуда не ведёт.

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
OPENROUTER = "openrouter"
MISTRAL = "mistral"
MOONSHOT = "moonshot"
DASHSCOPE = "dashscope"
ZAI = "zai"
OPENAI = "openai"
CEREBRAS = "cerebras"
CUSTOM = "custom"

# Два способа разговаривать с моделью. У Gemini свой протокол, у всех
# остальных — совместимый с OpenAI `/chat/completions`. Различие
# в одном поле, а не в отдельной реализации на каждого: провайдеров
# стало восемь, и писать восемь почти одинаковых функций значило бы
# восемь раз повторить одну ошибку.
KIND_GEMINI = "gemini"
KIND_OPENAI = "openai"

TIMEOUT = 25


@dataclass(frozen=True)
class ProviderInfo:
    key: str
    title: str
    env: str
    note: str
    paid: bool
    kind: str = KIND_OPENAI
    # Основание адреса без `/chat/completions`. Пусто у Gemini (свой
    # протокол) и у своих агентов — там адрес задаёт человек.
    base_url: str = ""
    default_model: str = ""
    # Настройка, из которой берётся адрес. Заполнена у своих агентов:
    # до 4.8.8 адрес был один на всех и читался из общей CUSTOM_AI_URL,
    # а агентов теперь несколько, и у каждого свой.
    url_env: str = ""

    @property
    def custom(self) -> bool:
        return self.key == CUSTOM or self.key.startswith(CUSTOM)

    def url(self) -> str:
        """Адрес совместимого с OpenAI эндпоинта."""
        base = secrets.get(self.url_env) if self.url_env else self.base_url
        return (base or "").rstrip("/")


# Настройки своего агента. Вынесены в имена, а не зашиты строками:
# на них ссылается и установщик, и раздел ключей в боте.
CUSTOM_URL_ENV = "CUSTOM_AI_URL"
CUSTOM_KEY_ENV = "CUSTOM_AI_KEY"

PROVIDERS: dict[str, ProviderInfo] = {
    GEMINI: ProviderInfo(
        GEMINI, "Google Gemini", "GEMINI_API_KEY",
        "Бесплатный тариф с ограничением по запросам. Умеет поиск в интернете.",
        paid=False, kind=KIND_GEMINI,
    ),
    DEEPSEEK: ProviderInfo(
        DEEPSEEK, "DeepSeek", "DEEPSEEK_API_KEY",
        "Оплата по факту, очень низкая цена. Поиска в интернете нет.",
        paid=True, base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
    ),
    OPENROUTER: ProviderInfo(
        OPENROUTER, "OpenRouter", "OPENROUTER_API_KEY",
        "Один ключ на десятки моделей, среди них есть бесплатные. "
        "Модель выбирается из списка.",
        paid=True, base_url="https://openrouter.ai/api/v1",
        default_model="",
    ),
    MISTRAL: ProviderInfo(
        MISTRAL, "Mistral", "MISTRAL_API_KEY",
        "Европейская юрисдикция, бесплатный тариф с жёстким пределом частоты.",
        paid=False, base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
    ),
    MOONSHOT: ProviderInfo(
        MOONSHOT, "Moonshot Kimi", "MOONSHOT_API_KEY",
        "До тысячи запросов в сутки бесплатно.",
        paid=False, base_url="https://api.moonshot.ai/v1",
        default_model="moonshot-v1-8k",
    ),
    DASHSCOPE: ProviderInfo(
        DASHSCOPE, "Alibaba Qwen", "DASHSCOPE_API_KEY",
        "Международный эндпоинт DashScope, модели Qwen.",
        paid=True,
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
    ),
    ZAI: ProviderInfo(
        ZAI, "Z.ai / GLM", "ZAI_API_KEY",
        "Модели GLM, часть доступна бесплатно.",
        paid=False, base_url="https://api.z.ai/api/paas/v4",
        default_model="glm-4-flash",
    ),
    OPENAI: ProviderInfo(
        OPENAI, "OpenAI", "OPENAI_API_KEY",
        "Платный, без бесплатного тарифа.",
        paid=True, base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
    ),
    CEREBRAS: ProviderInfo(
        CEREBRAS, "Cerebras", "CEREBRAS_API_KEY",
        "Открытые модели, около миллиона токенов в сутки бесплатно.",
        paid=False, base_url="https://api.cerebras.ai/v1",
        default_model="llama3.1-8b",
    ),
    CUSTOM: ProviderInfo(
        CUSTOM, "Свой агент", CUSTOM_KEY_ENV,
        "Любой сервис с совместимым с OpenAI интерфейсом: локальная модель, "
        "корпоративный шлюз, собственный прокси. Задаётся адресом и ключом.",
        paid=False, base_url="", default_model="", url_env=CUSTOM_URL_ENV,
    ),
}

# Текущий выбор. Пустая строка — используется значение из .env.
_selected: str = ""


def custom_infos() -> dict[str, ProviderInfo]:
    """Свои агенты как обычные провайдеры.

    Собираются на лету, а не хранятся в PROVIDERS: их состав меняется
    из панели и из бота, и застывший словарь показывал бы вчерашний
    список до перезапуска.
    """
    from . import agents

    built: dict[str, ProviderInfo] = {}
    for agent in agents.load():
        if agent.legacy:
            # Прежняя пара уже описана записью CUSTOM — второй раз
            # её показывать не надо.
            continue
        _title, url_env, key_env, _model = agents.env_names(agent.slot)
        built[agent.name] = ProviderInfo(
            agent.name, agent.shown, key_env,
            "Свой сервис с совместимым с OpenAI интерфейсом.",
            paid=False, base_url="", default_model=agent.model,
            url_env=url_env,
        )
    return built


def all_infos() -> dict[str, ProviderInfo]:
    """Встроенные провайдеры вместе со своими агентами."""
    merged = dict(PROVIDERS)
    merged.update(custom_infos())
    return merged


def available() -> list[ProviderInfo]:
    """Провайдеры, у которых есть ключ.

    Свой агент требует ещё и адреса: ключ без адреса никуда не ведёт,
    и показывать такой провайдер в списке значило бы предложить выбрать
    заведомо неработающее.
    """
    ready: list[ProviderInfo] = []
    for item in all_infos().values():
        if not secrets.get(item.env):
            continue
        if item.custom and not item.url():
            continue
        ready.append(item)
    return ready


# --------------------------------------------------------------------------
#  Выбор модели
# --------------------------------------------------------------------------
#
# У OpenRouter моделей десятки, и вписывать имя руками — верный способ
# опечататься так, что выяснится это при первом разборе настоящей тревоги.
# Поэтому список забирается у самого провайдера, а выбор запоминается.

def model_env(name: str) -> str:
    """Имя настройки с выбранной моделью провайдера."""
    return f"AI_MODEL_{name.upper()}"


def model_of(name: str) -> str:
    """Выбранная модель или значение по умолчанию."""
    info = all_infos().get(name)
    if info is None:
        return ""
    chosen = (secrets.get(model_env(name)) or "").strip()
    return chosen or info.default_model


def set_model(name: str, model: str) -> bool:
    if name not in all_infos():
        return False
    return secrets.write(model_env(name), (model or "").strip())


async def list_models(name: str, limit: int = 60) -> list[str]:
    """Список моделей у провайдера. Пусто — не спросить или не поддерживает.

    Формат ответа общий для совместимых с OpenAI служб:
    `{"data": [{"id": "..."}]}`. Gemini сюда не попадает — у него свой
    протокол и свой `ai.discover_models`.
    """
    info = all_infos().get(name)
    if info is None:
        return []

    # У Gemini свой протокол и свой перечень моделей. Раньше здесь стоял
    # безусловный отказ, и человек с заведённым ключом Google видел пустой
    # список: ключ есть, а выбрать нечего. Спрашивать заново он не обязан.
    if info.kind == KIND_GEMINI:
        from . import ai

        try:
            return (await ai.discover_models())[:limit]
        except Exception:  # noqa: BLE001
            log.warning("Список моделей Gemini недоступен", exc_info=True)
            return []

    if info.kind != KIND_OPENAI:
        return []

    base = info.url()
    key = secrets.get(info.env)
    if not base or not key:
        return []

    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {key}"},
            ) as response:
                if response.status != 200:
                    log.info("%s: список моделей вернул %s", name, response.status)
                    return []
                payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.info("%s: список моделей не получен: %s", name, exc)
        return []

    rows = payload.get("data") if isinstance(payload, dict) else payload
    names: list[str] = []
    for row in rows or []:
        found = row.get("id") if isinstance(row, dict) else row
        if isinstance(found, str) and found.strip():
            names.append(found.strip())

    # Сортировка по имени: у OpenRouter порядок выдачи произвольный,
    # и одна и та же модель каждый раз оказывалась бы в другом месте
    # списка — выбирать в таком неудобно.
    return sorted(set(names))[:limit]


def free_first(names: list[str]) -> list[str]:
    """Бесплатные модели вперёд — их у OpenRouter помечают суффиксом."""
    free = [item for item in names if item.endswith(":free")]
    rest = [item for item in names if not item.endswith(":free")]
    return free + rest


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
