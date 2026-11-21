"""Форум-группа: одна тема строго соответствует одному тикету."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from ..core.attachments import describe, from_message
from ..core.classify import KnowledgeBase
from ..core.config import Settings
from ..db.repo import SupportRepository, TicketClosed, ticket_number
from .common import deliver_export, notify_message, rating_keyboard, safe

router = Router(name="support_group")


@router.message(F.chat.type.in_({"group", "supergroup"}), Command("close"))
async def close_topic(message: Message, repo: SupportRepository, config: Settings) -> None:
    if message.chat.id != config.group_id or not message.message_thread_id:
        return
    user = await repo.get_or_create_user(message.from_user.id, superadmin_id=config.admin_id)
    ticket = await repo.by_topic(message.chat.id, message.message_thread_id, user.external_id)
    if ticket is None:
        await message.answer("Тикет не найден.")
        return
    ticket = await repo.close_ticket(ticket.id, user.external_id)
    await safe(message.answer(
        f"Обращение {ticket_number(ticket)} закрыто.", message_thread_id=message.message_thread_id,
    ), where="подтверждение закрытия топика")
    await deliver_export(
        message.bot, repo, ticket, user.external_id, config.export_dir,
        message.chat.id, message.message_thread_id,
    )
    data = await repo.export_data(ticket.id, user.external_id)
    author_id = (data or {}).get("author", {}).get("external_id")
    if author_id:
        await safe(message.bot.send_message(
            author_id, f"Обращение {ticket_number(ticket)} закрыто. Оцените ответ:",
            reply_markup=rating_keyboard(ticket),
        ), where="оценка после закрытия топика")
        await deliver_export(
            message.bot, repo, ticket, user.external_id, config.export_dir, author_id,
        )


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def topic_dialogue(message: Message, repo: SupportRepository, config: Settings,
                         knowledge: KnowledgeBase) -> None:
    if not config.group_id or message.chat.id != config.group_id or not message.from_user:
        return
    attachment = from_message(message)
    text = describe(attachment) if attachment else (message.text or message.caption or "").strip()
    if not text or text.startswith("/"):
        return
    user = await repo.get_or_create_user(
        message.from_user.id, message.from_user.username or "",
        (message.from_user.language_code or "ru")[:2], config.admin_id,
    )
    thread_id = message.message_thread_id
    ticket = await repo.by_topic(message.chat.id, thread_id, user.external_id) if thread_id else None
    if ticket is None:
        # Существующий чужой топик не превращается в новый тикет и не раскрывается.
        if thread_id:
            existing = await repo.by_topic_any(message.chat.id, thread_id)
            if existing is not None:
                await message.answer("Тикет не найден.", message_thread_id=thread_id)
                return
        category = await knowledge.category(text)
        ticket = await repo.create_ticket(
            user.external_id, subject=text, category=category,
            group_id=config.group_id, thread_id=thread_id,
        )
        if not thread_id:
            topic = await message.bot.create_forum_topic(
                chat_id=config.group_id, name=f"{ticket_number(ticket)} Поддержка",
            )
            thread_id = topic.message_thread_id
            ticket = await repo.attach_topic(ticket.id, config.group_id, thread_id)
        await message.bot.send_message(
            config.group_id, f"Обращение {ticket_number(ticket)} создано.",
            message_thread_id=thread_id,
        )
    try:
        result = await repo.add_message(
            ticket.id, user.external_id, text,
            "attachment" if attachment else "text", attachment,
        )
    except TicketClosed:
        await message.answer("Тикет закрыт.", message_thread_id=thread_id)
        return
    if result is not None:
        ticket, stored = result
        await notify_message(
            message.bot, repo, ticket, user, stored, config.group_id, mirror_group=False,
        )
