"""Раздел «Партнёрские проекты».

Список проектов автора вместо одной кнопки. Просмотр — всем, правка —
только суперадминистратору.

Сознательные ограничения раздела:

* здесь только собственные проекты автора; сторонней рекламы в «Радаре»
  нет, и раздел не должен становиться местом для неё;
* в оповещения об опасности раздел не попадает — человеку, которому
  сообщают о угрозе, не место читать промо.
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
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .. import features, partners, roles
from ..textutils import esc
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.partners")
router = Router(name="partners")


class AddProject(StatesGroup):
    title = State()
    url = State()
    description = State()


def _list_keyboard(projects, role: str) -> InlineKeyboardMarkup:
    rows = []
    for project in projects:
        # Кнопка-ссылка ведёт наружу сразу: лишний переход через бота
        # ради счётчика раздражал бы больше, чем стоит сама цифра.
        rows.append([InlineKeyboardButton(
            text=f"{project.icon} {project.title}", url=project.url,
        )])
    if roles.is_superadmin(role):
        rows.append([InlineKeyboardButton(
            text="✏️ Управление проектами", callback_data="prj:manage",
        )])
    rows.append([InlineKeyboardButton(
        text="🏠 В главное меню", callback_data="menu:main",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render(role: str) -> tuple[str, InlineKeyboardMarkup]:
    projects = partners.visible_projects(await partners.load())
    if not projects:
        return (
            "🤝 <b>Партнёрские проекты</b>\n\nСписок пока пуст.",
            _list_keyboard([], role),
        )

    lines = ["🤝 <b>Партнёрские проекты</b>", ""]
    for project in projects:
        lines.append(f"{project.icon} <b>{esc(project.title)}</b>")
        if project.description:
            lines.append(esc(project.description))
        lines.append("")
    return "\n".join(lines).strip(), _list_keyboard(projects, role)


@router.message(Command("partner", "vpn", "partners"))
async def cmd_partners(message: Message, role: str) -> None:
    if not features.enabled("partners"):
        # Пока раздел выключен, работает прежняя одиночная кнопка —
        # обновление не должно отнимать у людей то, что уже было.
        from .common import button_promo

        await button_promo(message)
        return
    text, markup = await _render(role)
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.callback_query(F.data == "menu:partners")
async def menu_partners(call: CallbackQuery, role: str) -> None:
    await call.answer()
    text, markup = await _render(role)
    await safe_edit(call, text, markup)


# --- управление -----------------------------------------------------------

def _manage_keyboard(projects) -> InlineKeyboardMarkup:
    rows = []
    for project in projects:
        mark = "👁" if project.visible else "🚫"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {project.title} · {project.clicks}",
                callback_data=f"prj:toggle:{project.slug}",
            ),
            InlineKeyboardButton(text="🗑", callback_data=f"prj:del:{project.slug}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="prj:add")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:partners")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _manage_text() -> str:
    projects = partners.order_projects(await partners.load())
    if not projects:
        return "✏️ <b>Управление проектами</b>\n\nПроектов нет."
    return (
        "✏️ <b>Управление проектами</b>\n\n"
        "Нажатие на проект скрывает или показывает его. "
        "Число рядом — переходы по ссылке.\n"
        f"Всего проектов: <b>{len(projects)}</b> из {partners.MAX_PROJECTS}."
    )


@router.callback_query(F.data == "prj:manage")
async def manage(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    projects = partners.order_projects(await partners.load())
    await safe_edit(call, await _manage_text(), _manage_keyboard(projects))


@router.callback_query(F.data.startswith("prj:toggle:"))
async def toggle(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    slug = call.data.split(":", 2)[2]
    projects = await partners.load()
    for project in projects:
        if project.slug == slug:
            project.visible = not project.visible
            await partners.save(projects)
            await call.answer("Показан" if project.visible else "Скрыт")
            break
    else:
        await call.answer("Проект не найден.", show_alert=True)
    projects = partners.order_projects(await partners.load())
    await safe_edit(call, await _manage_text(), _manage_keyboard(projects))


@router.callback_query(F.data.startswith("prj:del:"))
async def delete(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    slug = call.data.split(":", 2)[2]
    projects = [item for item in await partners.load() if item.slug != slug]
    await partners.save(projects)
    await call.answer("Проект удалён")
    await safe_edit(call, await _manage_text(),
                    _manage_keyboard(partners.order_projects(projects)))


@router.callback_query(F.data == "prj:add")
async def add_start(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    if len(await partners.load()) >= partners.MAX_PROJECTS:
        await call.answer("Достигнут предел числа проектов.", show_alert=True)
        return
    await call.answer()
    await state.set_state(AddProject.title)
    await safe_edit(
        call,
        "Название проекта — можно со значком в начале, например "
        "<code>🐙 HydraSite</code>.\n\n/cancel — отмена.",
        back_kb(),
    )


@router.message(AddProject.title)
async def add_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым.")
        return
    await state.update_data(title=title[:partners.MAX_TITLE])
    await state.set_state(AddProject.url)
    await message.answer("Ссылка на проект (http, https или tg).")


@router.message(AddProject.url)
async def add_url(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not partners.valid_url(url):
        await message.answer(
            "Не похоже на ссылку. Нужен полный адрес: <code>https://…</code> "
            "или <code>tg://…</code>"
        )
        return
    await state.update_data(url=url)
    await state.set_state(AddProject.description)
    await message.answer("Короткое описание. Или «-», чтобы пропустить.")


@router.message(AddProject.description)
async def add_description(message: Message, state: FSMContext, role: str) -> None:
    data = await state.get_data()
    await state.clear()

    description = (message.text or "").strip()
    if description == "-":
        description = ""

    title = data.get("title", "")
    icon = "🔗"
    parts = title.split(maxsplit=1)
    if len(parts) == 2 and not parts[0].isalnum() and len(parts[0]) <= 4:
        icon, title = parts[0], parts[1]

    projects = await partners.load()
    slug = _make_slug(title, {item.slug for item in projects})
    projects.append(partners.Project(
        slug=slug, title=title, url=data.get("url", ""),
        description=description[:partners.MAX_DESCRIPTION], icon=icon,
        order=100 + len(projects),
    ))
    await partners.save(projects)
    await message.answer(
        f"✅ Проект «{esc(title)}» добавлен.",
        reply_markup=_manage_keyboard(partners.order_projects(projects)),
    )


def _make_slug(title: str, taken: set[str]) -> str:
    """Короткое имя из названия. При совпадении добавляется номер."""
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    result = []
    for char in title.lower():
        if char in translit:
            result.append(translit[char])
        elif char.isalnum():
            result.append(char)
        elif result and result[-1] != "-":
            result.append("-")
    slug = "".join(result).strip("-")[:32] or "project"
    if len(slug) < 2:
        slug = f"{slug}-1"
    base = slug
    number = 2
    while slug in taken:
        slug = f"{base[:28]}-{number}"
        number += 1
    return slug
