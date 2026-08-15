"""Тонкие HTTP-клиенты: Gemini REST, OpenAI-совместимый и Anthropic.

Никаких SDK — только aiohttp, чтобы стенд запускался где угодно и не зависел
от версий библиотек провайдеров.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from providers import Provider

@dataclass
class Reply:
    ok: bool
    text: str = ""
    error: str = ""
    status: int = 0
    latency: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    refused: bool = False      # модель отказалась отвечать (фильтры)
    unreachable: bool = False  # сеть/гео-блокировка


REFUSAL_MARKERS = (
    "не могу", "не могу помочь", "cannot assist", "can't help", "i'm unable",
    "не могу обсуждать", "выходит за рамки", "as an ai", "i cannot provide",
    "unable to comply", "против моих правил", "не буду",
)

BLOCK_MARKERS = (
    "safety", "blocked", "content_filter", "content policy", "prohibited",
    "risk_control", "sensitive", "data_inspection_failed",
)


def looks_like_refusal(text: str) -> bool:
    low = text.lower()
    if len(low) < 400 and any(marker in low for marker in REFUSAL_MARKERS):
        return "{" not in low  # отказ без попытки вернуть JSON
    return False


def is_unreachable(error: str, status: int) -> bool:
    low = error.lower()
    if status in (403, 451):
        return True
    return any(
        marker in low
        for marker in (
            "cannot connect", "timeout", "timed out", "name or service not known",
            "ssl", "connection reset", "unavailable in your", "unsupported_country",
            "country, region", "not available in your region", "certificate",
        )
    )


async def _post(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
) -> tuple[int, str]:
    async with session.post(
        url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)
    ) as response:
        return response.status, await response.text()


def _is_gen3(model: str) -> bool:
    match = re.search(r"gemini-(\d+)", model or "")
    return bool(match) and int(match.group(1)) >= 3


async def ask(
    session: aiohttp.ClientSession,
    provider: Provider,
    model: str,
    api_key: str,
    system: str,
    prompt: str,
    *,
    json_mode: bool = True,
    max_tokens: int = 1200,
    timeout: int = 90,
) -> Reply:
    """Один запрос к произвольному провайдеру. Никогда не бросает исключений."""
    started = time.monotonic()
    try:
        if provider.kind == "gemini":
            status, body = await _ask_gemini(
                session, provider, model, api_key, system, prompt, json_mode, max_tokens, timeout
            )
        elif provider.kind == "anthropic":
            status, body = await _ask_anthropic(
                session, provider, model, api_key, system, prompt, max_tokens, timeout
            )
        else:
            status, body = await _ask_openai(
                session, provider, model, api_key, system, prompt, json_mode, max_tokens, timeout
            )
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        return Reply(
            ok=False,
            error=detail,
            latency=time.monotonic() - started,
            unreachable=is_unreachable(detail, 0),
        )

    latency = time.monotonic() - started

    if status != 200:
        short = re.sub(r"\s+", " ", body)[:300]
        return Reply(
            ok=False,
            error=f"HTTP {status}: {short}",
            status=status,
            latency=latency,
            unreachable=is_unreachable(short, status),
            refused=any(marker in short.lower() for marker in BLOCK_MARKERS),
        )

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return Reply(ok=False, error="ответ не является JSON", status=status, latency=latency)

    text, tokens_in, tokens_out, blocked = _unpack(provider.kind, data)
    if blocked:
        return Reply(
            ok=False, error="ответ заблокирован фильтрами", status=status,
            latency=latency, refused=True,
        )
    if not text.strip():
        return Reply(ok=False, error="пустой ответ модели", status=status, latency=latency)

    return Reply(
        ok=True,
        text=text,
        status=status,
        latency=latency,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        refused=looks_like_refusal(text),
    )


# --------------------------------------------------------------------------
#  Форматы запросов
# --------------------------------------------------------------------------

async def _ask_gemini(session, provider, model, api_key, system, prompt,
                      json_mode, max_tokens, timeout):
    url = f"{provider.base_url}/models/{model}:generateContent"
    generation: dict[str, Any] = {"maxOutputTokens": max_tokens}
    if json_mode:
        generation["responseMimeType"] = "application/json"
    if _is_gen3(model):
        # У 3.x параметры сэмплирования устарели, зато есть thinkingLevel.
        generation["thinkingConfig"] = {"thinkingLevel": "minimal"}
    else:
        generation["temperature"] = 0.1
        generation["thinkingConfig"] = {"thinkingBudget": 0}

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation,
        "safetySettings": [
            {"category": category, "threshold": "BLOCK_ONLY_HIGH"}
            for category in (
                "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ],
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    return await _post(session, url, headers, payload, timeout)


async def _ask_openai(session, provider, model, api_key, system, prompt,
                      json_mode, max_tokens, timeout):
    url = f"{provider.base_url}/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **provider.extra_headers,
    }
    status, body = await _post(session, url, headers, payload, timeout)

    # Часть провайдеров не поддерживает response_format — повторяем без него.
    if status in (400, 422) and json_mode and "response_format" in body:
        payload.pop("response_format", None)
        status, body = await _post(session, url, headers, payload, timeout)
    return status, body


async def _ask_anthropic(session, provider, model, api_key, system, prompt,
                         max_tokens, timeout):
    url = f"{provider.base_url}/messages"
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    return await _post(session, url, headers, payload, timeout)


# --------------------------------------------------------------------------
#  Разбор ответов
# --------------------------------------------------------------------------

def _unpack(kind: str, data: dict[str, Any]) -> tuple[str, int, int, bool]:
    if kind == "gemini":
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            return "", 0, 0, True
        chunks = []
        for candidate in data.get("candidates") or []:
            reason = str(candidate.get("finishReason") or "")
            if reason in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
                return "", 0, 0, True
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if part.get("thought"):
                    continue
                if part.get("text"):
                    chunks.append(part["text"])
        usage = data.get("usageMetadata") or {}
        return (
            "\n".join(chunks),
            int(usage.get("promptTokenCount") or 0),
            int(usage.get("candidatesTokenCount") or 0),
            False,
        )

    if kind == "anthropic":
        chunks = [
            block.get("text", "")
            for block in data.get("content") or []
            if block.get("type") == "text"
        ]
        usage = data.get("usage") or {}
        return (
            "\n".join(chunks),
            int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0),
            data.get("stop_reason") == "refusal",
        )

    # OpenAI-совместимый
    chunks = []
    for choice in data.get("choices") or []:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # некоторые провайдеры отдают массив блоков
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if content:
            chunks.append(content)
        if choice.get("finish_reason") == "content_filter":
            return "", 0, 0, True
    usage = data.get("usage") or {}
    return (
        "\n".join(chunks),
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        False,
    )


async def list_models(
    session: aiohttp.ClientSession, provider: Provider, api_key: str, timeout: int = 30
) -> tuple[list[str], str]:
    """Спрашивает у провайдера реальный список моделей."""
    try:
        if provider.kind == "gemini":
            url = f"{provider.base_url}/models"
            headers = {"x-goog-api-key": api_key}
        elif provider.kind == "anthropic":
            url = f"{provider.base_url}/models"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        else:
            url = f"{provider.base_url}/models"
            headers = {"Authorization": f"Bearer {api_key}", **provider.extra_headers}

        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            body = await response.text()
            if response.status != 200:
                detail = re.sub(r"\s+", " ", body)[:200]
                return [], f"HTTP {response.status}: {detail}"
            data = json.loads(body)
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"

    items = data.get("data") or data.get("models") or []
    names = []
    for item in items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("id") or item.get("name") or ""
            if name:
                names.append(str(name).removeprefix("models/"))
    return sorted(set(names)), ""
