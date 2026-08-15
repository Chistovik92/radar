"""Аутентификация веб-панели через Telegram Login Widget.

Пароли не заводим намеренно: у каждого пользователя уже есть подтверждённая
учётная запись Telegram, а роль хранится в базе бота. Виджет отдаёт данные,
подписанные HMAC от токена бота, — этого достаточно, чтобы убедиться, что
данные не подделаны, и не хранить ещё один секрет.

Проверяется три вещи, и все три обязательны:
  * подпись `hash` сходится с вычисленной по токену бота;
  * `auth_date` не старше допустимого — иначе перехваченная однажды ссылка
    работала бы вечно;
  * роль пользователя в базе достаточна для входа.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets as secrets_module
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("radar.web.auth")

# Данные виджета считаются свежими сутки; дальше нужен повторный вход
AUTH_TTL = 86400
SESSION_TTL = 3600 * 4
SESSION_COOKIE = "radar_session"

# Защита от подбора: сколько неудачных попыток допустимо с одного адреса
MAX_ATTEMPTS = 10
ATTEMPT_WINDOW = 600


@dataclass
class Session:
    token: str
    user_key: str
    role: str
    created: float = field(default_factory=time.time)
    seen: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return time.time() - self.created > SESSION_TTL


_sessions: dict[str, Session] = {}
_attempts: dict[str, list[float]] = {}


def _secret_key(bot_token: str) -> bytes:
    """Ключ подписи виджета — SHA-256 от токена бота."""
    return hashlib.sha256(bot_token.encode("utf-8")).digest()


def check_signature(data: dict[str, Any], bot_token: str) -> bool:
    """Сверяет подпись данных виджета."""
    received = str(data.get("hash") or "")
    if not received or not bot_token:
        return False

    pairs = sorted(
        f"{key}={value}" for key, value in data.items() if key != "hash"
    )
    payload = "\n".join(pairs)
    expected = hmac.new(
        _secret_key(bot_token), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # Сравнение постоянного времени: обычное == даёт утечку по таймингу
    return hmac.compare_digest(expected, received)


def check_freshness(data: dict[str, Any], ttl: int = AUTH_TTL) -> bool:
    try:
        issued = int(data.get("auth_date") or 0)
    except (TypeError, ValueError):
        return False
    if issued <= 0:
        return False
    return 0 <= time.time() - issued <= ttl


def rate_limited(address: str) -> bool:
    """Не слишком ли много неудачных попыток с этого адреса."""
    now = time.time()
    history = [stamp for stamp in _attempts.get(address, []) if now - stamp < ATTEMPT_WINDOW]
    _attempts[address] = history
    return len(history) >= MAX_ATTEMPTS


def note_failure(address: str) -> None:
    _attempts.setdefault(address, []).append(time.time())


def clear_failures(address: str) -> None:
    _attempts.pop(address, None)


def authenticate(
    data: dict[str, Any],
    bot_token: str,
    role_lookup,
    address: str = "",
) -> tuple[Session | None, str]:
    """Полная проверка входа. Возвращает (сессия, причина отказа)."""
    if address and rate_limited(address):
        return None, "слишком много попыток, подождите"

    if not check_signature(data, bot_token):
        if address:
            note_failure(address)
        log.warning("Веб-панель: подпись не сошлась (адрес %s)", address or "?")
        return None, "подпись не сошлась"

    if not check_freshness(data):
        return None, "данные входа устарели, войдите заново"

    user_key = str(data.get("id") or "")
    if not user_key:
        return None, "не передан идентификатор"

    role = role_lookup(user_key)
    if not role:
        return None, "пользователь не зарегистрирован в боте"

    from .. import roles as role_module

    if not role_module.is_admin(role):
        log.info("Веб-панель: отказ пользователю %s с ролью %s", user_key, role)
        return None, "нужны права администратора"

    if address:
        clear_failures(address)

    session = Session(
        token=secrets_module.token_urlsafe(32),
        user_key=user_key,
        role=role,
    )
    _sessions[session.token] = session
    log.info("Веб-панель: вход %s (%s)", user_key, role)
    return session, ""


def session_by_token(token: str) -> Session | None:
    session = _sessions.get(token or "")
    if session is None:
        return None
    if session.expired:
        _sessions.pop(token, None)
        return None
    session.seen = time.time()
    return session


def drop_session(token: str) -> None:
    _sessions.pop(token or "", None)


def cleanup() -> int:
    stale = [token for token, item in _sessions.items() if item.expired]
    for token in stale:
        _sessions.pop(token, None)
    return len(stale)


def active_sessions() -> int:
    cleanup()
    return len(_sessions)
