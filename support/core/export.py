"""Человекочитаемый TXT-экспорт и файловый архив."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

MSK = timezone(timedelta(hours=3))


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _time(value: datetime | None, with_date: bool = False) -> str:
    value = _aware(value)
    if value is None:
        return "—"
    local = value.astimezone(MSK)
    return local.strftime("%d.%m.%Y %H:%M" if with_date else "%H:%M")


def _name(user: dict[str, Any] | None) -> str:
    if not user:
        return "—"
    username = (user.get("username") or "").lstrip("@")
    return f"@{username}" if username else f"id {user.get('external_id', '—')}"


def render_dialogue(data: dict[str, Any]) -> str:
    """Собирает документ из уже выбранных данных, без обращения к БД."""
    ticket = data["ticket"]
    lines = [
        f"Обращение {ticket['number']}",
        f"Тема: {ticket.get('subject') or '—'}",
        f"Категория: {ticket.get('category') or '—'}",
        f"Автор: {_name(data.get('author'))} (id {data.get('author', {}).get('external_id', '—')})",
        f"Оператор: {_name(data.get('assignee'))}",
        f"Открыто: {_time(ticket.get('created_at'), True)} (MSK)",
        f"Закрыто: {_time(ticket.get('closed_at'), True)} (MSK)",
        "",
    ]
    for message in data.get("messages", []):
        sender = message.get("sender")
        if message.get("kind") == "system":
            icon, name = "⚙️", "система"
        elif sender and sender.get("id") == ticket.get("author_id"):
            icon, name = "👤", _name(sender)
        else:
            icon, name = "🛡", _name(sender)
        lines.append(f"[{_time(message.get('created_at'))}] {icon} {name}: {message.get('body', '')}")
    return "\n".join(lines).rstrip() + "\n"


def save_dialogue(data: dict[str, Any], directory: str) -> str:
    number = data["ticket"]["number"].lstrip("#")
    safe = "".join(char for char in number if char.isdigit() or char == "-")
    if not safe:
        raise ValueError("Некорректный номер тикета")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{safe}.txt")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=directory,
        prefix=f".{safe}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = handle.name
        handle.write(render_dialogue(data))
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
