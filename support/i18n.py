"""Небольшой ru/en словарь; русский — язык по умолчанию."""
from __future__ import annotations

TEXTS = {
    "start": {
        "ru": "Здравствуйте! /support — создать обращение, /tickets — мои обращения.",
        "en": "Hello! Use /support to create a ticket and /tickets to list yours.",
    },
    "created": {
        "ru": "Обращение {number} создано. Опишите вопрос — ответим в этом диалоге.",
        "en": "Ticket {number} created. Describe your question in this dialogue.",
    },
    "not_found": {"ru": "Тикет не найден.", "en": "Ticket not found."},
    "closed": {"ru": "Обращение {number} закрыто. Оцените ответ:", "en": "Ticket {number} closed. Rate the answer:"},
    "denied": {"ru": "Недостаточно прав.", "en": "Permission denied."},
    "error": {"ru": "Не удалось выполнить действие. Попробуйте позже.", "en": "The action failed. Please try later."},
}


def t(key: str, lang: str = "ru", **values: object) -> str:
    item = TEXTS.get(key, {})
    text = item.get(lang) or item.get("ru") or key
    return text.format(**values) if values else text
