"""Слой Google Gemini: устойчивые запросы, разбор новостей, ИИ-ассистент."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import OrderedDict
from typing import Any

from google import genai
from google.genai import types

from . import config
from .matching import Analysis, heuristic_analysis

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

# Возможности отключаются автоматически, если SDK или модель их не принимают.
_features = {"thinking": True, "safety": True}


class AIError(RuntimeError):
    """Ошибка обращения к модели с понятным пользователю текстом."""


def _config(system: str | None, json_mode: bool, max_tokens: int, temperature: float):
    kwargs: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_tokens}
    if system:
        kwargs["system_instruction"] = system
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    if _features["thinking"]:
        # Без этого модели 2.5 расходуют весь бюджет токенов на размышления
        # и возвращают пустой response.text.
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    if _features["safety"]:
        kwargs["safety_settings"] = [
            types.SafetySetting(category=category, threshold="BLOCK_ONLY_HIGH")
            for category in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ]
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


async def generate(
    contents: Any,
    *,
    system: str | None = None,
    json_mode: bool = False,
    max_tokens: int = 2048,
    temperature: float = 0.4,
    retries: int = 3,
) -> str:
    if not ENABLED:
        raise AIError("Gemini недоступен: не задан GEMINI_API_KEY.")

    last: AIError | None = None
    for attempt in range(retries):
        cfg = _config(system, json_mode, max_tokens, temperature)
        try:
            async with _semaphore:
                response = await asyncio.wait_for(
                    _client.aio.models.generate_content(
                        model=config.GEMINI_MODEL, contents=contents, config=cfg
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
            if "thinking" in low and _features["thinking"]:
                _features["thinking"] = False
                log.warning("Отключаю thinking_config: %s", detail)
                continue
            if "safety" in low and _features["safety"]:
                _features["safety"] = False
                log.warning("Отключаю safety_settings: %s", detail)
                continue
            if any(key in low for key in ("429", "resource_exhausted", "quota", "rate limit")):
                last = AIError("Превышена квота Gemini (429). Повторите позже.")
                await asyncio.sleep(6 * (attempt + 1))
                continue
            if any(key in low for key in ("500", "503", "unavailable", "internal", "deadline")):
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if any(key in low for key in ("api key", "401", "403", "permission", "unauthenticated")):
                raise AIError("Неверный или неактивный GEMINI_API_KEY.") from exc
            if "not found" in low or "404" in low:
                raise AIError(f"Модель «{config.GEMINI_MODEL}» недоступна для этого ключа.") from exc
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
    "Ты всегда отвечаешь одним валидным JSON-объектом без пояснений и без Markdown."
)

ANALYST_PROMPT = """Разбери сообщение из источника «{source}».

СООБЩЕНИЕ:
\"\"\"{text}\"\"\"

Категории:
- "bpla"      — БПЛА, беспилотники, ракетная опасность, воздушная тревога, работа ПВО, взрывы, угрозы военного характера;
- "mchs"      — экстренные оповещения МЧС: ЧС, штормовое предупреждение, крупные пожары, эвакуация, паводок;
- "jkh"       — ЖКХ: отключения холодной и горячей воды, электричества, газа, отопления, аварии и порывы на сетях, плановые ремонтные работы, вывоз мусора, лифты;
- "whitelist" — связь: ограничения мобильного интернета, «белые списки» сервисов, восстановление связи.

Верни строго такой JSON:
{{"relevant": true|false,
  "categories": ["jkh"],
  "severity": "critical"|"warning"|"info",
  "scope": "region"|"city"|"district"|"street",
  "region": "Саратовская область",
  "city": "Саратов",
  "districts": ["Кировский район"],
  "streets": [{{"street": "улица Чапаева", "houses": ["12", "14", "16-20"]}}],
  "summary": "1-3 предложения: что произошло, где, когда восстановят"}}

Правила:
1. Реклама, розыгрыши, спорт, культура, политические новости, поздравления → relevant=false, categories=[].
2. Для "bpla" всегда scope="city" или "region" — военные угрозы касаются всего города, улицы не указывай.
3. Для "jkh" обязательно вытащи улицы и номера домов, если они названы; диапазон домов пиши как "12-20".
4. Если ЖКХ-событие затрагивает весь город или район без перечисления улиц — scope="city" либо "district", streets=[].
5. Названия улиц пиши полностью, как в тексте («улица имени Чапаева В.И.» → «улица Чапаева»).
6. Незаполненные поля возвращай пустой строкой или пустым списком, поля не пропускай.
7. summary — по-русски, без эмодзи и разметки."""

_cache: "OrderedDict[str, Analysis]" = OrderedDict()
_CACHE_LIMIT = 800


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        raise ValueError(f"JSON не найден: {cleaned[:200]}")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Ожидался JSON-объект")
    return parsed


async def analyze(text: str, source: str) -> Analysis:
    """Разбирает сообщение один раз и кэширует результат для всех пользователей."""
    key = _cache_key(text)
    cached = _cache.get(key)
    if cached is not None:
        _cache.move_to_end(key)
        return cached

    analysis: Analysis
    if ENABLED:
        try:
            raw = await generate(
                ANALYST_PROMPT.format(source=source or "неизвестен", text=text[:4000]),
                system=ANALYST_SYSTEM,
                json_mode=True,
                max_tokens=900,
                temperature=0.1,
            )
            analysis = Analysis.from_payload(_parse_json(raw), source=source, raw=text)
        except (AIError, ValueError, json.JSONDecodeError) as exc:
            log.warning("Разбор через Gemini не удался (%s), включаю эвристику", exc)
            analysis = heuristic_analysis(text, source=source, default_city=config.DEFAULT_CITY)
    else:
        analysis = heuristic_analysis(text, source=source, default_city=config.DEFAULT_CITY)

    if not analysis.city and config.DEFAULT_CITY:
        analysis.city = config.DEFAULT_CITY

    _cache[key] = analysis
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return analysis


def cache_size() -> int:
    return len(_cache)


# --------------------------------------------------------------------------
#  ИИ-ассистент
# --------------------------------------------------------------------------

ASSISTANT_SYSTEM = (
    "Ты — ИИ-ассистент системы городского мониторинга «Радар». Помогаешь модераторам "
    "и администраторам: отвечаешь на вопросы, формулируешь оповещения для жителей, "
    "разбираешь ситуации по ЖКХ, ЧС и связи, объясняешь работу самого бота. "
    "Отвечай по-русски, кратко и по делу. Разметка: **жирный**, `код`, списки."
)


def user_turn(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def model_turn(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


async def assistant(history: list[types.Content], question: str) -> str:
    contents = list(history) + [user_turn(question)]
    return await generate(
        contents, system=ASSISTANT_SYSTEM, max_tokens=2048, temperature=0.6
    )
