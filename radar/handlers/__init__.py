"""Роутеры обработчиков. Порядок подключения важен: ассистент — последним."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import Dispatcher, F

from . import (
    assistant,
    chats,
    common,
    digest,
    features,
    group,
    history,
    language,
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
)

# Порядок прежний и важный: ассистент перехватывает любой оставшийся
# текст, поэтому он последний, а ссылки — прямо перед ним.
PRIVATE_ROUTERS = (
    common, locations, settings, sources, users, features, settings_admin,
    network, rustdesk, logs, language, history, partners, perf, shortlink,
    linkcheck, music, digest, sos, chats,
    # Подписка держит обработчик кодов: он ловит только то, что
    # похоже на код, и пропускает остальное дальше по цепочке.
    subscription,
    # Ссылки перехватываем до свободного диалога с моделью
    media,
    # Ассистент перехватывает любой оставшийся текст — только в конце.
    assistant,
)


def setup(dp: Dispatcher) -> None:
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
