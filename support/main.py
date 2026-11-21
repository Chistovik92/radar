"""Точка входа отдельного aiogram-бота поддержки."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent

from .core.classify import GeminiAssistant, KnowledgeBase
from .core.config import Settings
from .db.engine import Database
from .db.repo import SupportRepository, ticket_number
from .handlers import client, group, operator
from .handlers.common import safe

log = logging.getLogger("support")


async def sla_worker(repo: SupportRepository, bot: Bot, config: Settings) -> None:
    while True:
        try:
            overdue = await repo.escalate_overdue()
            if overdue:
                moderators = await repo.moderators()
                for ticket in overdue:
                    text = f"⚠️ SLA {ticket_number(ticket)} просрочен; приоритет high."
                    for moderator in moderators:
                        await safe(bot.send_message(moderator.external_id, text), where="SLA-уведомление")
                    if ticket.group_id and ticket.thread_id:
                        await safe(bot.send_message(
                            ticket.group_id, text, message_thread_id=ticket.thread_id
                        ), where="SLA в топик")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — следующий цикл должен состояться
            log.error("Ошибка фоновой проверки SLA: %s", exc)
        await asyncio.sleep(config.sla_check_seconds)


async def run() -> None:
    config = Settings.from_env()
    config.validate()
    database = Database(config.sqlalchemy_url(), config.db_echo)
    await database.create_schema()
    repo = SupportRepository(database, config.sla_minutes)
    await repo.get_or_create_user(config.admin_id, superadmin_id=config.admin_id)
    ai = GeminiAssistant(config.ai_enabled, config.gemini_api_key, config.gemini_model)
    knowledge = KnowledgeBase(ai)
    bot = Bot(config.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher(repo=repo, config=config, knowledge=knowledge)
    dispatcher.include_router(group.router)
    dispatcher.include_router(operator.router)
    dispatcher.include_router(client.router)

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> None:
        log.error("Ошибка обработчика", exc_info=event.exception)
        update = event.update
        message = getattr(update, "message", None) or getattr(update, "callback_query", None)
        if message and getattr(message, "message", None):
            message = message.message
        if message:
            await safe(message.answer("Не удалось выполнить действие. Попробуйте позже."))

    worker = asyncio.create_task(sla_worker(repo, bot, config))
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await database.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
