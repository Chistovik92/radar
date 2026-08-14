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
    features,
    locations,
    logs,
    settings,
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
    dp.include_router(logs.router)
    dp.include_router(sos.router)
    # Ассистент перехватывает любой оставшийся текст — только в самом конце.
    dp.include_router(assistant.router)


__all__ = ["setup"]
