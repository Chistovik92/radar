"""Команды операторов: очередь, ответы, SLA, экспорт, статистика и FAQ."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from ..core import roles
from ..core.attachments import describe, from_message
from ..core.classify import KnowledgeBase
from ..core.config import Settings
from ..db.repo import SupportRepository, TicketClosed, ticket_number
from .common import deliver_export, notify_message, safe, ticket_line

router = Router(name="support_operator")


async def _moderator(message: Message, repo: SupportRepository, config: Settings):
    user = await repo.get_or_create_user(
        message.from_user.id, message.from_user.username or "", superadmin_id=config.admin_id
    )
    if not roles.is_moderator(user.role):
        await message.answer("Недостаточно прав.")
        return None
    return user


def _argument(message: Message) -> str:
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


@router.message(F.chat.type == "private", Command("queue"))
async def queue(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _moderator(message, repo, config)
    if user:
        rows = await repo.list_tickets(user.external_id)
        await message.answer("\n".join(ticket_line(row) for row in rows) if rows else "Очередь пуста.")


@router.message(F.chat.type == "private", Command("reply"))
async def reply(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _moderator(message, repo, config)
    if not user:
        return
    argument = _argument(message)
    reference, _, text = argument.partition(" ")
    if not reference or not text.strip():
        await message.answer("Формат: /reply #2026-1 ответ")
        return
    try:
        result = await repo.add_message(reference, user.external_id, text.strip())
    except TicketClosed:
        result = None
    if result is None:
        await message.answer("Тикет не найден или закрыт.")
        return
    ticket, stored = result
    await notify_message(message.bot, repo, ticket, user, stored, config.group_id)
    await message.answer(f"Ответ добавлен в {ticket_number(ticket)}.")


@router.message(F.chat.type == "private", Command("draft"))
async def draft(message: Message, repo: SupportRepository, config: Settings,
                knowledge: KnowledgeBase) -> None:
    user = await _moderator(message, repo, config)
    if not user:
        return
    if knowledge.ai is None or not knowledge.ai.enabled:
        await message.answer("Gemini выключен: задайте SUPPORT_AI=1 и GEMINI_API_KEY.")
        return
    data = await repo.export_data(_argument(message), user.external_id)
    questions = [row["body"] for row in (data or {}).get("messages", [])
                 if row["kind"] != "system" and row.get("sender", {})
                 and row["sender"].get("id") == (data or {}).get("ticket", {}).get("author_id")]
    answer = await knowledge.ai.ask(questions[-1] if questions else "") if questions else None
    await message.answer(
        "Черновик:\n" + html.escape(answer) if answer
        else "Gemini не дал ответ; используйте обычный /reply."
    )


@router.message(F.chat.type == "private", Command("priority"))
async def priority(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _moderator(message, repo, config)
    if not user:
        return
    reference, _, value = _argument(message).partition(" ")
    ticket = await repo.set_priority(reference, user.external_id, value)
    await message.answer(f"Приоритет {ticket_number(ticket)}: {ticket.priority}." if ticket else "Формат: /priority #2026-1 low|normal|high")


@router.message(F.chat.type == "private", Command("export"))
async def export(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _moderator(message, repo, config)
    if not user:
        return
    ticket = await repo.get_ticket(_argument(message), user.external_id)
    if ticket is None:
        await message.answer("Тикет не найден.")
        return
    path = await deliver_export(message.bot, repo, ticket, user.external_id, config.export_dir, message.chat.id)
    if path is None:
        await message.answer("Не удалось сформировать экспорт.")


@router.message(F.chat.type == "private", Command("stats"))
async def stats(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _moderator(message, repo, config)
    if not user:
        return
    report = await repo.statistics(user.external_id)
    satisfaction = f"{report['satisfaction']}%" if report["satisfaction"] is not None else "нет оценок"
    lines = [
        f"Тикетов: {report['total']}",
        f"Статусы: {report['statuses']}",
        f"Оценки: 👍 {report['positive']}, 👎 {report['negative']} ({satisfaction})",
        f"SLA: вовремя {report['sla_on_time']}/{report['sla_responded']}, просрочено открытых {report['sla_overdue_open']}",
        f"По операторам: {html.escape(str(report['by_operator']))}",
        f"По категориям: {html.escape(str(report['by_category']))}",
    ]
    await message.answer("\n".join(lines))


@router.message(F.chat.type == "private", Command("role"))
async def role(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await repo.get_or_create_user(message.from_user.id, superadmin_id=config.admin_id)
    reference, _, value = _argument(message).partition(" ")
    try:
        target = int(reference)
    except ValueError:
        target = 0
    changed = await repo.set_role(user.external_id, target, value)
    await message.answer("Роль изменена." if changed else "Нельзя назначить эту роль. /role ID moderator")


@router.message(F.chat.type == "private", Command("faq_add"))
async def faq_add(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _moderator(message, repo, config)
    if not user:
        return
    keyword, separator, answer = _argument(message).partition("|")
    changed = bool(separator) and await repo.set_faq(user.external_id, keyword, answer)
    await message.answer("FAQ сохранён." if changed else "Формат: /faq_add ключевое слово | ответ")


@router.message(F.chat.type == "private", Command("faq_del"))
async def faq_del(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await _moderator(message, repo, config)
    if user:
        changed = await repo.delete_faq(user.external_id, _argument(message))
        await message.answer("Удалено." if changed else "Запись не найдена или недостаточно прав.")


@router.message(F.chat.type == "private", Command("delete_ticket"))
async def delete_ticket(message: Message, repo: SupportRepository, config: Settings) -> None:
    user = await repo.get_or_create_user(message.from_user.id, superadmin_id=config.admin_id)
    changed = await repo.delete_ticket(_argument(message), user.external_id)
    await message.answer("Тикет удалён; номер не будет переиспользован." if changed else "Нужна роль admin и существующий номер.")
