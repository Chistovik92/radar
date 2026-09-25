"""Роутеры обработчиков. Порядок подключения важен: ассистент — последним."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from aiogram import Dispatcher, F
from aiogram.types import CallbackQuery, ErrorEvent, Message

from . import (
    assistant,
    chats,
    common,
    digest,
    features,
    group,
    history,
    language,
    linking,
    linkcheck,
    locations,
    logs,
    media,
    music,
    network,
    partners,
    perf,
    rustdesk,
    settings,
    shortlink,
    settings_admin,
    sos,
    sources,
    subscription,
    users,
    vpn,
)

# Порядок прежний и важный: ассистент перехватывает любой оставшийся
# текст, поэтому он последний, а ссылки — прямо перед ним.
PRIVATE_ROUTERS = (
    common, locations, settings, sources, users, features, settings_admin,
    network, rustdesk, logs, language, history, partners, perf, shortlink,
    linkcheck, music, digest, sos, chats, vpn, linking,
    # Подписка держит обработчик кодов: он ловит только то, что
    # похоже на код, и пропускает остальное дальше по цепочке.
    subscription,
    # Ссылки перехватываем до свободного диалога с моделью
    media,
    # Ассистент перехватывает любой оставшийся текст — только в конце.
    assistant,
)


log = logging.getLogger("radar.handlers")


async def on_error(event: ErrorEvent) -> bool:
    """Последний рубеж: ни одно нажатие не остаётся без ответа (с 4.9.8.14).

    Обработчика ошибок у бота не было вовсе. Упавший раздел — например,
    из-за недоступной на секунду базы — оставлял человека перед кнопкой,
    которая просто ничего не делает: ни ответа, ни объяснения. Оставался
    только журнал, и то у администратора.

    Возвращаем True: исключение разобрано, и aiogram не должен ронять
    из-за него опрос обновлений.
    """
    update = event.update
    log.exception(
        "Необработанная ошибка в обработчике", exc_info=event.exception
    )

    note = (
        "⚠️ Не получилось выполнить действие. Попробуйте ещё раз — "
        "если повторится, сообщите администратору."
    )
    try:
        callback = getattr(update, "callback_query", None)
        if isinstance(callback, CallbackQuery):
            await callback.answer(note, show_alert=True)
            return True
        message = getattr(update, "message", None)
        if isinstance(message, Message):
            await message.answer(note)
    except Exception:  # noqa: BLE001
        # Извинение — не то, ради чего стоит поднимать вторую ошибку.
        log.debug("Сообщение об ошибке не доставлено")
    return True


def setup(dp: Dispatcher) -> None:
    dp.errors.register(on_error)

    # Модерация — первой и только для групп: её сообщения не должны
    # доходить до разделов, рассчитанных на личную переписку.
    group.router.message.filter(F.chat.type.in_({"group", "supergroup"}))
    dp.include_router(group.router)

    # Всё остальное — только личный чат. Фильтр вешается здесь, одним
    # местом, а не двадцатью декораторами: иначе новый раздел рано или
    # поздно окажется без него и начнёт отвечать в группе. Ассистент
    # ловит ЛЮБОЙ текст, и цена такой утечки — ответы ИИ на чужой
    # разговор и сожжённая квота.
    for module in PRIVATE_ROUTERS:
        module.router.message.filter(F.chat.type == "private")
        dp.include_router(module.router)


__all__ = ["setup"]
