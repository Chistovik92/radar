"""Расчёт SLA первого ответа."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def deadline(created_at: datetime, minutes: int) -> datetime:
    if minutes <= 0:
        raise ValueError("SLA должен быть положительным")
    return created_at + timedelta(minutes=minutes)


def is_overdue(sla_due_at: datetime, status: str, first_response_at: datetime | None,
               now: datetime | None = None) -> bool:
    return status == "open" and first_response_at is None and sla_due_at <= (now or utcnow())


def response_within_sla(created_at: datetime, first_response_at: datetime | None,
                        minutes: int) -> bool:
    return first_response_at is not None and first_response_at <= deadline(created_at, minutes)
