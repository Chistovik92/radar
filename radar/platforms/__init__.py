"""Адаптеры мессенджеров: единый формат событий поверх разных API."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from .base import (
    Button,
    EventKind,
    InboundEvent,
    Keyboard,
    OutboundMessage,
    Transport,
)

from .max import MaxTransport

__all__ = [
    "Button", "EventKind", "InboundEvent", "Keyboard", "OutboundMessage",
    "Transport", "MaxTransport",
]
