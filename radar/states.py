"""Состояния FSM."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    suggest_source = State()
    add_channel = State()
    add_rss = State()
    weather_time = State()
    weather_interval = State()
    manual_address = State()
