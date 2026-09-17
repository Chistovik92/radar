"""Модерация групп: исполнение решений и команды администраторов.

Разделение намеренное: что делать — решает `radar/moderation.py`, чистый
и офлайн-проверяемый; здесь только Telegram — права, удаление, мут, бан
и разговор с людьми.

Два правила, которые легко нарушить и дорого исправлять:

* администратор чата не модерируется. Бот не спорит с тем, кто его
  назначил, и права проверяет у Telegram, а не по ролям «Радара»:
  админ группы и админ бота — разные списки;
* об отсутствии прав бот сообщает ОДИН раз на чат. Иначе каждое
  нарушение превращается в жалобу в тот же чат, и получается тот самый
  спам, ради борьбы с которым бота и позвали.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import features, moderation
from ..db import repo

log = logging.getLogger("radar.group")

router = Router(name="group")

_flood = moderation.FloodTracker()
# Когда человек вошёл в чат: нужно, чтобы отличать новичка. В памяти —
# по той же причине, что и антифлуд: переживать перезапуск незачем,
# а после перезапуска все просто перестают считаться новичками.
_joined: dict[tuple[int, int], float] = {}
# Чаты, где уже пожаловались на нехватку прав.
_complained: set[int] = set()
# Кому выдана капча: до нажатия человек ограничен.
_pending: dict[tuple[int, int], float] = {}

MUTED = ChatPermissions(can_send_messages=False)
UNMUTED = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_other_messages=True,
    can_add_web_page_previews=True,
)


async def _settings(chat_id: int) -> tuple[bool, moderation.Settings]:
    """Настройки чата: включён ли он и по каким правилам живёт."""
    row = await repo.chat_get(chat_id)
    if row is None:
        return False, moderation.Settings()
    stored = {}
    if row.get("settings"):
        try:
            stored = json.loads(row["settings"])
        except ValueError:
            log.warning("Настройки чата %s не разобраны", chat_id)
    known = {field: stored[field] for field in moderation.Settings().__dict__
             if field in stored}
    return bool(row.get("enabled")), moderation.Settings(**known)


async def _is_admin(message: Message, user_id: int) -> bool:
    try:
        member = await message.bot.get_chat_member(message.chat.id, user_id)
    except Exception:  # noqa: BLE001
        return False
    return member.status in ("creator", "administrator")


async def _complain_once(message: Message, what: str) -> None:
    if message.chat.id in _complained:
        return
    _complained.add(message.chat.id)
    try:
        await message.answer(
            f"⚠️ Не могу {what}: не хватает прав администратора.\n"
            "Дайте боту права на удаление сообщений и блокировку участников — "
            "иначе модерация работать не будет."
        )
    except Exception:  # noqa: BLE001
        log.debug("Жалоба о правах не отправлена", exc_info=True)


async def _apply(message: Message, decision: moderation.Decision,
                 settings: moderation.Settings) -> None:
    """Исполняет решение. Каждое действие — отдельное право, и отсутствие
    одного не должно отменять остальные."""
    user = message.from_user

    if decision.delete_message:
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            await _complain_once(message, "удалять сообщения")

    if decision.action == moderation.WARN:
        await repo.warn_add(message.chat.id, user.id)
    elif decision.action == moderation.MUTE:
        await repo.warn_add(message.chat.id, user.id)
        until = datetime.now(timezone.utc) + timedelta(
            minutes=settings.mute_minutes)
        try:
            await message.bot.restrict_chat_member(
                message.chat.id, user.id, permissions=MUTED, until_date=until)
        except Exception:  # noqa: BLE001
            await _complain_once(message, "ограничивать участников")
    elif decision.action == moderation.BAN:
        try:
            await message.bot.ban_chat_member(message.chat.id, user.id)
        except Exception:  # noqa: BLE001
            await _complain_once(message, "блокировать участников")
        else:
            await repo.warn_reset(message.chat.id, user.id)

    text = moderation.describe(decision, settings)
    if text:
        try:
            await message.answer(text)
        except Exception:  # noqa: BLE001
            log.debug("Сообщение о модерации не отправлено", exc_info=True)


@router.message(F.new_chat_members)
async def greet_newcomers(message: Message) -> None:
    """Встреча новичков: приветствие и кнопка-подтверждение."""
    if not features.enabled("moderation"):
        return
    enabled, _settings_of = await _settings(message.chat.id)
    if not enabled:
        return

    for member in message.new_chat_members or []:
        if member.is_bot:
            continue
        _joined[(message.chat.id, member.id)] = time.time()
        _pending[(message.chat.id, member.id)] = time.time()
        try:
            await message.bot.restrict_chat_member(
                message.chat.id, member.id, permissions=MUTED)
        except Exception:  # noqa: BLE001
            await _complain_once(message, "ограничивать участников")
            continue
        await message.answer(
            f"👋 {member.full_name}, добро пожаловать. "
            "Нажмите кнопку — так видно, что вы не бот.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Я не бот",
                                     callback_data=f"grp:ok:{member.id}")
            ]]),
        )

    # Служебное сообщение о входе убираем: оно засоряет чат.
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("grp:ok:"))
async def confirm_human(call: CallbackQuery) -> None:
    """Капча: кнопку должен нажать тот, кому она выдана."""
    target = int(call.data.rsplit(":", 1)[1])
    if call.from_user.id != target:
        await call.answer("Эта кнопка не для вас.", show_alert=True)
        return

    chat_id = call.message.chat.id
    _pending.pop((chat_id, target), None)
    try:
        await call.bot.restrict_chat_member(chat_id, target,
                                            permissions=UNMUTED)
    except Exception:  # noqa: BLE001
        log.warning("Не удалось снять ограничение с %s", target)
    await call.answer("Спасибо!")
    try:
        await call.message.delete()
    except Exception:  # noqa: BLE001
        pass


@router.message(F.left_chat_member)
async def clean_leave(message: Message) -> None:
    """Сообщение «вышел из группы» — такой же мусор, как и «вошёл»."""
    if not features.enabled("moderation"):
        return
    enabled, _ = await _settings(message.chat.id)
    if enabled:
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass


@router.message(Command("modstatus"))
async def status(message: Message) -> None:
    enabled, settings = await _settings(message.chat.id)
    if not await _is_admin(message, message.from_user.id):
        return
    await message.answer(
        f"Модерация: {'включена' if enabled else 'выключена'}\n"
        f"Предупреждений до мута: {settings.warns_before_mute}, "
        f"до бана: {settings.warns_before_ban}\n"
        f"Мут: {settings.mute_minutes} мин · "
        f"антифлуд: {'да' if settings.antiflood else 'нет'} "
        f"({settings.flood_messages} за {settings.flood_seconds} с)\n"
        f"Стоп-слов: {len(settings.stopwords)}\n"
        f"Идентификатор чата: <code>{message.chat.id}</code>"
    )


@router.message(Command("warn", "mute", "ban", "unban"))
async def manual_action(message: Message) -> None:
    """Ручные команды. Только для администраторов чата и только ответом
    на сообщение: иначе непонятно, к кому применять."""
    if not await _is_admin(message, message.from_user.id):
        return
    if message.reply_to_message is None:
        await message.answer("Команда работает ответом на сообщение.")
        return

    target = message.reply_to_message.from_user
    command = (message.text or "").split()[0].lstrip("/").split("@")[0]
    _enabled, settings = await _settings(message.chat.id)

    if command == "warn":
        count = await repo.warn_add(message.chat.id, target.id)
        await message.answer(f"⚠️ {target.full_name}: предупреждение {count}")
        return

    if command == "mute":
        until = datetime.now(timezone.utc) + timedelta(
            minutes=settings.mute_minutes)
        try:
            await message.bot.restrict_chat_member(
                message.chat.id, target.id, permissions=MUTED,
                until_date=until)
        except Exception:  # noqa: BLE001
            await _complain_once(message, "ограничивать участников")
            return
        await message.answer(
            f"🔇 {target.full_name} — тишина на {settings.mute_minutes} мин")
        return

    if command == "ban":
        try:
            await message.bot.ban_chat_member(message.chat.id, target.id)
        except Exception:  # noqa: BLE001
            await _complain_once(message, "блокировать участников")
            return
        await repo.warn_reset(message.chat.id, target.id)
        await message.answer(f"⛔️ {target.full_name} заблокирован")
        return

    try:
        await message.bot.unban_chat_member(message.chat.id, target.id,
                                            only_if_banned=True)
    except Exception:  # noqa: BLE001
        await _complain_once(message, "снимать блокировку")
        return
    await repo.warn_reset(message.chat.id, target.id)
    await message.answer(f"✅ {target.full_name} разблокирован")


@router.message(F.text)
async def moderate(message: Message) -> None:
    """Главный путь: каждое текстовое сообщение группы."""
    if not features.enabled("moderation"):
        return

    enabled, settings = await _settings(message.chat.id)
    if not enabled:
        return

    user = message.from_user
    if user is None or user.is_bot:
        return

    # Пока капча не пройдена, любое сообщение удаляется: ограничение
    # Telegram могло не примениться, если у бота не хватило прав.
    if (message.chat.id, user.id) in _pending:
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
        return

    joined = _joined.get((message.chat.id, user.id))
    author = moderation.Author(
        user_id=user.id,
        joined_ago_hours=((time.time() - joined) / 3600.0
                          if joined else 999.0),
        warns=await repo.warn_count(message.chat.id, user.id),
        is_admin=await _is_admin(message, user.id),
    )

    flood = _flood.hit(message.chat.id, user.id, settings.flood_seconds)
    decision = moderation.decide(message.text or "", author, settings, flood)
    if not decision.acts:
        return

    log.info("Модерация %s: %s (%s)", message.chat.id, decision.action,
             decision.reason)
    await _apply(message, decision, settings)
