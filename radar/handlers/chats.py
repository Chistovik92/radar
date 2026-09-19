"""Раздел «Чаты» в самой переписке с ботом.

Отсюда видно, где бот модерирует, и отсюда же можно перейти в группу:
кнопка ведёт по ссылке — публичному имени, существующей ссылке владельца
или, если ни того ни другого нет, по созданной ботом (см. `radar/chatlink.py`).

Раздел личный, а не групповой: список чатов и переходы — дело
администрации, а не участников группы.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import chatlink, chatpost, features, roles
from ..db import repo
from ..states import Form
from ..textutils import esc
from ..tg import bot, safe_edit, send_html

log = logging.getLogger("radar.chats")

router = Router(name="chats")

ADD_HINT = (
    "🛡 <b>Чаты под модерацией</b>\n\n"
    "Пока ни одной группы.\n\n"
    "<b>Как добавить бота:</b>\n"
    "1. Откройте группу → «Участники» → «Добавить».\n"
    "2. Найдите бота по имени и добавьте.\n"
    "3. Там же сделайте его администратором и включите права "
    "<b>«Удаление сообщений»</b> и <b>«Блокировка участников»</b>.\n"
    "4. Напишите в группе <code>/modon</code> — чат появится здесь.\n\n"
    "<b>Бот уже в группе?</b> Тогда ничего добавлять не нужно: "
    "проверьте, что он администратор с этими правами, и напишите "
    "в группе <code>/modon</code>. Группы, куда бота добавили раньше, "
    "сами о себе не заявляют — Telegram сообщает боту только "
    "об изменениях.\n\n"
    "<i>Менять privacy mode у @BotFather не нужно: администратор "
    "получает все сообщения и так. Тем, кто уже в группе, бот ничего "
    "не пишет — проверка только для тех, кто войдёт после включения.</i>"
)


def can_post(role: str) -> bool:
    """Кому доступны объявления в группы.

    Только суперадминистратору: сообщение уходит от имени бота, и для
    участников группы это голос системы. Такое право не раздаётся вместе
    с обычными администраторскими — и без флага не появляется вовсе.
    """
    return roles.is_superadmin(role) and features.enabled("chat_post")


def _keyboard(rows: list[dict], links: dict[int, str],
              role: str = "") -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    posting = can_post(role)
    for row in rows:
        chat_id = row["chat_id"]
        title = row["title"] or str(chat_id)
        mark = "🟢" if row["enabled"] else "⚪️"
        link = links.get(chat_id, "")
        if link:
            line = [InlineKeyboardButton(text=f"{mark} {title}", url=link)]
        else:
            line = [InlineKeyboardButton(
                text=f"{mark} {title}", callback_data=f"chat:why:{chat_id}")]
        if posting:
            # Вторая кнопка в той же строке: список групп и так длинный,
            # а отдельная строка на каждую удвоила бы его.
            line.append(InlineKeyboardButton(
                text="✍️", callback_data=f"chat:say:{chat_id}"))
        if roles.is_superadmin(role):
            # Ссылка приглашения (с 4.9.9.1). Значок разный: по нему видно,
            # задана она руками или бот нашёл её сам.
            mark_link = "🔗" if row.get("invite") else "➕"
            line.append(InlineKeyboardButton(
                text=mark_link, callback_data=f"chat:link:{chat_id}"))
        buttons.append(line)
    buttons.append([InlineKeyboardButton(text="◀️ Назад",
                                         callback_data="menu:manage")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _render(role: str, lang: str = "ru") -> tuple[str, InlineKeyboardMarkup]:
    # Список виден администрации — переведён в 4.9.9.3. Объявления
    # и ссылки приглашения ниже — только суперадминистратору и по
    # правилу проекта остаются русскими (ROADMAP, п.20).
    from .. import i18n

    def _(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    rows = await repo.chat_list()
    if not rows:
        return _("chats.add_hint", ADD_HINT), InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=_("menu.back", "◀️ Назад"),
                                 callback_data="menu:manage")
        ]])

    links: dict[int, str] = {}
    lines = [_("chats.title", "🛡 <b>Чаты под модерацией</b>"), ""]
    for row in rows:
        ok, value = await chatlink.link_for(row["chat_id"])
        if ok:
            links[row["chat_id"]] = value
        state = (_("chats.mod_on", "модерация включена") if row["enabled"]
                 else _("chats.mod_off", "модерация выключена"))
        lines.append(f"• <b>{esc(row['title'] or str(row['chat_id']))}</b> — {state}")
        if not ok:
            lines.append(f"  <i>{esc(value)}</i>")
    lines.append("")
    lines.append("<i>" + _("chats.tap_hint", "Нажмите на группу, чтобы перейти в неё.")
                 + "</i>")
    if roles.is_superadmin(role):
        lines.append("<i>🔗 — своя ссылка приглашения задана, ➕ — задать.</i>")
    if can_post(role):
        lines.append("<i>✍️ рядом с группой — написать в неё от имени бота.</i>")
    return "\n".join(lines), _keyboard(rows, links, role)


@router.message(Command("chats"))
async def cmd_chats(message: Message, role: str, user: dict) -> None:
    from .. import i18n

    if not roles.is_admin(role):
        return
    lang = i18n.language_of(user)
    if not features.enabled("moderation"):
        await send_html(message.chat.id, i18n.t(
            "chats.mod_disabled", lang,
            "Модерация выключена — включите её в разделе «Возможности»."))
        return
    text, keyboard = await _render(role, lang)
    await send_html(message.chat.id, text, keyboard)


@router.callback_query(F.data == "menu:chats")
async def menu_chats(call: CallbackQuery, role: str, user: dict) -> None:
    from .. import i18n

    lang = i18n.language_of(user)
    if not roles.is_admin(role):
        await call.answer(i18n.t("chats.admins_only", lang, "Только для администрации."),
                          show_alert=True)
        return
    await call.answer()
    text, keyboard = await _render(role, lang)
    await safe_edit(call, text, keyboard)


@router.callback_query(F.data.startswith("chat:why:"))
async def explain(call: CallbackQuery, role: str) -> None:
    """Почему у чата нет кнопки перехода."""
    if not roles.is_admin(role):
        await call.answer("Только для администрации.", show_alert=True)
        return
    chat_id = int(call.data.rsplit(":", 1)[1])
    _ok, reason = await chatlink.link_for(chat_id)
    await call.answer(reason, show_alert=True)


# --------------------------------------------------------------------------
#  Объявления в группу от имени бота (с 4.9.8.14)
# --------------------------------------------------------------------------
#
# Право суперадминистратора и только его: участники группы видят сообщение
# как голос системы, а не как частное письмо. Отправка идёт в два шага —
# сначала текст показывается так, как его увидят, и лишь потом уходит:
# объявление в чужую группу не отзывается.

_drafts: dict[int, chatpost.Draft] = {}


def _forget_stale(now: float | None = None) -> None:
    """Убирает черновики, которые уже никто не подтвердит."""
    stale = [key for key, draft in _drafts.items() if draft.expired(now)]
    for key in stale:
        _drafts.pop(key, None)


def back_kb_chats() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ К списку чатов", callback_data="menu:chats")
    ]])


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Отправить", callback_data="chat:send")],
        [InlineKeyboardButton(text="🗑 Отменить", callback_data="chat:drop")],
    ])


@router.callback_query(F.data.startswith("chat:say:"))
async def ask_message(call: CallbackQuery, state: FSMContext, role: str) -> None:
    """Спрашивает текст объявления."""
    if not can_post(role):
        await call.answer(
            "Писать в группы может только суперадминистратор, "
            "и при включённой возможности «Сообщения в группы».",
            show_alert=True,
        )
        return

    chat_id = int(call.data.rsplit(":", 1)[1])
    row = await repo.chat_get(chat_id)
    if row is None:
        await call.answer("Группа больше не в списке.", show_alert=True)
        return

    title = row.get("title") or str(chat_id)
    await call.answer()
    await state.set_state(Form.chat_message)
    await state.update_data(chat_id=chat_id, chat_title=title)
    await safe_edit(
        call,
        f"✍️ <b>Сообщение в «{esc(title)}»</b>\n\n"
        "Пришлите текст — он уйдёт в группу <b>от имени бота</b>. "
        "Жирный, курсив и ссылки сохраняются.\n\n"
        "Перед отправкой покажу, как это будет выглядеть.\n\n"
        "<i>/cancel — отменить</i>",
        back_kb_chats(),
    )


@router.message(Form.chat_message)
async def take_message(message: Message, state: FSMContext, role: str) -> None:
    """Принимает текст, проверяет его и показывает, как это будет выглядеть."""
    if not can_post(role):
        await state.clear()
        return

    # Разметку берём в виде HTML: человек форматирует сообщение привычными
    # средствами Telegram, и объявление должно выйти таким, каким он его
    # набрал. `html_text` есть не у всякого сообщения — например, у фото.
    text = getattr(message, "html_text", None) or message.text or ""
    if text.strip().startswith("/"):
        # Команды не объявления: /cancel и прочее разбирает свой обработчик.
        return
    if not text.strip():
        await send_html(
            message.chat.id,
            "Пока умею отправлять только текст. Пришлите сообщение текстом.",
            back_kb_chats(),
        )
        return

    ok, reason = chatpost.validate(text)
    if not ok:
        # Состояние не сбрасываем: человек правит текст и присылает снова.
        await send_html(message.chat.id, f"⚠️ {reason}\n\n<i>/cancel — отменить</i>")
        return

    data = await state.get_data()
    chat_id = int(data.get("chat_id") or 0)
    title = str(data.get("chat_title") or chat_id)
    await state.clear()

    _forget_stale()
    draft = chatpost.Draft(chat_id=chat_id, title=title, text=text.strip())
    _drafts[message.from_user.id] = draft
    await send_html(message.chat.id, chatpost.preview(draft), _confirm_kb())


@router.callback_query(F.data == "chat:drop")
async def drop_message(call: CallbackQuery, role: str) -> None:
    if not can_post(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    _drafts.pop(call.from_user.id, None)
    await call.answer("Объявление отменено.")
    text, keyboard = await _render(role)
    await safe_edit(call, text, keyboard)


@router.callback_query(F.data == "chat:send")
async def send_message(call: CallbackQuery, role: str) -> None:
    """Отправляет подтверждённое объявление."""
    if not can_post(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    draft = _drafts.pop(call.from_user.id, None)
    if draft is None:
        await call.answer("Объявление не найдено — наберите заново.",
                          show_alert=True)
        return
    if draft.expired():
        await call.answer(
            "Прошло слишком много времени — наберите объявление заново.",
            show_alert=True,
        )
        return

    await call.answer()
    try:
        await bot.send_message(draft.chat_id, draft.text)
    except Exception as exc:  # noqa: BLE001
        # Причина нужна человеку, а не только журналу: «не отправилось»
        # без объяснения означает, что он попробует ещё три раза.
        log.warning("Объявление в %s не ушло: %s", draft.chat_id, exc)
        await safe_edit(
            call,
            f"❌ <b>Не отправилось в «{esc(draft.title)}»</b>\n\n"
            f"<code>{esc(str(exc)[:200])}</code>\n\n"
            "Обычные причины: бота выгнали из группы, сняли права "
            "или в ней запрещены сообщения от ботов. Текст не потерян — "
            "наберите заново после того, как поправите права.",
            back_kb_chats(),
        )
        return

    log.info("Суперадминистратор %s написал в чат %s (%d символов)",
             call.from_user.id, draft.chat_id, len(draft.text))
    await safe_edit(
        call,
        f"✅ <b>Отправлено в «{esc(draft.title)}»</b>\n\n"
        "Сообщение опубликовано от имени бота.",
        back_kb_chats(),
    )


# --------------------------------------------------------------------------
#  Своя ссылка приглашения (с 4.9.9.1)
# --------------------------------------------------------------------------
#
# Бот умеет найти ссылку сам: публичное имя, ссылка владельца, своя
# созданная. Но есть случаи, где автоматика не годится и не может годиться:
# закрытый чат со вступлением по заявке, ссылка с ограничением по времени
# или числу переходов, приглашение, которое владелец выдал отдельно.
# Тогда её задают руками — и она становится главной, а не запасной.


@router.callback_query(F.data.startswith("chat:link:"))
async def ask_invite(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    chat_id = int(call.data.rsplit(":", 1)[1])
    row = await repo.chat_get(chat_id)
    if row is None:
        await call.answer("Группа больше не в списке.", show_alert=True)
        return

    title = row.get("title") or str(chat_id)
    current = str(row.get("invite") or "")
    await call.answer()
    await state.set_state(Form.chat_invite)
    await state.update_data(chat_id=chat_id, chat_title=title)

    lines = [f"🔗 <b>Ссылка на «{esc(title)}»</b>", ""]
    if current:
        lines.append(f"Сейчас задана: {esc(current)}")
        lines.append("")
    lines.append(
        "Пришлите ссылку приглашения — она станет кнопкой перехода "
        "в списке чатов и заменит ту, что бот находит сам."
    )
    lines.append("")
    lines.append(
        "<i>Годится ссылка вида https://t.me/… — и публичная, "
        "и приглашение с заявкой на вступление.</i>"
    )
    if current:
        lines.append("<i>«-» уберёт свою ссылку: бот снова будет искать сам.</i>")
    lines.append("<i>/cancel — отменить</i>")

    await safe_edit(call, "\n".join(lines), back_kb_chats())


@router.message(Form.chat_invite)
async def take_invite(message: Message, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await state.clear()
        return

    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    data = await state.get_data()
    chat_id = int(data.get("chat_id") or 0)
    title = str(data.get("chat_title") or chat_id)

    if text == "-":
        await state.clear()
        await repo.chat_set_invite(chat_id, "")
        chatlink.forget(chat_id)
        # Меню пользователей строится из этого списка — обновляем сразу.
        await chatlink.refresh_published()
        await send_html(
            message.chat.id,
            f"✅ Своя ссылка на «{esc(title)}» убрана — бот снова ищет её сам.",
            back_kb_chats(),
        )
        return

    if not chatlink.valid_invite(text):
        # Состояние не сбрасываем: человек исправит и пришлёт снова.
        await send_html(
            message.chat.id,
            "⚠️ Это не похоже на ссылку Telegram. Нужен адрес вида "
            "<code>https://t.me/…</code>.\n\n<i>/cancel — отменить</i>",
        )
        return

    await state.clear()
    if not await repo.chat_set_invite(chat_id, text):
        await send_html(message.chat.id, "Группа больше не в списке.",
                        back_kb_chats())
        return

    # Сбрасываем запомненное: иначе кнопка ещё сутки вела бы по старому
    # адресу, и человек решил бы, что ссылка не сохранилась.
    chatlink.forget(chat_id)
    # Меню пользователей строится из этого списка — обновляем сразу.
    await chatlink.refresh_published()
    log.info("Задана ссылка приглашения для чата %s", chat_id)
    await send_html(
        message.chat.id,
        f"✅ Ссылка на «{esc(title)}» сохранена — она станет кнопкой "
        f"в списке чатов.",
        back_kb_chats(),
    )


# --------------------------------------------------------------------------
#  «Наши чаты» — для всех пользователей (с 4.9.9.2)
# --------------------------------------------------------------------------
#
# Своя ссылка приглашения до 4.9.9.2 была видна только администрации
# в разделе «Чаты», то есть тем, кто в группах и так состоит. Здесь её
# видят все: кнопка в главном меню, по кнопке на каждый чат.
# Показываются только чаты со ссылкой, заданной суперадминистратором, —
# см. chatlink.refresh_published.


@router.callback_query(F.data == "grp:list")
async def list_groups(call: CallbackQuery, user: dict) -> None:
    from .. import i18n

    lang = i18n.language_of(user)
    await call.answer()

    rows: list[list[InlineKeyboardButton]] = []
    for _chat_id, title, link in chatlink.published():
        rows.append([InlineKeyboardButton(text=title or "Чат", url=link)])
    rows.append([InlineKeyboardButton(
        text=i18n.t("menu.home", lang, "🏠 В главное меню"),
        callback_data="menu:main")])

    if len(rows) == 1:
        text = i18n.t("groups.empty", lang, "Пока нет чатов, куда можно вступить.")
    else:
        text = (
            i18n.t("groups.title", lang, "💬 <b>Наши чаты</b>")
            + "\n\n"
            + i18n.t(
                "groups.hint", lang,
                "Нажмите на чат, чтобы перейти в него. В часть чатов "
                "вступают по заявке — её одобряют администраторы чата.",
            )
        )
    await safe_edit(call, text, InlineKeyboardMarkup(inline_keyboard=rows))
