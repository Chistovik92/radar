"""Тикеты бота поддержки в веб-панели (6.0.2).

Панель читает и пишет ``support.db`` напрямую через тот же async-движок,
что и отдельный бот поддержки. Доступ — модератор и выше (совпадает с
``support.core.roles.is_moderator``), сопоставление — по Telegram ID
(``session.user_key`` ↔ ``User.external_id``).

Слой включается, только когда поддержка сконфигурирована: задан
``SUPPORT_DATABASE_URL`` либо существует файл ``SUPPORT_DB_FILE``
(по умолчанию ``data/support.db``). Иначе страница и пункт меню скрыты.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
from typing import Any

from .. import roles as radar_roles

log = logging.getLogger("radar.web.support_tickets")

_support_db = None
_support_repo = None
_configured: bool | None = None


def _support_url() -> str:
    """URL базы поддержки по тем же правилам, что ``support.core.config``."""
    explicit = (os.getenv("SUPPORT_DATABASE_URL") or "").strip()
    if explicit:
        url = explicit
        for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url
    db_file = (os.getenv("SUPPORT_DB_FILE") or "data/support.db").strip()
    path = os.path.abspath(db_file)
    return f"sqlite+aiosqlite:///{path}"


def available() -> bool:
    """Поддержка доступна в панели: слой есть и хотя бы один источник данных."""
    if (os.getenv("SUPPORT_DATABASE_URL") or "").strip():
        return True
    db_file = (os.getenv("SUPPORT_DB_FILE") or "data/support.db").strip()
    return os.path.isfile(db_file)


async def _repo():
    """Лениво поднять движок и репозиторий поддержки."""
    global _support_db, _support_repo
    if _support_repo is not None:
        return _support_repo
    from support.core.config import Settings
    from support.db.engine import Database
    from support.db.repo import SupportRepository

    config = Settings.from_env()
    _support_db = Database(config.sqlalchemy_url(), config.db_echo)
    await _support_db.create_schema()
    _support_repo = SupportRepository(_support_db, config.sla_minutes)
    return _support_repo


def _external_id(session) -> int:
    try:
        return int(str(session.user_key or "").split(":")[-1])
    except (ValueError, IndexError):
        return 0


def can_moderate(session) -> bool:
    """Модератор и выше — как в боте поддержки."""
    return radar_roles.is_moderator(session.role)


async def sync_role(session) -> None:
    """Подтянуть роль оператора из radar-базы в support-базу.

    Панель судит о правах по роли в основной базе ``radar``, а бот
    поддержки и репозиторий тикетов — по роли в ``support.db``. Без
    синхронизации модератор, назначенный в панели, не увидел бы чужие
    тикеты: ``list_tickets`` вернул бы только его собственные.

    Роли называются одинаково (``user/moderator/admin/superadmin``),
    поэтому сопоставление прямое. Запись в support-базе создаётся, если
    её ещё нет; роль понижается/повышается до роли radar, но суперадмин
    не трогается (его роль в support-базе задаёт ``SUPPORT_ADMIN_ID``).
    """
    external_id = _external_id(session)
    if external_id <= 0:
        return
    role = str(session.role or "")
    if role not in ("user", "moderator", "admin", "superadmin"):
        return
    try:
        repo = await _repo()
        await repo.get_or_create_user(external_id)
        await repo.set_role_direct(external_id, role)
    except Exception as exc:  # noqa: BLE001 — синхронизация не должна ронять страницу
        log.warning("Не удалось синхронизировать роль %s в support.db: %s",
                    external_id, exc)


async def list_tickets(session) -> list[dict[str, Any]]:
    repo = await _repo()
    tickets = await repo.list_tickets(_external_id(session))
    return [repo._ticket_dict(ticket) for ticket in tickets]


async def ticket_detail(session, reference: str) -> dict[str, Any] | None:
    repo = await _repo()
    data = await repo.export_data(reference, _external_id(session))
    if data is None:
        return None
    return data


async def reply(session, reference: str, text: str) -> tuple[bool, str]:
    """Ответ оператора. Возвращает (успех, сообщение)."""
    from support.db.repo import TicketClosed

    repo = await _repo()
    body = " ".join((text or "").split())
    if not body:
        return False, "Текст ответа пуст."
    try:
        result = await repo.add_message(reference, _external_id(session), body)
    except TicketClosed as exc:
        return False, f"Тикет уже закрыт ({exc})."
    if result is None:
        return False, "Тикет не найден или недостаточно прав."
    return True, "Ответ добавлен."


async def close_ticket(session, reference: str) -> tuple[bool, str]:
    repo = await _repo()
    ticket = await repo.close_ticket(reference, _external_id(session))
    if ticket is None:
        return False, "Тикет не найден или недостаточно прав."
    return True, "Тикет закрыт."


async def set_priority(session, reference: str, priority: str) -> tuple[bool, str]:
    repo = await _repo()
    ticket = await repo.set_priority(reference, _external_id(session), priority)
    if ticket is None:
        return False, "Не удалось изменить приоритет (доступ или значение)."
    return True, f"Приоритет: {ticket.priority}."
