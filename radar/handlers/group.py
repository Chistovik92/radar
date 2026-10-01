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

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import accounts, chatlink, features, moderation
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
# Сообщение с кнопкой — чтобы убрать его, когда время вышло (с 5.9.4).
_captcha_msgs: dict[tuple[int, int], int] = {}
# Кого уже записали в «известные участники» за время работы процесса:
# без этого каждое сообщение чата стоило бы запроса к базе.
_remembered: set[tuple[int, int]] = set()
# Результат проверки на удалённые аккаунты до подтверждения:
# чат → (когда, кто запросил, найденные).
_scans: dict[int, tuple[float, int, list[int]]] = {}
SCAN_TTL = 600
CAPTCHA_SWEEP = 30

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


@router.my_chat_member()
async def track_membership(event: ChatMemberUpdated) -> None:
    """Бота добавили, повысили или выгнали.

    Чат заводится сам: просить человека переписать в панель
    идентификатор вида -1001234567890 — значит предложить ошибиться.
    """
    status = getattr(event.new_chat_member, "status", "")
    title = getattr(event.chat, "title", "") or ""

    if status in ("left", "kicked"):
        await repo.chat_forget(event.chat.id)
        chatlink.forget(event.chat.id)
        # Чат, откуда бота выгнали, не должен висеть кнопкой в меню
        # у пользователей: ссылка могла пережить бота, но звать туда
        # от имени бота уже незачем.
        await chatlink.refresh_published()
        log.info("Бот удалён из чата %s", event.chat.id)
        return

    if status == "administrator":
        await repo.chat_save(event.chat.id, title=title, enabled=True)
        _complained.discard(event.chat.id)
        try:
            await event.bot.send_message(
                event.chat.id,
                "🛡 Модерация включена.\n\n"
                "Тех, кто уже в группе, это не касается: проверка "
                "и приветствие — только для тех, кто войдёт дальше. "
                "Администраторов чата бот не модерирует.\n\n"
                "Команды для админов: /warn, /mute, /ban, /unban "
                "ответом на сообщение и /modstatus."
            )
        except Exception:  # noqa: BLE001
            log.debug("Приветствие в чат не отправлено", exc_info=True)
        return

    # Добавили обычным участником — прав на модерацию нет.
    await repo.chat_save(event.chat.id, title=title, enabled=False)
    try:
        await event.bot.send_message(
            event.chat.id,
            "Бот добавлен, но модерировать не может: нужны права "
            "администратора — «Удаление сообщений» и «Блокировка "
            "участников»."
        )
    except Exception:  # noqa: BLE001
        log.debug("Сообщение о правах не отправлено", exc_info=True)


@router.message(F.new_chat_members)
async def greet_newcomers(message: Message) -> None:
    """Встреча новичков: приветствие и кнопка-подтверждение.

    Только для тех, кто входит ПОСЛЕ подключения бота: событие
    приходит на само вступление, и уже сидящих в группе оно не касается
    вовсе. Это осознанно — здороваться с людьми, которые тут давно,
    и требовать от них нажать кнопку было бы навязчиво.
    """
    if not features.enabled("moderation"):
        return
    enabled, _settings_of = await _settings(message.chat.id)
    if not enabled:
        return

    for member in message.new_chat_members or []:
        if member.is_bot:
            continue
        await _remember(message.chat.id, member.id)

        # Известные спамеры — до приветствия: незачем встречать того,
        # кого в этот же миг исключат. Недоступность сервиса пускает
        # человека дальше (капча остаётся).
        if features.enabled("cas_check") and await accounts.cas_banned(member.id):
            try:
                await message.bot.ban_chat_member(message.chat.id, member.id)
                log.info("CAS: %s исключён из %s", member.id, message.chat.id)
                continue
            except Exception:  # noqa: BLE001
                await _complain_once(message, "блокировать участников")

        _joined[(message.chat.id, member.id)] = time.time()
        _pending[(message.chat.id, member.id)] = time.time()
        try:
            await message.bot.restrict_chat_member(
                message.chat.id, member.id, permissions=MUTED)
        except Exception:  # noqa: BLE001
            await _complain_once(message, "ограничивать участников")
            continue
        sent = await message.answer(
            f"👋 {member.full_name}, добро пожаловать. "
            "Нажмите кнопку — так видно, что вы не бот.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Я не бот",
                                     callback_data=f"grp:ok:{member.id}")
            ]]),
        )
        _captcha_msgs[(message.chat.id, member.id)] = sent.message_id

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
    _captcha_msgs.pop((chat_id, target), None)
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


@router.message(Command("modon", "modoff"))
async def switch(message: Message) -> None:
    """Включить или выключить модерацию прямо в группе.

    Нужно ещё и потому, что `my_chat_member` приходит только НА ИЗМЕНЕНИЕ:
    группы, куда бота добавили до появления модерации, сами о себе
    не заявят. Одна команда от администратора — и чат в списке.
    """
    if not await _is_admin(message, message.from_user.id):
        return

    wanted = (message.text or "").split()[0].lstrip("/").split("@")[0] == "modon"
    await repo.chat_save(message.chat.id,
                         title=message.chat.title or "",
                         enabled=wanted)
    if not wanted:
        await message.answer("Модерация выключена в этом чате.")
        return

    if not features.enabled("moderation"):
        await message.answer(
            "Чат записан, но модерация выключена во всём боте — "
            "включите возможность «Модерация групп» в разделе "
            "«Возможности»."
        )
        return
    await message.answer(
        "🛡 Модерация включена.\n\n"
        "Тех, кто уже в группе, это не касается: приветствие и проверка — "
        "только для входящих дальше. Администраторов чата бот "
        "не модерирует."
    )


@router.message(Command("modstatus"))
async def status(message: Message) -> None:
    if not await _is_admin(message, message.from_user.id):
        return

    enabled, settings = await _settings(message.chat.id)
    known = await repo.chat_get(message.chat.id)
    if known is None:
        # Чат добавлен раньше, чем появилась модерация: заведём его,
        # но включать без просьбы не будем.
        await repo.chat_save(message.chat.id,
                             title=message.chat.title or "", enabled=False)
        await message.answer(
            "Чат записан. Модерация пока выключена — включите командой "
            "<code>/modon</code>."
        )
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


async def _remember(chat_id: int, user_id: int) -> None:
    """Запоминает человека как известного участника чата (для чистки)."""
    key = (chat_id, user_id)
    if key in _remembered or not features.enabled("deleted_cleanup"):
        return
    _remembered.add(key)
    try:
        await repo.member_seen(chat_id, user_id)
    except Exception:  # noqa: BLE001
        _remembered.discard(key)
        log.debug("Участник не записан", exc_info=True)


def _scan_text(scan: accounts.Scan) -> str:
    lines = [
        "🧹 <b>Проверка удалённых аккаунтов</b>",
        f"Известно боту участников: <b>{scan.coverage}</b>",
        f"Проверено: <b>{scan.checked}</b>"
        + (f", не удалось: {scan.failed}" if scan.failed else ""),
        f"Удалённых аккаунтов: <b>{len(scan.deleted)}</b>",
    ]
    if scan.members_total and scan.known < scan.members_total:
        lines.append(
            "<i>Bot API не отдаёт список участников, поэтому бот проверяет "
            "только тех, кого видел с момента подключения — по вступлению "
            "или сообщению. Остальные попадут в проверку, когда напишут.</i>")
    if scan.truncated:
        lines.append(f"<i>За раз проверяется не больше {accounts.SCAN_LIMIT}.</i>")
    return "\n".join(lines)


@router.message(Command("cleandeleted"))
async def clean_deleted(message: Message) -> None:
    """Чистка удалённых аккаунтов: проверить и по кнопке исключить."""
    if not features.enabled("deleted_cleanup"):
        return
    if not await _is_admin(message, message.from_user.id):
        return
    chat_id = message.chat.id
    status = await message.answer("⏳ Проверяю известных боту участников…")
    ids = await repo.member_ids(chat_id)
    if not ids:
        await status.edit_text(
            "Бот пока не видел в этом чате ни одного участника. Список "
            "наполняется по мере вступлений и сообщений — загляните позже.")
        return
    scan = await accounts.scan_chat(message.bot, chat_id, ids)
    text = _scan_text(scan)
    if not scan.deleted:
        await status.edit_text(text)
        return
    _scans[chat_id] = (time.time(), message.from_user.id, scan.deleted)
    await status.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"Исключить {len(scan.deleted)}",
                                 callback_data=f"grp:purge:{chat_id}"),
            InlineKeyboardButton(text="Отмена", callback_data=f"grp:keep:{chat_id}"),
        ]]))


@router.callback_query(F.data.startswith("grp:purge:") | F.data.startswith("grp:keep:"))
async def clean_deleted_confirm(call: CallbackQuery) -> None:
    action, _, raw = call.data.rpartition(":")
    chat_id = int(raw)
    if call.message is None or call.message.chat.id != chat_id:
        await call.answer()
        return
    try:
        member = await call.bot.get_chat_member(chat_id, call.from_user.id)
        allowed = member.status in ("creator", "administrator")
    except Exception:  # noqa: BLE001
        allowed = False
    if not allowed:
        await call.answer("Только для администраторов чата.", show_alert=True)
        return
    stored = _scans.pop(chat_id, None)
    if action.endswith("keep") or stored is None or time.time() - stored[0] > SCAN_TTL:
        await call.answer("Отменено." if action.endswith("keep")
                          else "Результат устарел — запустите проверку заново.")
        try:
            await call.message.delete()
        except Exception:  # noqa: BLE001
            pass
        return
    await call.answer("Исключаю…")
    removed = await accounts.remove_deleted(call.bot, chat_id, stored[2])
    try:
        await call.message.edit_text(f"✅ Исключено удалённых аккаунтов: <b>{removed}</b>")
    except Exception:  # noqa: BLE001
        pass


async def captcha_sweeper(bot) -> None:
    """Исключает тех, кто не нажал кнопку за отведённое время (с 5.9.4).

    До 5.9.4 запись о капче жила вечно: человек оставался немым, пока
    не нажмёт, а бот-спамер, вошедший и замолчавший, оставался в группе
    навсегда. Исключение — «бан и сразу разбан»: прийти снова можно.
    """
    while True:
        await asyncio.sleep(CAPTCHA_SWEEP)
        if not features.enabled("captcha_kick"):
            continue
        now = time.time()
        for key, since in list(_pending.items()):
            chat_id, user_id = key
            try:
                _enabled, settings = await _settings(chat_id)
            except Exception:  # noqa: BLE001
                continue
            if now - since < max(1, settings.captcha_minutes) * 60:
                continue
            try:
                await bot.ban_chat_member(chat_id, user_id)
                await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
                log.info("Капча не пройдена: %s исключён из %s", user_id, chat_id)
            except Exception:  # noqa: BLE001
                log.debug("Не удалось исключить %s", user_id, exc_info=True)
            finally:
                _pending.pop(key, None)
                message_id = _captcha_msgs.pop(key, None)
                if message_id:
                    try:
                        await bot.delete_message(chat_id, message_id)
                    except Exception:  # noqa: BLE001
                        pass


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
    await _remember(message.chat.id, user.id)

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
