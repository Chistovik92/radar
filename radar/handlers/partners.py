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

from .. import features, i18n, partners, promo, roles
from ..textutils import esc
from ..tg import back_kb, safe_edit

log = logging.getLogger("radar.handlers.partners")
router = Router(name="partners")


class AddProject(StatesGroup):
    title = State()
    url = State()
    description = State()


def _list_keyboard(projects, lang: str = i18n.DEFAULT) -> InlineKeyboardMarkup:
    rows = []
    for project in projects:
        # Кнопка-ссылка ведёт наружу сразу: лишний переход через бота
        # ради счётчика раздражал бы больше, чем стоит сама цифра.
        rows.append([InlineKeyboardButton(
            text=f"{project.icon} {project.title}", url=project.url,
        )])
        if features.enabled("promo_codes") and project.has_promo:
            rows.append([InlineKeyboardButton(
                text=i18n.t("partners.promo", lang, "🎁 Получить промокод"),
                callback_data=f"prj:promo:{project.slug}",
            )])
    # Кнопки управления здесь нет намеренно: правка разделов собрана
    # в одном месте — в меню «Управление». Раздел для читателя остаётся
    # только списком проектов.
    rows.append([InlineKeyboardButton(
        text=i18n.t("menu.home", lang, "🏠 В главное меню"),
        callback_data="menu:main",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render(lang: str = i18n.DEFAULT) -> tuple[str, InlineKeyboardMarkup]:
    projects = partners.visible_projects(await partners.load())
    title = i18n.t("menu.partners", lang, "🤝 Партнёрские проекты")

    if not projects:
        empty = i18n.t("partners.empty", lang, "Список пока пуст.")
        return f"<b>{title}</b>\n\n{empty}", _list_keyboard([], lang)

    lines = [f"<b>{title}</b>", ""]
    for project in projects:
        lines.append(f"{project.icon} <b>{esc(project.title)}</b>")
        if project.description:
            # Описание пишет суперадминистратор по-русски: для английского
            # интерфейса переводим на лету, с кэшем. Не переведётся —
            # покажем как есть, это лучше пустого места.
            lines.append(esc(await i18n.translate(project.description, lang)))
        lines.append("")
    return "\n".join(lines).strip(), _list_keyboard(projects, lang)


@router.message(Command("partner", "vpn", "partners"))
async def cmd_partners(message: Message, user: dict) -> None:
    if not features.enabled("partners"):
        # Пока раздел выключен, работает прежняя одиночная кнопка —
        # обновление не должно отнимать у людей то, что уже было.
        from .common import button_promo

        await button_promo(message)
        return
    text, markup = await _render(i18n.language_of(user))
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.callback_query(F.data == "menu:partners")
async def menu_partners(call: CallbackQuery, user: dict) -> None:
    await call.answer()
    text, markup = await _render(i18n.language_of(user))
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
    if features.enabled("promo_codes"):
        rows.append([InlineKeyboardButton(
            text="🎁 Промокоды", callback_data="prm:list",
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:manage")])
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


# --- выдача промокодов ----------------------------------------------------

@router.callback_query(F.data.startswith("prj:promo:"))
async def give_promo(call: CallbackQuery, user: dict) -> None:
    """Выдать промокод. Повторное нажатие возвращает тот же код."""
    if not features.enabled("promo_codes"):
        await call.answer("Промокоды сейчас не выдаются.", show_alert=True)
        return

    slug = call.data.split(":", 2)[2]
    project = await partners.by_slug(slug)
    if project is None or not project.has_promo:
        await call.answer("У этого проекта нет промокода.", show_alert=True)
        return

    try:
        issued = await promo.issue(project, str(call.from_user.id))
    except Exception:  # noqa: BLE001
        log.exception("Выдача промокода не удалась")
        await call.answer("Не удалось выдать код, попробуйте позже.",
                          show_alert=True)
        return

    if issued is None:
        await call.answer("Код выдать не получилось.", show_alert=True)
        return

    await call.answer()
    lang = i18n.language_of(user)
    lines = [
        f"🎁 <b>Промокод — {esc(project.title)}</b>",
        "",
        f"<code>{esc(issued.code)}</code>",
        "",
        f"Выдан: <b>{issued.date}</b>",
    ]
    if project.promo_terms:
        lines.extend(["", esc(await i18n.translate(project.promo_terms, lang))])
    lines.extend([
        "",
        "<i>Код закреплён за вами: повторное нажатие покажет его же.</i>",
    ])
    await call.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{project.icon} {project.title}",
                                  url=project.url)],
            [InlineKeyboardButton(text="◀️ К проектам",
                                  callback_data="menu:partners")],
        ]),
    )


# --- настройка промокодов -------------------------------------------------

class PromoSetup(StatesGroup):
    value = State()
    terms = State()


def _promo_keyboard(projects) -> InlineKeyboardMarkup:
    rows = []
    for project in projects:
        mark = "🎁" if project.has_promo else "➖"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {project.title} — {partners.KIND_TITLES[project.promo_kind]}",
            callback_data=f"prm:pick:{project.slug}",
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="prj:manage")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "prm:list")
async def promo_list(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    projects = partners.order_projects(await partners.load())
    await safe_edit(
        call,
        "🎁 <b>Промокоды</b>\n\nВыберите проект, чтобы настроить выдачу.",
        _promo_keyboard(projects),
    )


def _project_promo_keyboard(project) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="➖ Нет", callback_data=f"prm:kind:{project.slug}:none"),
        InlineKeyboardButton(text="1️⃣ Общий", callback_data=f"prm:kind:{project.slug}:shared"),
        InlineKeyboardButton(text="🎲 Свой", callback_data=f"prm:kind:{project.slug}:unique"),
    ]]
    if project.promo_kind == partners.SHARED:
        rows.append([InlineKeyboardButton(
            text="✏️ Задать код", callback_data=f"prm:value:{project.slug}")])
    if project.promo_kind == partners.UNIQUE:
        rows.append([InlineKeyboardButton(
            text="✏️ Приставка кода", callback_data=f"prm:value:{project.slug}")])
    if project.has_promo:
        rows.append([InlineKeyboardButton(
            text="📄 Условия", callback_data=f"prm:terms:{project.slug}")])
        rows.append([InlineKeyboardButton(
            text="📥 Выгрузка для партнёра", callback_data=f"prm:export:{project.slug}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="prm:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _project_promo_text(project) -> str:
    from ..db import repo

    try:
        issued = await repo.promo_count(project.slug)
    except Exception:  # noqa: BLE001
        issued = 0

    lines = [
        f"🎁 <b>{esc(project.title)}</b>",
        "",
        f"Режим: <b>{partners.KIND_TITLES[project.promo_kind]}</b>",
    ]
    if project.promo_kind == partners.SHARED:
        lines.append(f"Код: <code>{esc(project.promo_value or '— не задан —')}</code>")
        lines.append(
            "<i>Код у всех одинаковый, но дата получения у каждого своя — "
            "срок считается от неё.</i>"
        )
    elif project.promo_kind == partners.UNIQUE:
        lines.append(f"Приставка: <code>{esc(project.promo_prefix or '— нет —')}</code>")
        lines.append(
            "<i>Каждому выдаётся свой код. Партнёру отдаётся выгрузка "
            "«код и дата» — без наших идентификаторов.</i>"
        )
    if project.promo_terms:
        lines.extend(["", "Условия:", esc(project.promo_terms)])
    lines.extend(["", f"Выдано кодов: <b>{issued}</b>"])
    return "\n".join(lines)


@router.callback_query(F.data.startswith("prm:pick:"))
async def promo_pick(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    project = await partners.by_slug(call.data.split(":", 2)[2])
    if project is None:
        await call.answer("Проект не найден.", show_alert=True)
        return
    await call.answer()
    await safe_edit(call, await _project_promo_text(project),
                    _project_promo_keyboard(project))


@router.callback_query(F.data.startswith("prm:kind:"))
async def promo_kind(call: CallbackQuery, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    _, _, slug, kind = call.data.split(":", 3)
    projects = await partners.load()
    for project in projects:
        if project.slug == slug:
            project.promo_kind = kind if kind in partners.KINDS else partners.NONE
            await partners.save(projects)
            await call.answer(partners.KIND_TITLES[project.promo_kind])
            await safe_edit(call, await _project_promo_text(project),
                            _project_promo_keyboard(project))
            return
    await call.answer("Проект не найден.", show_alert=True)


@router.callback_query(F.data.startswith("prm:value:"))
async def promo_value_start(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    slug = call.data.split(":", 2)[2]
    project = await partners.by_slug(slug)
    if project is None:
        await call.answer("Проект не найден.", show_alert=True)
        return
    await call.answer()
    await state.update_data(slug=slug)
    await state.set_state(PromoSetup.value)
    if project.promo_kind == partners.SHARED:
        prompt = ("Пришлите код, который партнёр выдал для всех. "
                  "Например: <code>RADAR2026</code>")
    else:
        prompt = ("Пришлите приставку для генерируемых кодов — по ней партнёр "
                  "отличит наши коды от чужих. Например: <code>HYDRA</code>\n\n"
                  "«-» — без приставки.")
    await safe_edit(call, prompt + "\n\n/cancel — отмена.", back_kb())


@router.message(PromoSetup.value)
async def promo_value_set(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    value = (message.text or "").strip()

    projects = await partners.load()
    for project in projects:
        if project.slug != data.get("slug"):
            continue
        if project.promo_kind == partners.SHARED:
            if not value or value == "-":
                await message.answer("Код не может быть пустым.")
                return
            project.promo_value = value[:64]
        else:
            project.promo_prefix = "" if value == "-" else "".join(
                char for char in value.upper() if char.isalnum()
            )[:12]
        await partners.save(projects)
        await message.answer(
            "✅ Сохранено.",
            reply_markup=_project_promo_keyboard(project),
        )
        return
    await message.answer("Проект не найден.")


@router.callback_query(F.data.startswith("prm:terms:"))
async def promo_terms_start(call: CallbackQuery, state: FSMContext, role: str) -> None:
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return
    await call.answer()
    await state.update_data(slug=call.data.split(":", 2)[2])
    await state.set_state(PromoSetup.terms)
    await safe_edit(
        call,
        "Пришлите описание промокода: что даёт, до какого срока, "
        "как применить. Этот текст увидит человек вместе с кодом.\n\n"
        "«-» — очистить. /cancel — отмена.",
        back_kb(),
    )


@router.message(PromoSetup.terms)
async def promo_terms_set(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    text = (message.text or "").strip()

    projects = await partners.load()
    for project in projects:
        if project.slug != data.get("slug"):
            continue
        project.promo_terms = "" if text == "-" else text[:partners.MAX_TERMS]
        await partners.save(projects)
        await message.answer("✅ Условия сохранены.",
                             reply_markup=_project_promo_keyboard(project))
        return
    await message.answer("Проект не найден.")


@router.callback_query(F.data.startswith("prm:export:"))
async def promo_export(call: CallbackQuery, role: str) -> None:
    """Выгрузка кодов партнёру — только код и дата, без наших идентификаторов."""
    if not roles.is_superadmin(role):
        await call.answer("Только для суперадминистратора.", show_alert=True)
        return

    slug = call.data.split(":", 2)[2]
    try:
        rows = await promo.export_for_partner(slug)
    except Exception:  # noqa: BLE001
        log.exception("Выгрузка промокодов не удалась")
        await call.answer("Выгрузка не удалась — смотрите журнал.", show_alert=True)
        return

    if not rows:
        await call.answer("Кодов пока не выдано.", show_alert=True)
        return

    await call.answer()
    from aiogram.types import BufferedInputFile

    payload = promo.render_csv(rows).encode("utf-8")
    await call.message.answer_document(
        BufferedInputFile(payload, filename=f"promo-{slug}.csv"),
        caption=(
            f"📥 Коды проекта «{esc(slug)}»: {len(rows)}\n\n"
            "<i>Только код и дата выдачи. Идентификаторов пользователей "
            "в файле нет и по коду они не восстанавливаются.</i>"
        ),
    )
