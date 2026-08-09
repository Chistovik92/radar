"""Роутеры обработчиков. Порядок подключения важен: ассистент — последним."""

from __future__ import annotations

from aiogram import Dispatcher

from . import assistant, common, locations, settings, sources, users


def setup(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(locations.router)
    dp.include_router(settings.router)
    dp.include_router(sources.router)
    dp.include_router(users.router)
    # Ассистент перехватывает любой оставшийся текст — только в самом конце.
    dp.include_router(assistant.router)


__all__ = ["setup"]
