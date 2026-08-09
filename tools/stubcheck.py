#!/usr/bin/env python3
"""Импортирует весь проект с заглушками aiogram/aiohttp/google-genai/aiofiles.

Ловит опечатки в именах, неверные импорты и ошибки времени импорта без
установки зависимостей и без сети.

    python3 tools/stubcheck.py
"""

from __future__ import annotations

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("BOT_TOKEN", "123456:stub")
os.environ.setdefault("SUPERADMIN_ID", "1")
os.environ.setdefault("GEMINI_API_KEY", "")


class Any:
    """Универсальная заглушка: любой атрибут, вызов, оператор и контекст."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, item):
        return Any()

    def __call__(self, *args, **kwargs):
        return Any()

    def __or__(self, other):
        return Any()

    def __and__(self, other):
        return Any()

    def __eq__(self, other):
        return Any()

    def __hash__(self):
        return 0

    async def __aenter__(self):
        return Any()

    async def __aexit__(self, *args):
        return False

    def __enter__(self):
        return Any()

    def __exit__(self, *args):
        return False


def module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    mod.__getattr__ = lambda item: Any()  # type: ignore[attr-defined]
    sys.modules[name] = mod
    return mod


class Router:
    def __init__(self, *args, **kwargs):
        self.name = kwargs.get("name", "")

    def __getattr__(self, item):
        return Any()

    def message(self, *args, **kwargs):
        return lambda func: func

    def callback_query(self, *args, **kwargs):
        return lambda func: func


class Dispatcher(Router):
    def include_router(self, router):
        return router


def install() -> None:
    module("dotenv", load_dotenv=lambda *a, **k: None)
    module("aiofiles", open=Any())

    module("aiohttp", ClientSession=Any, ClientTimeout=Any)

    genai = module("google.genai", Client=Any, types=Any())
    module("google", genai=genai)
    module("google.genai.types")

    aiogram = module(
        "aiogram", Bot=Any, Dispatcher=Dispatcher, Router=Router, F=Any(), BaseMiddleware=object
    )
    module("aiogram.client.default", DefaultBotProperties=Any)
    module("aiogram.enums", ParseMode=Any())
    module(
        "aiogram.exceptions",
        TelegramBadRequest=type("TelegramBadRequest", (Exception,), {}),
        TelegramForbiddenError=type("TelegramForbiddenError", (Exception,), {}),
        TelegramRetryAfter=type("TelegramRetryAfter", (Exception,), {}),
    )
    module("aiogram.filters", Command=Any, CommandStart=Any)
    module("aiogram.fsm.context", FSMContext=Any)
    module("aiogram.fsm.state", State=Any, StatesGroup=object)
    module("aiogram.fsm.storage.memory", MemoryStorage=Any)
    module(
        "aiogram.types",
        CallbackQuery=Any, InlineKeyboardButton=Any, InlineKeyboardMarkup=Any,
        Message=Any, TelegramObject=Any,
    )
    aiogram.types = sys.modules["aiogram.types"]


def main() -> int:
    install()
    modules = [
        "radar", "radar.config", "radar.textutils", "radar.roles", "radar.matching",
        "radar.storage", "radar.ai", "radar.geocode", "radar.weather", "radar.sources",
        "radar.tg", "radar.keyboards", "radar.states", "radar.middlewares",
        "radar.monitor", "radar.handlers", "radar.handlers.common",
        "radar.handlers.locations", "radar.handlers.settings",
        "radar.handlers.sources", "radar.handlers.users", "radar.handlers.assistant",
        "main",
    ]
    failures = 0
    for name in modules:
        try:
            __import__(name)
            print(f"  ok   {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\nИмпортировано модулей: {len(modules) - failures}/{len(modules)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
