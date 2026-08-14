#!/usr/bin/env python3
"""Точка входа системы «Радар»."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os

from radar import config

# Логи и проверка конфигурации выполняются до импорта aiogram-слоя:
# без валидного BOT_TOKEN экземпляр Bot создать нельзя.
log = config.setup_logging()
config.validate()

from radar import ai, features, handlers, logs as logstore, monitor, roles, storage  # noqa: E402
from radar.db import engine as db_engine  # noqa: E402
from radar.db import importer, repo  # noqa: E402
from radar.middlewares import AccessMiddleware  # noqa: E402
from radar.tg import bot, dp, send_html  # noqa: E402

# История изменений: список версий, а не склеенный текст. Раньше блоки
# «Из прошлых версий» дописывались друг к другу и дублировались, а название
# базы было вписано жёстко — при переходе на SQLite оно стало враньём.
RELEASES: list[tuple[str, list[str]]] = [
    ("4.2.1", [
        "🎬 <b>Загрузка видео по ссылке</b> с выбором качества — YouTube, VK, "
        "RuTube, OK, Дзен и другие площадки. Включается флагом media_download.",
        "🔌 <b>Адаптер мессенджера MAX</b> — реализован, но пока не проверен "
        "на живом сервере: включайте только для испытаний.",
    ]),
    ("4.1.1", [
        "🆘 <b>Кнопка SOS</b> — отправка геопозиции экстренному контакту.",
        "🌤 <b>Погода для пользователей от администрации</b> — режим и частоту "
        "можно задать за пользователя.",
        "🟠 <b>Одноклассники как источник</b> — через официальный API.",
        "🛡 Больше проверок отказоустойчивости.",
    ]),
    ("4.0.8", [
        "🩺 <b>Диагностика перед запуском</b>: установщик проверяет систему "
        "и не стартует бота при ошибке.",
        "↩️ <b>Откат на предыдущую версию</b> из снимка, если обновление не удалось.",
        "📋 <b>Журналы в боте</b>: /logs, /logtail, /logclear у суперадминистратора.",
        "🔍 <b>Проверка источников</b> — кнопка в панели модератора и /checksources.",
    ]),
    ("4.0", [
        "🗄 <b>Настоящая база данных</b> вместо файла. Данные перенесены автоматически.",
        "🕘 <b>История событий</b> — видно, что приходило по каждому адресу.",
        "⚙️ <b>Управление возможностями</b> в боте: /features у суперадминистратора, "
        "без обновления версии.",
        "🔌 <b>Готовность к мессенджеру MAX</b> — единое ядро для двух платформ.",
        "🐙 Партнёрский проект переименован в <b>HydraSite</b>, команда /partner.",
    ]),
    ("3.3", [
        "✅ <b>Отбой опасности</b> приходит отдельным сообщением с другим сигналом.",
        "📍 <b>Администрация добавляет локации</b> пользователям — адресом или геопозицией.",
        "🔗 Новости из лент СМИ снабжаются ссылкой на источник.",
        "🌍 Новые города: Москва, Санкт-Петербург, Казань, Самара.",
        "📦 Источники выгружаются и загружаются файлом.",
        "📵 <b>Белые списки</b> — предупреждение выдаётся автоматически "
        "вместе с оповещением о БПЛА.",
    ]),
    ("3.0", [
        "🛸 <b>Военные угрозы</b> определяются на весь город и приходят одним "
        "сообщением со списком совпавших локаций.",
        "🛠 <b>ЖКХ</b> ищется адресно — по улице и дому, отдельным сообщением.",
        "📍 Локаций сколько угодно; ближе 1 км — объединяются в одну сводку.",
        "🌤 Погода — по каждой группе локаций отдельно.",
        "🧠 ИИ-ассистент в диалоге — начиная с роли «Модератор».",
        "👥 Роли: суперадминистратор → администратор → модератор → пользователь.",
    ]),
]


def build_changelog(limit: int = 2) -> str:
    """Собирает сообщение об обновлении.

    Показываются последние `limit` выпусков: полный список за всю историю
    в одном сообщении не читается и упирается в ограничение Telegram.
    """
    backend = "PostgreSQL" if not config.is_sqlite() else "SQLite"
    parts = [
        f"🚀 <b>Система «Радар» v{config.VERSION}</b>",
        f"<i>База данных: {backend}</i>",
        "",
    ]
    for index, (version, items) in enumerate(RELEASES[:limit]):
        if index:
            parts.append("")
            parts.append(f"<b>Ранее, в версии {version}:</b>")
        parts.extend(items)

    if len(RELEASES) > limit:
        parts.append("")
        parts.append("<i>Полная история изменений — в репозитории проекта.</i>")
    return "\n".join(parts)


async def announce() -> None:
    """Рассылает changelog один раз на версию, а не при каждом рестарте."""
    marker = await storage.meta_get("announced_version") or {}
    if marker.get("value") == config.VERSION:
        return
    await storage.meta_set("announced_version", {"value": config.VERSION})
    for uid, user in list(storage.users().items()):
        if roles.is_moderator(user.get("role")):
            await send_html(uid, build_changelog())
            await asyncio.sleep(0.2)


async def setup_commands() -> None:
    """Список команд в синей кнопке меню Telegram."""
    from aiogram.types import BotCommand

    commands = [
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="partner", description="Партнёрский проект"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="id", description="Мой ID и роль"),
        BotCommand(command="cancel", description="Отменить ввод"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception:  # noqa: BLE001
        log.warning("Не удалось установить меню команд", exc_info=True)


async def prepare_database() -> None:
    """Готовит базу: ждёт готовности, создаёт схему, переносит старые данные."""
    await db_engine.wait_ready()

    log.info("Проверяю схему базы")
    created, tables, repaired = await db_engine.ensure_schema()
    await db_engine.stamp_alembic()
    if repaired:
        log.warning("Схема была несовместима и пересоздана (%d таблиц)", tables)
    elif created:
        log.info("Схема базы создана (%d таблиц)", tables)
    else:
        log.info("Схема базы актуальна (%d таблиц)", tables)
    if await importer.is_empty():
        log.info("База пуста — переношу данные прежней версии")
        counters = await importer.run()
        log.info(
            "Перенос завершён: пользователей %d, локаций %d",
            counters.get("users", 0), counters.get("locations", 0),
        )
    await storage.load()
    features.apply(await repo.load_features())
    active = sum(1 for flag in features.FLAGS if features.enabled(flag.key))
    log.info("Возможностей включено: %d из %d", active, len(features.FLAGS))
    logstore.ensure_directory()
    stale_logs = logstore.purge_old()
    if stale_logs:
        log.info("Удалено устаревших журналов: %d", stale_logs)

    removed = await repo.purge_old_events()
    if removed:
        log.info("Удалено устаревших событий: %d", removed)


async def main() -> None:
    await prepare_database()

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
        await db_engine.dispose()
        log.info("Остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except db_engine.AuthenticationError:
        # Причина уже подробно объяснена в логе — трассировка тут лишний шум.
        raise SystemExit(1)
    except Exception:  # noqa: BLE001
        # Без этого контейнер уходит в бесконечный цикл рестартов, а причина
        # теряется среди одинаковых трейсбеков.
        log.critical("Критический сбой при запуске", exc_info=True)
        log.critical(
            "Проверьте .env (DB_PASSWORD без символа $), доступность базы "
            "и логи radar_db: docker logs --tail 40 radar_db"
        )
        raise SystemExit(1)
