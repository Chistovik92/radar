"""Конфигурация только из SUPPORT_* переменных окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote_plus

from dotenv import load_dotenv


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int | None = 0) -> int:
    try:
        value = int((os.getenv(name) or str(default)).strip())
        return value if minimum is None else max(minimum, value)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    admin_id: int
    db_file: str = "data/support.db"
    database_url: str = ""
    group_id: int = 0
    ai_enabled: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    sla_minutes: int = 60
    sla_check_seconds: int = 60
    export_dir: str = "data/exports"
    db_echo: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            token=(os.getenv("SUPPORT_BOT_TOKEN") or "").strip(),
            admin_id=_int("SUPPORT_ADMIN_ID", 0),
            db_file=(os.getenv("SUPPORT_DB_FILE") or "data/support.db").strip(),
            database_url=(os.getenv("SUPPORT_DATABASE_URL") or "").strip(),
            group_id=_int("SUPPORT_GROUP_ID", 0, minimum=None),
            ai_enabled=_bool("SUPPORT_AI") or _bool("support_ai"),
            gemini_api_key=(os.getenv("GEMINI_API_KEY") or "").strip(),
            gemini_model=(os.getenv("SUPPORT_GEMINI_MODEL") or "gemini-2.5-flash").strip(),
            sla_minutes=_int("SUPPORT_SLA_MINUTES", 60, 1),
            sla_check_seconds=_int("SUPPORT_SLA_CHECK_SECONDS", 60, 5),
            export_dir=(os.getenv("SUPPORT_EXPORT_DIR") or "data/exports").strip(),
            db_echo=_bool("SUPPORT_DB_ECHO"),
        )

    def sqlalchemy_url(self) -> str:
        if self.database_url:
            url = self.database_url
            for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
                if url.startswith(prefix):
                    return "postgresql+asyncpg://" + url[len(prefix):]
            return url
        path = os.path.abspath(self.db_file)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return f"sqlite+aiosqlite:///{path}"

    def validate(self) -> None:
        if not self.token:
            raise ValueError("SUPPORT_BOT_TOKEN не задан")
        if self.token == (os.getenv("BOT_TOKEN") or "").strip():
            raise ValueError("SUPPORT_BOT_TOKEN должен отличаться от BOT_TOKEN")
        if self.admin_id <= 0:
            raise ValueError("SUPPORT_ADMIN_ID должен содержать Telegram ID владельца")


def postgres_url(user: str, password: str, host: str, port: int, database: str) -> str:
    """Вспомогательный конструктор для установщика и тестов конфигурации."""
    return f"postgresql+asyncpg://{user}:{quote_plus(password)}@{host}:{port}/{database}"
