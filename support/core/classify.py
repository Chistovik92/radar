"""Детерминированные FAQ/категории и необязательный Gemini."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable

log = logging.getLogger("support.ai")

DEFAULT_FAQ = {
    "пароль": "Пароль можно сменить в личном кабинете. Если письмо не приходит, проверьте спам.",
    "оплата": "Проверьте статус платежа в личном кабинете. Если сумма списана, создайте тикет и приложите чек.",
    "vpn": "Перезапустите VPN-приложение и проверьте соединение. Если ошибка остаётся, создайте тикет со скриншотом.",
}
CATEGORIES = {
    "оплата": ("оплат", "платеж", "платёж", "деньги", "чек", "подписк"),
    "доступ": ("парол", "войти", "вход", "доступ", "аккаунт", "блокир"),
    "VPN": ("vpn", "впн", "подключ", "сервер", "конфиг"),
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def classify(text: str) -> str:
    value = normalize(text)
    for category, words in CATEGORIES.items():
        if any(word in value for word in words):
            return category
    return "прочее"


def faq_answer(text: str, entries: dict[str, str] | None = None) -> str | None:
    value = normalize(text)
    if not value:
        return None
    source = dict(DEFAULT_FAQ)
    source.update(entries or {})
    matches = [(key, answer) for key, answer in source.items() if normalize(key) and normalize(key) in value]
    if not matches:
        return None
    matches.sort(key=lambda pair: len(pair[0]), reverse=True)
    return matches[0][1]


class GeminiAssistant:
    """Ленивый клиент: библиотека и сеть не нужны при выключенном SUPPORT_AI."""

    def __init__(self, enabled: bool, api_key: str, model: str, timeout: float = 45.0) -> None:
        self.enabled = bool(enabled and api_key)
        self.model = model
        self.timeout = timeout
        self._client: Any = None
        if self.enabled:
            try:
                from google import genai
                self._client = genai.Client(api_key=api_key)
            except Exception as exc:  # noqa: BLE001
                log.warning("Gemini отключён: %s", exc)
                self.enabled = False

    async def category(self, text: str) -> str | None:
        """Возвращает только известную категорию; ошибки оставляет fallback'у."""
        if not self.enabled or not normalize(text):
            return None
        allowed = ", ".join([*CATEGORIES, "прочее"])
        prompt = (
            "Определи категорию обращения в поддержку. Ответь одним словом строго "
            f"из списка: {allowed}. Обращение: " + text[:6000]
        )
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(model=self.model, contents=prompt),
                timeout=self.timeout,
            )
            answer = normalize(getattr(response, "text", "") or "")
            return next((name for name in [*CATEGORIES, "прочее"] if normalize(name) == answer), None)
        except Exception as exc:  # noqa: BLE001
            log.warning("Ошибка классификации Gemini: %s", exc)
            return None

    async def ask(self, question: str) -> str | None:
        if not self.enabled or not normalize(question):
            return None
        prompt = (
            "Ты помощник службы поддержки. Отвечай кратко, по-русски, не выдумывай "
            "факты и не запрашивай пароли. Вопрос: " + question[:6000]
        )
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(model=self.model, contents=prompt),
                timeout=self.timeout,
            )
            return (getattr(response, "text", "") or "").strip() or None
        except Exception as exc:  # noqa: BLE001 — AI никогда не должен ронять тикет
            log.warning("Ошибка Gemini: %s", exc)
            return None


class KnowledgeBase:
    def __init__(self, ai: GeminiAssistant | None = None) -> None:
        self.ai = ai

    async def category(self, text: str) -> str:
        if self.ai is not None and self.ai.enabled:
            answer = await self.ai.category(text)
            if answer:
                return answer
        return classify(text)

    async def answer(self, text: str, entries: dict[str, str] | None = None) -> str | None:
        deterministic = faq_answer(text, entries)
        if deterministic is not None or self.ai is None:
            return deterministic
        return await self.ai.ask(text)
