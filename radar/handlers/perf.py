"""Отчёт о том, куда уходит время цикла. Только суперадминистратору.

Нужен, чтобы оптимизировать по замерам, а не по догадке. На слабом
одноплатнике порядок стадий обычно один и тот же — сеть, потом ИИ, —
но проверять это следует на конкретной машине, а не на общих словах.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import config, profiling, roles
from ..tg import back_kb, safe_edit

router = Router(name="perf")

TITLES = {
    "sources": "Сбор источников",
    "vk": "ВКонтакте",
    "ai": "Разбор ИИ",
    "dispatch": "Рассылка оповещений",
    "digest": "Рассылка подборок",
    "save": "Запись в базу",
}


def _duration(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60)} мин {seconds % 60:.0f} с"
    if seconds >= 1:
        return f"{seconds:.1f} с"
    return f"{seconds * 1000:.0f} мс"


def _uptime(seconds: float) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    if hours >= 24:
        return f"{hours // 24} сут {hours % 24} ч"
    return f"{hours} ч {remainder // 60} мин"


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="perf:show")],
        [InlineKeyboardButton(text="🧹 Сбросить счётчики", callback_data="perf:reset")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
    ])


def _report() -> str:
    stages = profiling.snapshot()
    lines = ["⏱ <b>Время цикла по стадиям</b>", ""]

    if not stages:
        lines.append("Замеров пока нет — цикл ещё не отработал ни разу.")
    else:
        # Доля считается от суммы стадий, а не от интервала опроса: между
        # проходами бот спит, и включать сон в проценты бессмысленно.
        total = sum(stage.total for stage in stages.values()) or 1.0
        for key, stage in stages.items():
            title = TITLES.get(key, key)
            share = stage.total / total * 100
            lines.append(
                f"<b>{title}</b> — {share:.0f}%\n"
                f"  среднее {_duration(stage.average)}"
                f" · худшее {_duration(stage.worst)}"
                f" · последнее {_duration(stage.last)}"
                f" · вызовов {stage.calls}"
            )
        lines.append("")
        lines.append(f"Суммарно в стадиях: <b>{_duration(total)}</b>")

    memory = profiling.memory_mb()
    cores = profiling.cpu_count()
    one, five, fifteen = profiling.load_average()

    lines.append("")
    lines.append("💻 <b>Ресурсы</b>")
    if memory:
        lines.append(f"Память процесса: <b>{memory:.0f} МиБ</b>")
    lines.append(f"Процессорное время: <b>{_duration(profiling.cpu_seconds())}</b>")
    if one or five or fifteen:
        # Нагрузка выше числа ядер означает очередь готовых задач —
        # на четырёхъядерном RK3318 тревожен порог около 4.
        lines.append(
            f"Средняя нагрузка: <b>{one:.2f}</b> / {five:.2f} / {fifteen:.2f}"
            f" (ядер: {cores})"
        )
    lines.append(f"Наблюдение идёт: <b>{_uptime(profiling.uptime())}</b>")
    lines.append(f"Интервал опроса: <b>{config.POLL_INTERVAL} с</b>")

    # Состояние пула подборок: пустой пул и сломанный сбор снаружи
    # выглядят одинаково, и разница обнаруживалась только чтением кода.
    try:
        from .. import monitor

        state = monitor.digest_state()
        lines.append("")
        lines.append("📰 <b>Подборки</b>")
        if not state["enabled"]:
            lines.append("Выключены флагом.")
        elif not state["total"]:
            lines.append(
                "В пуле пусто. Если так дольше часа — новости не проходят "
                "разбор по тематикам."
            )
        else:
            lines.append(f"В пуле новостей: <b>{state['total']}</b>")
            top = sorted(state["topics"].items(), key=lambda item: -item[1])[:6]
            lines.append(", ".join(f"{key} — {count}" for key, count in top))
    except Exception:  # noqa: BLE001
        pass

    lines.append("")
    lines.append(
        "<i>Проценты показывают, что именно оптимизировать. Сбор источников "
        "и разбор ИИ упираются в сеть и внешний сервис, а не в скорость кода.</i>"
    )
    return "\n".join(lines)


@router.message(Command("perf"))
async def cmd_perf(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Замеры доступны суперадминистратору.")
        return
    await message.answer(_report(), reply_markup=_menu())


@router.callback_query(F.data == "perf:show")
async def perf_show(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _report(), _menu())


@router.callback_query(F.data == "perf:reset")
async def perf_reset(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    profiling.reset()
    await call.answer("Счётчики сброшены.")
    await safe_edit(call, _report(), _menu())
