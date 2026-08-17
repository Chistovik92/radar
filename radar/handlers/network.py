"""Выход бота в интернет и выбор провайдера ИИ. Только суперадминистратор."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import config, proxy, provider, roles, secrets
from ..states import Form
from ..textutils import esc, split_text
from ..tg import back_kb, safe_edit, send_html

log = logging.getLogger("radar.handlers.network")
router = Router(name="network")

_state = proxy.ProxyState()


def _load_state() -> proxy.ProxyState:
    """Восстанавливает состояние из .env при первом обращении."""
    if _state.servers or not secrets.get("EGRESS_SOURCE"):
        return _state

    source = secrets.get("EGRESS_SOURCE")
    _state.source = source
    payload = secrets.get("EGRESS_PAYLOAD")
    if payload:
        _state.servers = proxy.parse_subscription(payload)
    elif not proxy.is_subscription_url(source):
        server = proxy.parse_uri(source)
        if server is not None:
            _state.servers = [server]

    _state.selected = secrets.get("EGRESS_SELECTED")
    _state.enabled = bool(config.EGRESS_PROXY)
    return _state


# --------------------------------------------------------------------------
#  Меню
# --------------------------------------------------------------------------

def _menu() -> InlineKeyboardMarkup:
    state = _load_state()
    rows: list[list[InlineKeyboardButton]] = []

    if state.servers:
        rows.append([
            InlineKeyboardButton(text="🖥 Выбрать сервер", callback_data="net:list:0")
        ])
        if state.selected:
            action = "⏸ Выключить выход" if state.enabled else "▶️ Включить выход"
            rows.append([InlineKeyboardButton(text=action, callback_data="net:toggle")])
        rows.append([
            InlineKeyboardButton(text="🔄 Обновить подписку", callback_data="net:refresh"),
            InlineKeyboardButton(text="🗑 Удалить ключ", callback_data="net:drop"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="➕ Добавить ключ или подписку", callback_data="net:add")
        ])

    rows.append([InlineKeyboardButton(text="◀️ К управлению", callback_data="menu:manage")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("network"))
async def cmd_network(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Выход в сеть настраивает суперадминистратор.")
        return
    await message.answer(proxy.describe(_load_state()), reply_markup=_menu())


@router.callback_query(F.data == "net:menu")
async def show_menu(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await safe_edit(call, proxy.describe(_load_state()), _menu())


# --------------------------------------------------------------------------
#  Добавление ключа
# --------------------------------------------------------------------------

@router.callback_query(F.data == "net:add")
async def ask_key(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await state.set_state(Form.proxy_key)
    await safe_edit(
        call,
        "➕ <b>Ключ или подписка</b>\n\n"
        "Пришлите одно из:\n"
        "• ссылку на подписку (<code>https://…/sub/…</code>)\n"
        "• <code>vless://…</code>\n"
        "• <code>ss://…</code>\n"
        "• <code>trojan://…</code>\n"
        "• <code>socks5://host:port</code>\n\n"
        "<b>Добавление ключа ничего не включает.</b> Из подписки приходят "
        "десятки серверов; какой из них использовать и по какому протоколу — "
        "вы выберете вручную следующим шагом.\n\n"
        "<i>/cancel — отмена.</i>",
        back_kb("net:menu", "Отмена"),
    )


@router.message(Form.proxy_key)
async def save_key(message: Message, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await state.clear()
        return

    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    await state.clear()
    try:
        await message.delete()      # ключ не должен оставаться в переписке
    except Exception:  # noqa: BLE001
        pass

    notice = await message.answer("🔎 Разбираю ключ…")

    servers: list[proxy.Server] = []
    payload = ""

    if proxy.is_subscription_url(text):
        payload = await _download(text)
        if not payload:
            await notice.edit_text(
                "❌ Подписку скачать не удалось. Проверьте ссылку и доступность "
                "сервера подписки.",
                reply_markup=back_kb("net:menu", "◀️ Назад"),
            )
            return
        servers = proxy.parse_subscription(payload)
    else:
        single = proxy.parse_uri(text)
        if single is not None:
            servers = [single]

    if not servers:
        await notice.edit_text(
            "❌ Не удалось разобрать. Поддерживаются подписки, vless://, ss://, "
            "trojan:// и socks5://.",
            reply_markup=back_kb("net:menu", "◀️ Назад"),
        )
        return

    _state.source = text
    _state.servers = servers
    _state.selected = ""
    _state.enabled = False

    secrets.write("EGRESS_SOURCE", text)
    if payload:
        secrets.write("EGRESS_PAYLOAD", payload.replace("\n", "|"))
    secrets.write("EGRESS_SELECTED", "")

    grouped = _state.by_protocol()
    summary = ", ".join(
        f"{name.upper()}: {len(items)}" for name, items in sorted(grouped.items())
    )
    await notice.edit_text(
        f"✅ Загружено серверов: <b>{len(servers)}</b>\n{esc(summary)}\n\n"
        "⚠️ <b>Выход в сеть пока не включён.</b> Выберите сервер — только после "
        "этого трафик пойдёт через него.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🖥 Выбрать сервер", callback_data="net:list:0")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="net:menu")],
        ]),
    )


async def _download(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": config.USER_AGENT}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    log.warning("Подписка вернула HTTP %s", response.status)
                    return ""
                return await response.text()
    except Exception as exc:  # noqa: BLE001
        log.warning("Подписка недоступна: %s", exc)
        return ""


# --------------------------------------------------------------------------
#  Выбор сервера
# --------------------------------------------------------------------------

PAGE = 8


@router.callback_query(F.data.startswith("net:list:"))
async def list_servers(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    page = int(call.data.split(":")[2])
    state = _load_state()
    if not state.servers:
        await call.answer("Серверов нет.", show_alert=True)
        return

    chunk = state.servers[page * PAGE:(page + 1) * PAGE]
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if item.key == state.selected else "") + item.label[:48],
                callback_data=f"net:pick:{page * PAGE + index}",
            )
        ]
        for index, item in enumerate(chunk)
    ]

    navigation: list[InlineKeyboardButton] = []
    if page:
        navigation.append(
            InlineKeyboardButton(text="◀️", callback_data=f"net:list:{page - 1}")
        )
    if (page + 1) * PAGE < len(state.servers):
        navigation.append(
            InlineKeyboardButton(text="▶️", callback_data=f"net:list:{page + 1}")
        )
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="net:menu")])

    total_pages = (len(state.servers) + PAGE - 1) // PAGE
    await call.answer()
    await safe_edit(
        call,
        f"🖥 <b>Выбор сервера</b>\nСтраница {page + 1} из {total_pages}\n\n"
        "<i>Выбор определяет и протокол, и страну, из которой бот виден "
        "площадкам.</i>",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("net:pick:"))
async def pick_server(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    index = int(call.data.split(":")[2])
    state = _load_state()
    if index >= len(state.servers):
        await call.answer("Сервер не найден.", show_alert=True)
        return

    server = state.servers[index]
    state.selected = server.key
    secrets.write("EGRESS_SELECTED", server.key)

    # Конфигурация пишется рядом с ботом: её читает sing-box
    written = _write_config(server)
    await call.answer(f"Выбран: {server.label[:40]}")

    lines = [
        f"✅ <b>Сервер выбран</b>\n{esc(server.label)}",
        f"<code>{esc(server.host)}:{server.port}</code>",
        "",
    ]
    if written:
        lines.append("Конфигурация sing-box записана.")
    else:
        lines.append("⚠️ Конфигурацию записать не удалось — проверьте права на data/.")
    lines.append("")
    lines.append(
        "Чтобы трафик пошёл через него, включите выход и перезапустите "
        "контейнеры: <code>docker compose --profile proxy up -d</code>"
    )

    await safe_edit(
        call,
        "\n".join(lines),
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Включить выход", callback_data="net:toggle")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="net:menu")],
        ]),
    )


def _write_config(server: proxy.Server) -> bool:
    try:
        path = proxy.CONFIG_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(proxy.render_config(server))
        return True
    except OSError as exc:
        log.error("Конфигурация sing-box не записана: %s", exc)
        return False


@router.callback_query(F.data == "net:toggle")
async def toggle(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    state = _load_state()
    if not state.selected:
        await call.answer("Сначала выберите сервер.", show_alert=True)
        return

    state.enabled = not state.enabled
    value = f"socks5://singbox:{proxy.LOCAL_PORT}" if state.enabled else ""
    secrets.write("EGRESS_PROXY", value)

    await call.answer("Включено" if state.enabled else "Выключено")
    note = (
        "Трафик пойдёт через выбранный сервер после перезапуска."
        if state.enabled else
        "Бот вернётся к прямому подключению после перезапуска."
    )
    await safe_edit(
        call,
        f"{proxy.describe(state)}\n\n⚠️ <i>{note}</i>\n"
        "<code>docker compose --profile proxy up -d</code>",
        _menu(),
    )


@router.callback_query(F.data == "net:refresh")
async def refresh(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    state = _load_state()
    if not proxy.is_subscription_url(state.source):
        await call.answer("Обновлять нечего: добавлен отдельный ключ.", show_alert=True)
        return

    await call.answer("Обновляю…")
    payload = await _download(state.source)
    servers = proxy.parse_subscription(payload) if payload else []
    if not servers:
        await safe_edit(call, "❌ Подписка недоступна или пуста.", _menu())
        return

    previous = state.selected
    state.servers = servers
    secrets.write("EGRESS_PAYLOAD", payload.replace("\n", "|"))

    # Выбранный сервер мог исчезнуть из подписки — честно об этом сообщаем
    if previous and not any(item.key == previous for item in servers):
        state.selected = ""
        state.enabled = False
        secrets.write("EGRESS_SELECTED", "")
        secrets.write("EGRESS_PROXY", "")
        await safe_edit(
            call,
            f"🔄 Обновлено: <b>{len(servers)}</b> серверов.\n\n"
            "⚠️ Прежний сервер из подписки пропал — выход выключен, "
            "выберите новый.",
            _menu(),
        )
        return

    await safe_edit(call, f"🔄 Обновлено: <b>{len(servers)}</b> серверов.\n\n"
                          f"{proxy.describe(state)}", _menu())


@router.callback_query(F.data == "net:drop")
async def drop(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    _state.source = ""
    _state.servers = []
    _state.selected = ""
    _state.enabled = False
    for key in ("EGRESS_SOURCE", "EGRESS_PAYLOAD", "EGRESS_SELECTED", "EGRESS_PROXY"):
        secrets.clear(key)

    await call.answer("Удалено")
    await safe_edit(
        call,
        "🗑 Ключ удалён, бот вернётся к прямому подключению после перезапуска.",
        _menu(),
    )


# --------------------------------------------------------------------------
#  Провайдер ИИ
# --------------------------------------------------------------------------

def _provider_menu() -> InlineKeyboardMarkup:
    active = provider.current()
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if info.key == active else "") + info.title,
                callback_data=f"prov:pick:{info.key}",
            )
        ]
        for info in provider.available()
    ]
    rows.append([
        InlineKeyboardButton(text="🔄 Проверить доступ и баланс", callback_data="prov:check")
    ])
    rows.append([InlineKeyboardButton(text="◀️ К управлению ИИ", callback_data="ai:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("provider"))
async def cmd_provider(message: Message, role: str) -> None:
    if not roles.is_superadmin(role):
        await message.answer("⛔️ Провайдера выбирает суперадминистратор.")
        return
    await message.answer(_provider_overview(), reply_markup=_provider_menu())


def _provider_overview() -> str:
    active = provider.current()
    lines = ["🤖 <b>Провайдер разбора новостей</b>", ""]
    for info in provider.PROVIDERS.values():
        mark = "✅" if info.key == active else ("•" if secrets.get(info.env) else "—")
        lines.append(f"{mark} <b>{esc(info.title)}</b>")
        lines.append(f"   <i>{esc(info.note)}</i>")
    lines.append("")
    lines.append(
        "<i>Смена действует со следующего разбора, перезапуск не нужен. "
        "ИИ-ассистент в диалоге всегда работает через Gemini: только он "
        "умеет искать в интернете.</i>"
    )
    return "\n".join(lines)


@router.callback_query(F.data == "prov:menu")
async def provider_menu(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, _provider_overview(), _provider_menu())


@router.callback_query(F.data == "prov:check")
async def provider_check(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    await call.answer("Проверяю…")
    results = await provider.check_all()
    await safe_edit(call, provider.render(results), _provider_menu())


@router.callback_query(F.data.startswith("prov:pick:"))
async def provider_pick(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    key = call.data.split(":")[2]
    info = provider.PROVIDERS.get(key)
    if info is None:
        await call.answer("Неизвестный провайдер.", show_alert=True)
        return

    await call.answer("Проверяю доступ…")
    health = await provider.check(key)

    # Платный провайдер с нулевым балансом не отличить от рабочего до первого
    # запроса — а первым окажется разбор настоящей тревоги. Проверяем заранее.
    if not health.ok:
        await safe_edit(
            call,
            f"❌ <b>{esc(info.title)}</b> недоступен: {esc(health.detail or 'нет ответа')}\n\n"
            "Переключение отменено — прежний провайдер продолжает работать.",
            _provider_menu(),
        )
        return

    if not provider.select(key):
        await safe_edit(call, "❌ Переключить не удалось.", _provider_menu())
        return

    lines = [f"✅ Провайдер разбора: <b>{esc(info.title)}</b>"]
    if health.balance:
        lines.append(f"{esc(health.balance)}")
    if health.balance_low:
        lines.append("\n⚠️ <i>Остаток на исходе — пополните, иначе разбор "
                     "переключится на эвристику.</i>")
    lines.append("\n<i>Действует со следующего разбора новостей.</i>")

    await safe_edit(call, "\n".join(lines), _provider_menu())
