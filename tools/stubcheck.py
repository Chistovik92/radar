#!/usr/bin/env python3
"""Импортирует весь проект с заглушками aiogram/aiohttp/google-genai/aiofiles.

Ловит опечатки в именах, неверные импорты и ошибки времени импорта без
установки зависимостей и без сети.

    python3 tools/stubcheck.py
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("BOT_TOKEN", "123456:stub")
os.environ.setdefault("SUPERADMIN_ID", "1")
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("DB_PASSWORD", "stub")

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

    # SQLAlchemy: заглушки достаточно, чтобы модели импортировались.
    module(
        "sqlalchemy", BigInteger=Any, Boolean=Any, DateTime=Any, Float=Any,
        ForeignKey=Any, Index=Any, Integer=Any, String=Any, Text=Any,
        UniqueConstraint=Any, delete=Any(), func=Any(), select=Any(), text=Any(),
        pool=Any(),
    )
    module("sqlalchemy.dialects", postgresql=Any())
    module("sqlalchemy.dialects.postgresql", JSONB=Any, insert=Any())
    module(
        "sqlalchemy.orm",
        DeclarativeBase=object, Mapped=Any, mapped_column=Any(), relationship=Any(),
    )
    module(
        "sqlalchemy.ext.asyncio",
        AsyncEngine=Any, AsyncSession=Any, async_sessionmaker=Any,
        create_async_engine=Any(), async_engine_from_config=Any(),
    )
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
    module("aiogram.filters", Command=Any, CommandStart=Any, StateFilter=Any)
    module("aiogram.fsm.context", FSMContext=Any)
    module("aiogram.fsm.state", State=Any, StatesGroup=object)
    module("aiogram.fsm.storage.memory", MemoryStorage=Any)
    module(
        "aiogram.types",
        CallbackQuery=Any, InlineKeyboardButton=Any, InlineKeyboardMarkup=Any,
        KeyboardButton=Any, ReplyKeyboardMarkup=Any, BufferedInputFile=Any,
        LinkPreviewOptions=Any,
        Message=Any, TelegramObject=Any,
    )
    aiogram.types = sys.modules["aiogram.types"]


def smoke_checks() -> list[str]:
    """Проверки, которые ловят ошибки уровня рантайма, а не импорта.

    Импорт модуля не выполняет тела функций, поэтому опечатки в обращениях
    вида `module.attribute` всплывают только в продакшене. Здесь перечислены
    точки, где такая ошибка уже случалась.
    """
    import importlib
    import types

    problems: list[str] = []

    # 1. `from pkg import submodule` обязан давать модуль, а не функцию.
    for package, submodule in (
        ("radar.db", "engine"),
        ("radar.db", "repo"),
        ("radar.db", "importer"),
        ("radar.db", "models"),
        ("radar.platforms", "base"),
    ):
        parent = importlib.import_module(package)
        value = getattr(parent, submodule, None)
        if not isinstance(value, types.ModuleType):
            problems.append(
                f"{package}.{submodule} — это {type(value).__name__}, а не модуль: "
                f"имя затенено в {package}/__init__.py"
            )

    # 2. Имена, к которым обращается main.py при запуске.
    main_module = importlib.import_module("main")
    for holder, attribute in (
        ("db_engine", "wait_ready"),
        ("db_engine", "AuthenticationError"),
        ("db_engine", "dispose"),
        ("importer", "is_empty"),
        ("importer", "run"),
        ("repo", "load_features"),
        ("repo", "purge_old_events"),
        ("features", "apply"),
        ("features", "FLAGS"),
        ("storage", "load"),
        ("storage", "meta_get"),
        ("storage", "meta_set"),
        ("monitor", "run"),
    ):
        target = getattr(main_module, holder, None)
        if target is None:
            problems.append(f"main.py: имя «{holder}» не импортировано")
        elif not hasattr(target, attribute):
            problems.append(f"main.py: у «{holder}» нет атрибута «{attribute}»")

    return problems


def main() -> int:
    install()
    modules = [
        "radar", "radar.config", "radar.textutils", "radar.roles", "radar.matching",
        "radar.identity", "radar.features", "radar.logs", "radar.presets", "radar.sourcecheck", "radar.storage", "radar.exporting", "radar.ratelimit", "radar.ai", "radar.geocode", "radar.weather", "radar.sources",
        "radar.tg", "radar.keyboards", "radar.states", "radar.middlewares",
        "radar.monitor", "radar.handlers", "radar.handlers.common",
        "radar.handlers.locations", "radar.handlers.settings",
        "radar.handlers.sources", "radar.handlers.users", "radar.handlers.features", "radar.handlers.logs", "radar.handlers.assistant",
        "radar.platforms", "radar.platforms.base",
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

    if failures:
        return 1

    issues = smoke_checks()
    for issue in issues:
        print(f"  ✗ {issue}")
    if issues:
        print(f"Проблем на уровне рантайма: {len(issues)}")
        return 1
    print("Рантайм-проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
