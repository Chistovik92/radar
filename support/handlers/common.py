"""Общие Telegram-операции с устойчивостью к сетевым ошибкам."""
from __future__ import annotations

import html
import logging
import os
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from ..core.export import save_dialogue
from ..db.models import Ticket, TicketMessage, User
from ..db.repo import SupportRepository, ticket_number

log = logging.getLogger("support.telegram")


def rating_keyboard(ticket: Ticket) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👍", callback_data=f"support:rate:{ticket.id}:1"),
        InlineKeyboardButton(text="👎", callback_data=f"support:rate:{ticket.id}:-1"),
    ]])


def new_ticket_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Создать тикет", callback_data="support:new")
    ]])


async def safe(coro, *, where: str = "Telegram") -> Any:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — ошибка доставки не отменяет запись тикета
        log.warning("%s: %s", where, exc)
        return None


def ticket_line(ticket: Ticket) -> str:
    return (f"{ticket_number(ticket)} · {ticket.status} · {ticket.priority} · "
            f"{html.escape(ticket.subject or 'Без темы')}")


async def ensure_group_topic(bot: Bot, repo: SupportRepository, ticket: Ticket,
                             group_id: int) -> Ticket:
    if not group_id or ticket.group_id == group_id and ticket.thread_id:
        return ticket
    topic = await safe(bot.create_forum_topic(
        chat_id=group_id, name=f"{ticket_number(ticket)} {ticket.subject or 'Поддержка'}"[:128]
    ), where="создание форум-топика")
    thread_id = getattr(topic, "message_thread_id", None)
    if thread_id:
        attached = await repo.attach_topic(ticket.id, group_id, thread_id)
        return attached or ticket
    return ticket


async def send_attachment(bot: Bot, chat_id: int, message: TicketMessage,
                          thread_id: int | None = None, caption: str = "") -> Any:
    kwargs: dict[str, Any] = {"chat_id": chat_id, "caption": caption[:1024]}
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    file_id = message.attachment_file_id
    methods = {
        "photo": bot.send_photo, "video": bot.send_video, "animation": bot.send_animation,
        "audio": bot.send_audio, "voice": bot.send_voice, "video_note": bot.send_video_note,
        "sticker": bot.send_sticker,
    }
    method = methods.get(message.attachment_type, bot.send_document)
    parameter = "sticker" if message.attachment_type == "sticker" else (
        "photo" if message.attachment_type == "photo" else
        "video_note" if message.attachment_type == "video_note" else
        message.attachment_type if message.attachment_type in {"video", "animation", "audio", "voice"} else "document"
    )
    if message.attachment_type in {"video_note", "sticker"}:
        kwargs.pop("caption", None)
    return await safe(method(**{parameter: file_id}, **kwargs), where="пересылка вложения")


async def notify_message(bot: Bot, repo: SupportRepository, ticket: Ticket,
                         sender: User, message: TicketMessage, group_id: int,
                         mirror_group: bool = True) -> None:
    """Доставляет копию другой стороне, сохраняя исходный ticket в БД."""
    operator = sender.id != ticket.author_id
    targets: list[int] = []
    if operator:
        data = await repo.export_data(ticket.id, sender.external_id)
        author_external = (data or {}).get("author", {}).get("external_id")
        if author_external and author_external != sender.external_id:
            targets.append(author_external)
    else:
        data = await repo.export_data(ticket.id, sender.external_id)
        assignee = (data or {}).get("assignee") or {}
        if assignee.get("external_id"):
            targets.append(assignee["external_id"])
    text = html.escape(message.body or "")
    for target in targets:
        if message.kind == "attachment":
            await send_attachment(bot, target, message, caption=text)
        elif text:
            await safe(bot.send_message(target, f"{ticket_number(ticket)}\n{text}"), where="ответ клиенту")
    if not mirror_group:
        return
    if ticket.group_id and ticket.thread_id:
        if message.kind == "attachment":
            await send_attachment(bot, ticket.group_id, message, ticket.thread_id, text)
        elif text:
            await safe(bot.send_message(
                ticket.group_id, text, message_thread_id=ticket.thread_id
            ), where="сообщение в топик")
    elif group_id:
        ticket = await ensure_group_topic(bot, repo, ticket, group_id)
        if ticket.group_id and ticket.thread_id:
            if message.kind == "attachment":
                await send_attachment(bot, ticket.group_id, message, ticket.thread_id, text)
            elif text:
                await safe(bot.send_message(
                    ticket.group_id, text, message_thread_id=ticket.thread_id
                ), where="первое сообщение в топик")


async def deliver_export(bot: Bot, repo: SupportRepository, ticket: Ticket,
                         actor_external_id: int, export_dir: str, chat_id: int,
                         thread_id: int | None = None) -> str | None:
    data = await repo.export_data(ticket.id, actor_external_id)
    if data is None:
        return None
    path = save_dialogue(data, export_dir)
    with open(path, "rb") as handle:
        payload = handle.read()
    document = BufferedInputFile(payload, filename=os.path.basename(path))
    kwargs = {"message_thread_id": thread_id} if thread_id else {}
    await safe(bot.send_document(
        chat_id, document, caption=ticket_number(ticket), **kwargs
    ), where="TXT-экспорт")
    return path
