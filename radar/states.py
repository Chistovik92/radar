"""Состояния FSM."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
    suggest_source = State()
    add_channel = State()
    add_rss = State()
    weather_time = State()
    weather_interval = State()
    manual_address = State()
    admin_add_location = State()   # ввод адреса для чужого пользователя
    admin_weather_time = State()   # точное время погоды для чужого пользователя
    admin_weather_interval = State()
    sos_contact = State()          # добавление доверенного контакта
    sos_location = State()         # ожидание геопозиции для сигнала
    secret_value = State()         # ввод ключа доступа суперадминистратором
    proxy_key = State()            # ключ или подписка для выхода в сеть
    digest_time = State()          # время доставки новостной подборки
    quiet_hours = State()          # интервал тихих часов
