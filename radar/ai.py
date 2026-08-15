"""Слой Google Gemini: автовыбор модели, совместимость поколений, экономия квоты.

Устойчивость к отключению моделей
---------------------------------
Google выводит модели из обращения быстрее объявленных дат: `gemini-2.5-flash`
закрыт для новых ключей до наступления официальной даты отключения. Поэтому
имя модели не зашито намертво: при старте список кандидатов сверяется с тем,
что реально доступно ключу (`models.list`), а при ответе 404 модель на лету
понижается и берётся следующая из списка.

Различия поколений
------------------
Начиная с Gemini 3.x: `temperature`/`top_p`/`top_k` устарели и игнорируются,
`thinking_budget` заменён строковым `thinking_level`, запрос не должен
заканчиваться ходом роли `model`. Всё это учитывается в `_build_config`.

Экономия квоты
--------------
  1. предфильтр по ключевым словам — заведомо нерелевантное не уходит в модель;
  2. пакетный разбор — до AI_BATCH_SIZE новостей одним запросом;
  3. кэш результатов по хэшу текста — повтор не оплачивается;
  4. учёт RPM/RPD с резервом суточных запросов под живой диалог.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import OrderedDict
from dataclasses import replace
from typing import Any, Sequence

from google import genai
from google.genai import types

from . import config
from .matching import Analysis, heuristic_analysis
from .ratelimit import QuotaExceeded, RateLimiter

log = logging.getLogger("radar.ai")

_client: genai.Client | None = None
if config.AI_ENABLED:
    try:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    except Exception as exc:  # noqa: BLE001
        log.error("Не удалось создать клиент Gemini: %s", exc)
        _client = None

ENABLED = _client is not None
_semaphore = asyncio.Semaphore(config.AI_CONCURRENCY)
limiter = RateLimiter(
    rpm=config.AI_RPM,
    rpd=config.AI_RPD,
    reserve=config.AI_RESERVE,
    cooldown=config.AI_COOLDOWN,
)

# Возможности отключаются автоматически, если SDK или модель их не принимают.
_features = {"thinking": True, "safety": True, "search": config.AI_SEARCH}

ASSISTANT = "assistant"
ANALYSIS = "analysis"

# Порядок предпочтения. Первым идёт значение из .env, если оно задано.
_CANDIDATES: dict[str, list[str]] = {
    ASSISTANT: [
        config.GEMINI_MODEL,
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    ANALYSIS: [
        config.GEMINI_MODEL_ANALYSIS,
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-flash-latest",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    ],
}

def _dedup(names: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for name in names:
        clean = (name or "").strip().removeprefix("models/")
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


_chain: dict[str, list[str]] = {role: _dedup(names) for role, names in _CANDIDATES.items()}
_current: dict[str, str] = {role: chain[0] for role, chain in _chain.items() if chain}
_available: list[str] = []      # что реально видит ключ
_unavailable: set[str] = set()  # модели, ответившие 404


class AIError(RuntimeError):
    """Ошибка обращения к модели с понятным пользователю текстом."""


# --------------------------------------------------------------------------
#  Выбор модели
# --------------------------------------------------------------------------

def is_gen3(model: str) -> bool:
    """Модель поколения 3.x и новее: другой набор параметров запроса."""
    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", model or "")
    return bool(match) and int(match.group(1)) >= 3


def current_model(role: str) -> str:
    return _current.get(role) or config.GEMINI_MODEL


def _demote(role: str, model: str) -> str | None:
    """Помечает модель недоступной и переходит к следующей из цепочки."""
    _unavailable.add(model)
    for candidate in _chain.get(role, []):
        if candidate not in _unavailable:
            _current[role] = candidate
            log.warning("Модель «%s» недоступна — перехожу на «%s»", model, candidate)
            return candidate
    log.error("Ни одна модель из списка не доступна для роли «%s»", role)
    return None


async def discover_models() -> list[str]:
    """Спрашивает у API, какие модели доступны ключу, и подбирает рабочие."""
    global _available
    if not ENABLED:
        return []
    names: list[str] = []
    try:
        pager = await _client.aio.models.list()
        async for item in pager:
            raw = getattr(item, "name", "") or ""
            actions = (
                getattr(item, "supported_actions", None)
                or getattr(item, "supported_generation_methods", None)
                or []
            )
            if actions and not any("generateContent" in str(a) for a in actions):
                continue
            names.append(raw.removeprefix("models/"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось получить список моделей (%s) — работаю по умолчанию", exc)
        return []

    _available = sorted(names)
    log.info("Ключу доступно моделей: %d", len(_available))

    for role, chain in _chain.items():
        picked = next((name for name in chain if name in _available), None)
        if picked:
            if picked != _current.get(role):
                log.info("Модель для роли «%s»: %s", role, picked)
            _current[role] = picked
        else:
            log.warning(
                "Ни один кандидат для роли «%s» не найден среди доступных; оставляю «%s»",
                role, _current.get(role),
            )
    return _available


def pin_model(role: str, name: str) -> bool:
    """Закрепляет конкретную модель за ролью до перезапуска."""
    clean = (name or "").strip().removeprefix("models/")
    if not clean:
        return False
    _current[role] = clean
    _unavailable.discard(clean)
    if clean not in _chain.setdefault(role, []):
        _chain[role].insert(0, clean)
    log.info("Модель для роли «%s» закреплена вручную: %s", role, clean)
    return True


def models_report() -> dict[str, Any]:
    return {
        "assistant": current_model(ASSISTANT),
        "analysis": current_model(ANALYSIS),
        "available": list(_available),
        "unavailable": sorted(_unavailable),
    }


# --------------------------------------------------------------------------
#  Сборка запроса
# --------------------------------------------------------------------------

def _thinking_config(model: str):
    """Минимальное «мышление»: у 3.x — thinking_level, у 2.5 — thinking_budget."""
    if not _features["thinking"]:
        return None
    try:
        if is_gen3(model):
            return types.ThinkingConfig(thinking_level="minimal")
        return types.ThinkingConfig(thinking_budget=0)
    except Exception as exc:  # noqa: BLE001 — старый SDK не знает поле
        log.warning("ThinkingConfig не поддерживается SDK (%s) — отключаю", exc)
        _features["thinking"] = False
        return None


def _build_config(
    model: str,
    system: str | None,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
    search: bool,
):
    kwargs: dict[str, Any] = {"max_output_tokens": max_tokens}

    # У Gemini 3.x параметры сэмплирования устарели: игнорируются сейчас
    # и вернут 400 в следующих поколениях.
    if not is_gen3(model):
        kwargs["temperature"] = temperature

    if system:
        kwargs["system_instruction"] = system
    if json_mode:
        kwargs["response_mime_type"] = "application/json"

    thinking = _thinking_config(model)
    if thinking is not None:
        kwargs["thinking_config"] = thinking

    if _features["safety"]:
        try:
            kwargs["safety_settings"] = [
                types.SafetySetting(category=category, threshold="BLOCK_ONLY_HIGH")
                for category in (
                    "HARM_CATEGORY_HARASSMENT",
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_DANGEROUS_CONTENT",
                )
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("SafetySetting не поддерживается (%s) — отключаю", exc)
            _features["safety"] = False

    if search and _features["search"] and not json_mode:
        # Поиск несовместим со строгим JSON-режимом, поэтому только для диалога.
        try:
            kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        except Exception as exc:  # noqa: BLE001
            log.warning("Поиск в интернете не поддерживается SDK (%s)", exc)
            _features["search"] = False

    return types.GenerateContentConfig(**kwargs)


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text.strip()
    chunks: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "thought", False):
                continue
            piece = getattr(part, "text", None)
            if piece:
                chunks.append(piece)
    return "\n".join(chunks).strip()


def _finish_reason(response: Any) -> str:
    for candidate in getattr(response, "candidates", None) or []:
        reason = getattr(candidate, "finish_reason", None)
        if reason:
            return str(reason)
    return "UNKNOWN"


def _strip_trailing_model_turn(contents: Any) -> Any:
    """Gemini 3.x отвергает запрос, если последний ход — роли model (400)."""
    if not isinstance(contents, list):
        return contents
    trimmed = list(contents)
    while trimmed and str(getattr(trimmed[-1], "role", "")) == "model":
        trimmed.pop()
    return trimmed


async def generate(
    contents: Any,
    *,
    system: str | None = None,
    json_mode: bool = False,
    max_tokens: int = 2048,
    temperature: float = 0.4,
    retries: int = 3,
    role: str = ASSISTANT,
    priority: bool = True,
    search: bool = False,
) -> str:
    """Запрос к модели с учётом квот и автоподменой недоступной модели.

    priority=True — живой диалог: ждём свободный слот в пределах таймаута.
    priority=False — фоновая задача: при нехватке квоты сразу QuotaExceeded.
    """
    if not ENABLED:
        raise AIError("Gemini недоступен: не задан GEMINI_API_KEY.")

    if priority:
        try:
            await limiter.wait_acquire(priority=True)
        except QuotaExceeded as exc:
            raise AIError(
                f"Квота Gemini исчерпана ({exc}). Суточный лимит бесплатного тарифа "
                "обнуляется в полночь по тихоокеанскому времени — около 10–11 утра по Москве."
            ) from exc
    elif not await limiter.try_acquire(priority=False):
        raise QuotaExceeded("нет свободной квоты для фонового анализа")

    payload = _strip_trailing_model_turn(contents)
    last: AIError | None = None

    for attempt in range(retries):
        model = current_model(role)
        cfg = _build_config(model, system, json_mode, max_tokens, temperature, search)
        try:
            async with _semaphore:
                response = await asyncio.wait_for(
                    _client.aio.models.generate_content(
                        model=model, contents=payload, config=cfg
                    ),
                    timeout=config.AI_TIMEOUT,
                )
        except asyncio.TimeoutError:
            last = AIError(f"Таймаут запроса к Gemini ({config.AI_TIMEOUT} с).")
            await asyncio.sleep(2 * (attempt + 1))
            continue
        except Exception as exc:  # noqa: BLE001 — SDK бросает разнородные типы
            detail = f"{type(exc).__name__}: {exc}"
            low = detail.lower()
            last = AIError(detail)

            # Модель отключена или недоступна ключу — берём следующую из цепочки.
            if "404" in low or "not found" in low or "no longer available" in low:
                replacement = _demote(role, model)
                if replacement:
                    continue
                raise AIError(
                    f"Модель «{model}» недоступна для этого ключа, и запасных не осталось. "
                    "Укажите актуальную модель в GEMINI_MODEL — список доступных: /models"
                ) from exc

            if "thinking" in low and _features["thinking"]:
                _features["thinking"] = False
                log.warning("Отключаю thinking-параметры: %s", detail)
                continue
            if "safety" in low and _features["safety"]:
                _features["safety"] = False
                log.warning("Отключаю safety_settings: %s", detail)
                continue
            if ("tool" in low or "google_search" in low) and _features["search"]:
                _features["search"] = False
                log.warning("Отключаю поиск в интернете: %s", detail)
                continue
            if any(key in low for key in ("temperature", "top_p", "top_k", "candidate_count")):
                # Параметр устарел в новом поколении — повторяем без него.
                log.warning("Параметр отвергнут моделью: %s", detail)
                continue
            if any(key in low for key in ("429", "resource_exhausted", "quota", "rate limit")):
                limiter.note_rejection()
                raise AIError(
                    "Превышена квота Gemini (429). Суточный лимит бесплатного тарифа "
                    "обнуляется в полночь по тихоокеанскому времени — около 10–11 утра "
                    "по Москве. Расход: /quota"
                ) from exc
            if any(key in low for key in ("500", "503", "unavailable", "internal", "deadline")):
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if any(key in low for key in ("api key", "401", "403", "permission", "unauthenticated")):
                raise AIError("Неверный или неактивный GEMINI_API_KEY.") from exc
            raise last from exc

        answer = _extract_text(response)
        if answer:
            return answer

        reason = _finish_reason(response)
        last = AIError(f"Модель вернула пустой ответ (finish_reason={reason}).")
        if "MAX_TOKENS" in reason:
            max_tokens = min(max_tokens * 2, 8192)
        elif any(key in reason for key in ("SAFETY", "RECITATION", "BLOCK")):
            raise last
        await asyncio.sleep(1.5 * (attempt + 1))

    raise last or AIError("Неизвестная ошибка Gemini.")


# --------------------------------------------------------------------------
#  Разбор новостей
# --------------------------------------------------------------------------

ANALYST_SYSTEM = (
    "Ты — аналитик оперативных сообщений городских служб, администраций и СМИ. "
    "Ты всегда отвечаешь одним валидным JSON-массивом без пояснений и без Markdown. "
    "Работаешь строго по правилам из запроса, ничего не додумывая."
)

ANALYST_PROMPT = """Разбери сообщения из городских источников.

Категории:
- "bpla"      — БПЛА, беспилотники, ракетная опасность, воздушная тревога, работа ПВО, взрывы, угрозы военного характера;
- "mchs"      — экстренные оповещения МЧС: ЧС, штормовое предупреждение, крупные пожары, эвакуация, паводок;
- "jkh"       — ЖКХ: отключения холодной и горячей воды, электричества, газа, отопления, аварии и порывы на сетях, плановые ремонтные работы, лифты;
- "whitelist" — связь: ограничения мобильного интернета, «белые списки» сервисов, восстановление связи.

СООБЩЕНИЯ:
{items}

Верни JSON-массив, по одному объекту на каждое сообщение, в том же порядке:
[{{"index": 1,
   "relevant": true,
   "all_clear": false,
   "historical": false,
   "categories": ["jkh"],
   "severity": "critical" | "warning" | "info",
   "scope": "region" | "city" | "district" | "street",
   "region": "Саратовская область",
   "city": "Саратов",
   "districts": ["Кировский район"],
   "streets": [{{"street": "улица Чапаева", "houses": ["12", "14", "16-20"]}}],
   "summary": "1-3 предложения: что произошло, где, когда восстановят"}}]

Правила:
1. Реклама, розыгрыши, спорт, культура, политические новости, поздравления → relevant=false, categories=[].
2. Для "bpla" всегда scope="city" или "region": военные угрозы касаются всего города, улицы не указывай.
3. Для "jkh" обязательно вытащи улицы и номера домов, если они названы; диапазон пиши как "12-20".
4. Если ЖКХ-событие затрагивает весь город или район без перечисления улиц — scope="city" либо "district", streets=[].
5. Названия улиц пиши полностью, как в тексте («улица имени Чапаева В.И.» → «улица Чапаева»).
6. Незаполненные поля возвращай пустой строкой или пустым списком, поля не пропускай.
7. summary — по-русски, без эмодзи и разметки.
8. all_clear=true, если сообщение отменяет ранее объявленную опасность: «отбой»,
   «опасность снята», «режим беспилотной опасности отменён», «угроза миновала»,
   «обстановка спокойная». Категорию при этом указывай ту же, что у самой угрозы
   (например, отбой БПЛА → categories=["bpla"], all_clear=true, severity="info").
9. historical=true, если событие уже произошло и завершилось: «вчера»,
   «в ночь на», «по итогам суток», «был сбит», «напомним», «как сообщалось»,
   а также если названа дата в прошлом. Такие сообщения нужны как сводка,
   но тревогой не считаются.
10. Поля region и city заполняй всегда, когда место можно определить, —
    хотя бы по названию источника или упоминанию области. Пустой город
    означает, что оповещение не дойдёт до пользователей: без географии
    рассылать тревогу нельзя.
11. Количество объектов в массиве должно совпадать с количеством сообщений."""

_cache: "OrderedDict[str, Analysis]" = OrderedDict()
_CACHE_LIMIT = 800
_counters = {"ai": 0, "cached": 0, "prefiltered": 0, "heuristic": 0, "requests": 0}


def counters() -> dict[str, int]:
    return dict(_counters)


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _remember(text: str, analysis: Analysis) -> Analysis:
    _cache[_cache_key(text)] = analysis
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return analysis


def _parse_array(raw: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    match = re.search(r"\[.*\]", cleaned, re.S)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return [parsed]
    raise ValueError(f"JSON не найден: {cleaned[:200]}")


def _fallback(text: str, source: str, link: str = "") -> Analysis:
    analysis = heuristic_analysis(
        text, source=source, default_city=config.DEFAULT_CITY, link=link
    )
    if not analysis.city and config.DEFAULT_CITY:
        analysis.city = config.DEFAULT_CITY
    return analysis


async def analyze_batch(items: Sequence[tuple[str, ...]]) -> list[Analysis]:
    """Разбирает список кортежей (текст, источник[, ссылка]).

    Ссылка не участвует в анализе, а только переносится в результат:
    кэш строится по тексту, поэтому одна и та же новость из двух лент
    разбирается один раз.
    """
    results: list[Analysis | None] = [None] * len(items)
    todo: list[int] = []

    for index, item in enumerate(items):
        text, source = item[0], item[1]
        link = item[2] if len(item) > 2 else ""
        key = _cache_key(text)
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            _counters["cached"] += 1
            results[index] = replace(cached, link=link or cached.link)
            continue

        if config.AI_PREFILTER:
            # Дешёвая проверка: если ключевых слов нет вовсе, модель не нужна.
            probe = heuristic_analysis(
                text, source=source, default_city=config.DEFAULT_CITY, link=link
            )
            if not probe.relevant:
                _counters["prefiltered"] += 1
                results[index] = _remember(text, probe)
                continue

        if not ENABLED:
            _counters["heuristic"] += 1
            results[index] = _remember(text, _fallback(text, source, link))
            continue

        todo.append(index)

    for start in range(0, len(todo), config.AI_BATCH_SIZE):
        chunk = todo[start:start + config.AI_BATCH_SIZE]
        listing = "\n\n".join(
            f"[{position + 1}] источник «{items[index][1]}»:\n{items[index][0][:2500]}"
            for position, index in enumerate(chunk)
        )
        try:
            raw = await generate(
                ANALYST_PROMPT.format(items=listing),
                system=ANALYST_SYSTEM,
                json_mode=True,
                max_tokens=700 * len(chunk) + 300,
                temperature=0.1,
                role=ANALYSIS,
                priority=False,
            )
            _counters["requests"] += 1
            payloads = _parse_array(raw)
        except QuotaExceeded:
            log.info("Квота исчерпана — оставшиеся %d сообщений по эвристике", len(chunk))
            for index in chunk:
                _counters["heuristic"] += 1
                results[index] = _remember(items[index][0], _fallback(*items[index][:3]))
            continue
        except (AIError, ValueError, json.JSONDecodeError) as exc:
            log.warning("Пакетный разбор не удался (%s) — эвристика", exc)
            for index in chunk:
                _counters["heuristic"] += 1
                results[index] = _remember(items[index][0], _fallback(*items[index][:3]))
            continue

        by_position: dict[int, dict[str, Any]] = {}
        for position, payload in enumerate(payloads):
            marker = payload.get("index")
            if isinstance(marker, (int, str)) and str(marker).isdigit():
                by_position[int(marker) - 1] = payload
            else:
                by_position.setdefault(position, payload)

        for position, index in enumerate(chunk):
            payload = by_position.get(position)
            text, source = items[index][0], items[index][1]
            link = items[index][2] if len(items[index]) > 2 else ""
            if payload is None:
                _counters["heuristic"] += 1
                results[index] = _remember(text, _fallback(text, source, link))
                continue
            analysis = Analysis.from_payload(payload, source=source, raw=text, link=link)
            if not analysis.city and config.DEFAULT_CITY:
                analysis.city = config.DEFAULT_CITY
            _counters["ai"] += 1
            results[index] = _remember(text, analysis)

    return [item if item is not None else Analysis(relevant=False) for item in results]


async def analyze(text: str, source: str, link: str = "") -> Analysis:
    """Разбор одного сообщения (обёртка над пакетным)."""
    return (await analyze_batch([(text, source, link)]))[0]


def cache_size() -> int:
    return len(_cache)


def quota_snapshot() -> dict[str, int | bool]:
    return limiter.snapshot()


# --------------------------------------------------------------------------
#  ИИ-ассистент
# --------------------------------------------------------------------------

ASSISTANT_SYSTEM = (
    "Ты — ИИ-ассистент системы городского мониторинга «Радар». Помогаешь модераторам "
    "и администраторам: отвечаешь на вопросы, формулируешь оповещения для жителей, "
    "разбираешь ситуации по ЖКХ, ЧС и связи, объясняешь работу самого бота, помогаешь "
    "искать официальные каналы и источники. Если пользуешься поиском — приводи ссылки. "
    "Отвечай по-русски, кратко и по делу. Разметка: **жирный**, `код`, списки. "
    "Не используй заголовки и таблицы: ответ читают в Telegram."
)


def user_turn(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def model_turn(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


async def assistant(history: list[types.Content], question: str) -> str:
    contents = list(history) + [user_turn(question)]
    return await generate(
        contents,
        system=ASSISTANT_SYSTEM,
        max_tokens=2048,
        temperature=0.6,
        role=ASSISTANT,
        priority=True,
        search=True,
    )
