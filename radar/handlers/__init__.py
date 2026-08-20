"""Роутеры обработчиков. Порядок подключения важен: ассистент — последним."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import Dispatcher

from . import (
    assistant,
    common,
    digest,
    features,
    history,
    language,
    locations,
    logs,
    media,
    network,
    partners,
    perf,
    settings,
    shortlink,
    settings_admin,
    sos,
    sources,
    users,
)

def setup(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(locations.router)
    dp.include_router(settings.router)
    dp.include_router(sources.router)
    dp.include_router(users.router)
    dp.include_router(features.router)
    dp.include_router(settings_admin.router)
    dp.include_router(network.router)
    dp.include_router(logs.router)
    dp.include_router(language.router)
    dp.include_router(history.router)
    dp.include_router(partners.router)
    dp.include_router(perf.router)
    dp.include_router(shortlink.router)
    dp.include_router(digest.router)
    dp.include_router(sos.router)
    # Ссылки перехватываем до свободного диалога с моделью
    dp.include_router(media.router)
    # Ассистент перехватывает любой оставшийся текст — только в самом конце.
    dp.include_router(assistant.router)


__all__ = ["setup"]
