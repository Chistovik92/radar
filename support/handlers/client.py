"""Личный чат: создание, переписка, вложения, закрытие и оценка."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..core.attachments import describe, from_message
from ..core.classify import KnowledgeBase, classify
from ..core.config import Settings
from ..db.models import Ticket
from ..db.repo import SupportRepository, TicketClosed, ticket_number
from ..i18n import t
from .common import (
    deliver_export, new_ticket_keyboard, notify_message, rating_keyboard, safe, ticket_line,
)

router = Router(name="support_client")


async def _user(repo: SupportRepository, message: Message, config: Settings):
    return await repo.get_or_create_user(
        message.from_user.id, message.from_user.username or "",
        (message.from_user.language_code or "ru")[:2], config.admin_id,
    )


@router.message(F.chat.type == "private", CommandStart())
async def start(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _user(repo, message, config)
    await message.answer(t("start", user.lang), reply_markup=new_ticket_keyboard())


async def create(message: Message, repo: SupportRepository, config: Settings, actor=None) -> Ticket:
    if actor is None:
        user = await _user(repo, message, config)
    else:
        user = await repo.get_or_create_user(
            actor.id, actor.username or "", (actor.language_code or "ru")[:2], config.admin_id,
        )
    ticket = await repo.create_ticket(user.external_id)
    await message.answer(t("created", user.lang, number=ticket_number(ticket)))
    return ticket


@router.message(F.chat.type == "private", Command("support"))
async def support(message: Message, repo: SupportRepository, config: Settings) -> None:
    await create(message, repo, config)


@router.callback_query(F.data == "support:new")
async def support_callback(query: CallbackQuery, repo: SupportRepository, config: Settings) -> None:
    await query.answer()
    if query.message and query.message.chat.type == "private":
        await create(query.message, repo, config, actor=query.from_user)


@router.message(F.chat.type == "private", Command("tickets"))
async def tickets(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _user(repo, message, config)
    rows = await repo.list_tickets(user.external_id, include_closed=True)
    await message.answer("\n".join(ticket_line(row) for row in rows) if rows else "Тикетов пока нет.")


@router.message(F.chat.type == "private", Command("open"))
async def open_ticket(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _user(repo, message, config)
    parts = (message.text or "").split(maxsplit=1)
    ticket = await repo.set_active(parts[1], user.external_id) if len(parts) == 2 else None
    if ticket is None:
        await message.answer(t("not_found", user.lang))
        return
    data = await repo.export_data(ticket.id, user.external_id)
    history = "\n".join(
        html.escape(item["body"])
        for item in (data or {}).get("messages", [])[-20:] if item["body"]
    )
    await message.answer(ticket_line(ticket) + (("\n\n" + history) if history else ""))


@router.message(F.chat.type == "private", Command("close"))
async def close_ticket(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _user(repo, message, config)
    parts = (message.text or "").split(maxsplit=1)
    ticket = await repo.active_ticket(user.external_id) if len(parts) == 1 else await repo.get_ticket(parts[1], user.external_id)
    if ticket is None:
        await message.answer(t("not_found", user.lang))
        return
    ticket = await repo.close_ticket(ticket.id, user.external_id)
    await message.answer(t("closed", user.lang, number=ticket_number(ticket)), reply_markup=rating_keyboard(ticket))
    await deliver_export(message.bot, repo, ticket, user.external_id, config.export_dir, message.chat.id)
    data = await repo.export_data(ticket.id, user.external_id)
    author_id = (data or {}).get("author", {}).get("external_id")
    if author_id and author_id != user.external_id:
        await safe(message.bot.send_message(
            author_id, t("closed", "ru", number=ticket_number(ticket)),
            reply_markup=rating_keyboard(ticket),
        ), where="уведомление автора о закрытии")
        await deliver_export(message.bot, repo, ticket, user.external_id, config.export_dir, author_id)
    if ticket.group_id and ticket.thread_id:
        await safe(message.bot.send_message(
            ticket.group_id, f"Обращение {ticket_number(ticket)} закрыто.",
            message_thread_id=ticket.thread_id,
        ), where="закрытие топика")


@router.callback_query(F.data.startswith("support:rate:"))
async def rate(query: CallbackQuery, repo: SupportRepository) -> None:
    try:
        _, _, raw_id, raw_rating = (query.data or "").split(":")
        reference, rating = int(raw_id), int(raw_rating)
    except (ValueError, TypeError):
        await query.answer("Некорректная оценка", show_alert=True)
        return
    accepted = await repo.rate_ticket(reference, query.from_user.id, rating)
    await query.answer("Спасибо за оценку!" if accepted else "Оценить может автор закрытого тикета", show_alert=not accepted)
    if accepted and query.message:
        await safe(query.message.edit_reply_markup(reply_markup=None))


@router.message(F.chat.type == "private")
async def dialogue(message: Message, repo: SupportRepository, config: Settings,
                   knowledge: KnowledgeBase) -> None:
    user = await _user(repo, message, config)
    ticket = await repo.active_ticket(user.external_id)
    if ticket is None or ticket.status == "closed":
        text = message.text or message.caption or ""
        answer = await knowledge.answer(text, await repo.faq_entries())
        if answer:
            await message.answer(
                html.escape(answer) + "\n\nЕсли не помогло, создайте тикет.",
                reply_markup=new_ticket_keyboard(),
            )
        else:
            await message.answer("Создайте обращение командой /support, затем напишите сообщение.")
        return
    attachment = from_message(message)
    text = describe(attachment) if attachment else (message.text or "").strip()
    if not text:
        return
    try:
        result = await repo.add_message(
            ticket.id, user.external_id, text,
            "attachment" if attachment else "text", attachment,
        )
    except TicketClosed:
        await message.answer("Тикет уже закрыт. Создайте новый: /support")
        return
    if result is None:
        await message.answer(t("not_found", user.lang))
        return
    ticket, stored = result
    await notify_message(message.bot, repo, ticket, user, stored, config.group_id)
