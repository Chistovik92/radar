#!/usr/bin/env python3
"""Точка входа системы «Радар»."""

from __future__ import annotations

import asyncio
import os

from radar import config

# Логи и проверка конфигурации выполняются до импорта aiogram-слоя:
# без валидного BOT_TOKEN экземпляр Bot создать нельзя.
log = config.setup_logging()
config.validate()

from radar import ai, handlers, monitor, roles, storage  # noqa: E402
from radar.middlewares import AccessMiddleware  # noqa: E402
from radar.tg import bot, dp, send_html  # noqa: E402

CHANGELOG = (
    f"🚀 <b>Система «Радар» v{config.VERSION}</b>\n\n"
    "✅ <b>Отбой опасности</b> приходит отдельным сообщением с другим сигналом, "
    "а не как новая тревога.\n"
    "📍 <b>Администрация может добавлять локации</b> пользователям — по адресу "
    "текстом или геопозицией.\n"
    "🔗 <b>Новости из лент СМИ</b> снабжаются ссылкой на источник.\n"
    "🌍 <b>Новые города</b>: Москва, Санкт-Петербург, Казань, Самара.\n"
    "☰ <b>Кнопки «Меню» и «HydraVPN»</b> закреплены под полем ввода.\n\n"
    "<i>Из прошлых версий:</i>\n"
    "<b>Полностью переработанная версия:</b>\n"
    "🛸 <b>Военные угрозы</b> (БПЛА, ракетная опасность) определяются на весь город "
    "и приходят одним сообщением со списком совпавших локаций.\n"
    "🛠 <b>ЖКХ</b> (вода, свет, газ, отопление, аварии) ищется адресно — по улице и дому, "
    "отдельным сообщением.\n"
    "📍 <b>Локаций сколько угодно</b>; находящиеся ближе 1 км объединяются в одну сводку.\n"
    "🌤 <b>Погода</b> — по каждой группе локаций отдельно.\n"
    "🌐 <b>Источники</b>: каналы служб ЖКХ, МЧС, администраций города, района, области "
    "плюс RSS-ленты СМИ.\n"
    "🧠 <b>ИИ-ассистент</b> в диалоге — начиная с роли «Модератор».\n"
    "👥 <b>Роли</b>: суперадминистратор назначает администраторов, администратор — "
    "модераторов; правка локаций и оповещений — с модератора, удаление — с администратора.\n"
    "📉 <b>Экономия квоты Gemini</b>: предфильтр, пакетный разбор и резерв запросов "
    "под ассистента. Расход — командой /quota.\n"
    "🔄 <b>Модель выбирается автоматически</b> из доступных ключу: при отключении "
    "одной версии бот сам переходит на следующую. Список — командой /models.\n"
    "📦 <b>Источники выгружаются и загружаются файлом</b> — кнопки в панели модератора.\n"
    "🌤 <b>Погода переработана</b>: почасовая таблица, прогноз на три дня, восход и закат.\n"
    "📵 <b>Белые списки</b> больше не ищутся в новостях — предупреждение выдаётся "
    "автоматически вместе с оповещением о БПЛА или ракетной опасности."
)


async def announce() -> None:
    """Рассылает changelog один раз на версию, а не при каждом рестарте."""
    meta = storage.meta()
    if meta.get("announced_version") == config.VERSION:
        return
    meta["announced_version"] = config.VERSION
    await storage.save()
    for uid, user in list(storage.users().items()):
        if roles.is_moderator(user.get("role")):
            await send_html(uid, CHANGELOG)
            await asyncio.sleep(0.2)


async def setup_commands() -> None:
    """Список команд в синей кнопке меню Telegram."""
    from aiogram.types import BotCommand

    commands = [
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="vpn", description="HydraVPN — второй проект"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="id", description="Мой ID и роль"),
        BotCommand(command="cancel", description="Отменить ввод"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception:  # noqa: BLE001
        log.warning("Не удалось установить меню команд", exc_info=True)


async def main() -> None:
    await storage.load()

    dp.message.outer_middleware(AccessMiddleware())
    dp.callback_query.outer_middleware(AccessMiddleware())
    handlers.setup(dp)

    log.info(
        "Запуск «Радар» v%s | ИИ: %s | TZ: %s | опрос каждые %d с",
        config.VERSION,
        config.GEMINI_MODEL if config.AI_ENABLED else "выключен (эвристика)",
        os.getenv("TZ", "system"),
        config.POLL_INTERVAL,
    )

    if ai.ENABLED:
        await ai.discover_models()
        log.info(
            "Модели: ассистент «%s», анализ «%s»",
            ai.current_model(ai.ASSISTANT), ai.current_model(ai.ANALYSIS),
        )

    await setup_commands()

    background = asyncio.create_task(monitor.run(), name="monitor")
    asyncio.create_task(announce(), name="announce")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        background.cancel()
        try:
            await background
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        log.info("Остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
