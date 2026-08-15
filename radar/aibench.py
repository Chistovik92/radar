"""Сравнение провайдеров ИИ прямо из бота.

Раньше это был отдельный стенд в `bench/`, который на сервере никто
не запускал: нужно было зайти по SSH, положить ключи в отдельный файл,
поставить зависимости. Теперь тот же набор тест-кейсов прогоняется
по кнопке, а ключи берутся из общего `.env`.

Что проверяется
---------------
Одинаковые сообщения городских служб уходят каждому провайдеру, у которого
задан ключ. Сравнивается не «качество вообще», а именно то, что нужно
«Радару»: правильные категории, извлечённые улицы и дома, отсутствие ложных
тревог на шуме и — отдельной колонкой — способность вообще разбирать
сообщения о БПЛА. Провайдер, который срезает военные темы, для оповещений
непригоден, каким бы точным он ни был в остальном.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

import aiohttp

from . import secrets
from .textutils import esc

log = logging.getLogger("radar.aibench")

REQUEST_TIMEOUT = 60
PAUSE = 1.5


@dataclass(frozen=True)
class Provider:
    key: str
    title: str
    env: str
    base_url: str
    model: str
    kind: str = "openai"       # openai | gemini | anthropic
    region: str = ""


PROVIDERS: tuple[Provider, ...] = (
    Provider("google", "Google Gemini", "GEMINI_API_KEY",
             "https://generativelanguage.googleapis.com/v1beta",
             "gemini-3.5-flash-lite", kind="gemini", region="США"),
    Provider("groq", "Groq", "GROQ_API_KEY",
             "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", region="США"),
    Provider("cerebras", "Cerebras", "CEREBRAS_API_KEY",
             "https://api.cerebras.ai/v1", "gpt-oss-120b", region="США"),
    Provider("mistral", "Mistral", "MISTRAL_API_KEY",
             "https://api.mistral.ai/v1", "mistral-small-latest", region="Франция"),
    Provider("openrouter", "OpenRouter", "OPENROUTER_API_KEY",
             "https://openrouter.ai/api/v1", "deepseek/deepseek-chat-v3.1:free",
             region="агрегатор"),
    Provider("deepseek", "DeepSeek", "DEEPSEEK_API_KEY",
             "https://api.deepseek.com/v1", "deepseek-chat", region="КНР"),
    Provider("zai", "Z.ai / GLM", "ZAI_API_KEY",
             "https://api.z.ai/api/paas/v4", "glm-4.5-air", region="КНР"),
    Provider("moonshot", "Moonshot Kimi", "MOONSHOT_API_KEY",
             "https://api.moonshot.ai/v1", "moonshot-v1-32k", region="КНР"),
    Provider("qwen", "Alibaba Qwen", "DASHSCOPE_API_KEY",
             "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-turbo",
             region="КНР"),
    Provider("openai", "OpenAI", "OPENAI_API_KEY",
             "https://api.openai.com/v1", "gpt-4.1-mini", region="США"),
    Provider("anthropic", "Anthropic Claude", "ANTHROPIC_API_KEY",
             "https://api.anthropic.com/v1", "claude-haiku-4-5-20251001",
             kind="anthropic", region="США"),
)


@dataclass(frozen=True)
class Case:
    ident: str
    text: str
    categories: tuple[str, ...]
    streets: tuple[str, ...] = ()
    sensitive: bool = False


CASES: tuple[Case, ...] = (
    Case("jkh", "Внимание! Отключение холодной воды по улице Чапаева, дома 12 и 14 "
                "до 18:00 в связи с устранением порыва.",
         ("jkh",), ("чапаева",)),
    Case("jkh-city", "Начинаются гидравлические испытания: горячая вода будет "
                     "отключена во всём городе с 12 по 22 августа.", ("jkh",)),
    Case("bpla", "Внимание! На территории области объявлена опасность атаки "
                 "беспилотных летательных аппаратов. Сообщайте по номеру 112.",
         ("bpla",), sensitive=True),
    Case("bpla-clear", "Отбой беспилотной опасности. Обстановка спокойная.",
         ("bpla",), sensitive=True),
    Case("mchs", "Экстренное предупреждение МЧС: гроза с усилением ветра "
                 "до 25 м/с и градом в ближайшие два часа.", ("mchs",)),
    Case("noise", "Розыгрыш сертификата на 5000 рублей среди подписчиков! "
                  "Подпишись и поставь лайк.", ()),
    Case("noise-sport", "«Сокол» обыграл соперника со счётом 2:1 в домашнем матче.", ()),
)

SYSTEM = (
    "Ты — аналитик сообщений городских служб. Отвечаешь одним валидным "
    "JSON-объектом без пояснений и без Markdown."
)

PROMPT = """Разбери сообщение.

СООБЩЕНИЕ:
\"\"\"{text}\"\"\"

Категории: "bpla" (БПЛА, ракетная опасность, воздушная тревога),
"mchs" (МЧС, ЧС, штормовое предупреждение), "jkh" (вода, свет, газ,
отопление, аварии на сетях), "whitelist" (ограничения связи).

Верни JSON:
{{"relevant": true|false, "categories": ["jkh"],
  "streets": [{{"street": "улица Чапаева", "houses": ["12"]}}],
  "summary": "кратко"}}

Реклама, розыгрыши, спорт → relevant=false, categories=[]."""


@dataclass
class ProviderResult:
    provider: Provider
    reachable: bool = False
    error: str = ""
    runs: int = 0
    parsed: int = 0
    correct: int = 0
    streets_hit: int = 0
    streets_total: int = 0
    false_alarms: int = 0
    censored: int = 0
    sensitive_total: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.runs if self.runs else 0.0

    @property
    def latency(self) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        return ordered[len(ordered) // 2]

    @property
    def military_ok(self) -> bool:
        return self.sensitive_total > 0 and self.censored == 0


@dataclass
class Report:
    results: list[ProviderResult] = field(default_factory=list)
    finished: datetime = field(default_factory=datetime.now)


_running = False
_last: Report | None = None


def is_running() -> bool:
    return _running


def last_report() -> Report | None:
    return _last


def configured_providers() -> list[Provider]:
    """Провайдеры, у которых задан ключ."""
    return [item for item in PROVIDERS if secrets.get(item.env)]


# --------------------------------------------------------------------------
#  Запросы
# --------------------------------------------------------------------------

async def _ask(session: aiohttp.ClientSession, provider: Provider,
               api_key: str, prompt: str) -> tuple[str, str]:
    """Возвращает (ответ, ошибка)."""
    try:
        if provider.kind == "gemini":
            url = f"{provider.base_url}/models/{provider.model}:generateContent"
            headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
            payload = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": SYSTEM}]},
                "generationConfig": {
                    "maxOutputTokens": 700,
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingLevel": "minimal"},
                },
            }
        elif provider.kind == "anthropic":
            url = f"{provider.base_url}/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            payload = {
                "model": provider.model, "max_tokens": 700, "system": SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
            }
        else:
            url = f"{provider.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 700,
                "temperature": 0.1,
            }

        async with session.post(url, json=payload, headers=headers) as response:
            body = await response.text()
            if response.status != 200:
                # Свёртку пробелов выносим из f-строки: обратный слэш внутри
                # выражения запрещён до Python 3.12, а образ собран на 3.11.
                detail = re.sub(r"\s+", " ", body)[:120]
                return "", f"HTTP {response.status}: {detail}"
            data = json.loads(body)
    except asyncio.TimeoutError:
        return "", "таймаут"
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}"

    return _extract(provider.kind, data), ""


def _extract(kind: str, data: dict[str, Any]) -> str:
    if kind == "gemini":
        chunks = []
        for candidate in data.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                if part.get("text"):
                    chunks.append(part["text"])
        return "\n".join(chunks)
    if kind == "anthropic":
        return "\n".join(
            block.get("text", "") for block in data.get("content") or []
            if block.get("type") == "text"
        )
    for choice in data.get("choices") or []:
        content = (choice.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
    return ""


def _parse(raw: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.S)
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _score(case: Case, payload: dict[str, Any], result: ProviderResult) -> None:
    relevant = bool(payload.get("relevant"))
    categories = {
        str(item) for item in (payload.get("categories") or [])
        if str(item) in ("jkh", "bpla", "mchs", "whitelist")
    }
    if not relevant:
        categories = set()

    expected = set(case.categories)
    if categories == expected:
        result.correct += 1
    if expected and not categories:
        if case.sensitive:
            result.censored += 1
    if not expected and categories:
        result.false_alarms += 1

    if case.streets:
        result.streets_total += 1
        found = " ".join(
            str(item.get("street", "") if isinstance(item, dict) else item).lower()
            for item in (payload.get("streets") or [])
        )
        if all(part in found for part in case.streets):
            result.streets_hit += 1


# --------------------------------------------------------------------------
#  Прогон
# --------------------------------------------------------------------------

async def run(
    progress: Callable[[int, int, str], Awaitable[None]] | None = None,
) -> Report:
    """Прогоняет все настроенные провайдеры по набору кейсов."""
    global _running, _last

    if _running:
        raise RuntimeError("Проверка уже выполняется")

    providers = configured_providers()
    if not providers:
        raise RuntimeError("Нет провайдеров с заданными ключами")

    _running = True
    report = Report()
    total = len(providers) * len(CASES)
    done = 0

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for provider in providers:
                api_key = secrets.get(provider.env)
                result = ProviderResult(provider=provider)

                for case in CASES:
                    if case.sensitive:
                        result.sensitive_total += 1

                    started = time.monotonic()
                    answer, error = await _ask(
                        session, provider, api_key, PROMPT.format(text=case.text)
                    )
                    result.latencies.append(time.monotonic() - started)
                    result.runs += 1
                    done += 1

                    if error:
                        result.error = result.error or error
                        # Ключ неверен или провайдер недоступен — дальше нет смысла
                        if "401" in error or "403" in error or "таймаут" in error:
                            done += len(CASES) - result.runs
                            break
                    else:
                        result.reachable = True
                        payload = _parse(answer)
                        if payload is not None:
                            result.parsed += 1
                            _score(case, payload, result)
                        elif case.sensitive:
                            result.censored += 1

                    if progress:
                        await progress(done, total, provider.title)
                    await asyncio.sleep(PAUSE)

                report.results.append(result)

        _last = report
        log.info("Сравнение провайдеров завершено: %d участников", len(report.results))
        return report
    finally:
        _running = False


def render(report: Report) -> str:
    """Отчёт для сообщения в боте."""
    lines = [
        "🧪 <b>Сравнение провайдеров ИИ</b>",
        f"<i>{report.finished:%d.%m.%Y %H:%M}, кейсов на провайдера: {len(CASES)}</i>",
        "",
    ]

    ranked = sorted(report.results, key=lambda item: (-item.accuracy, item.latency))
    for item in ranked:
        if not item.reachable:
            lines.append(f"❌ <b>{esc(item.provider.title)}</b> — {esc(item.error or 'нет ответа')}")
            continue

        military = "✅ разбирает" if item.military_ok else (
            f"⚠️ срезано {item.censored}/{item.sensitive_total}"
        )
        streets = (
            f"{item.streets_hit}/{item.streets_total}" if item.streets_total else "—"
        )
        lines.append(
            f"<b>{esc(item.provider.title)}</b> · {esc(item.provider.region)}\n"
            f"  точность {item.accuracy * 100:.0f}% · JSON {item.parsed}/{item.runs} · "
            f"адреса {streets}\n"
            f"  военные темы: {military} · ложных тревог: {item.false_alarms} · "
            f"{item.latency:.1f} с"
        )

    working = [item for item in ranked if item.reachable]
    if working:
        lines.append("")
        best = working[0]
        lines.append(f"🏆 <b>Точнее всех:</b> {esc(best.provider.title)}")
        military = [item for item in working if item.military_ok]
        if military:
            lines.append(
                f"🛸 <b>Без цензуры военных тем:</b> {esc(military[0].provider.title)}"
            )
        else:
            lines.append(
                "⚠️ <b>Все провайдеры срезают военные темы</b> — оповещения "
                "о БПЛА придётся оставить на эвристике."
            )
    else:
        lines.append("")
        lines.append("Ни один провайдер не ответил. Проверьте ключи и доступ в сеть.")

    return "\n".join(lines)
