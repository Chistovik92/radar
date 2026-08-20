"""Партнёрские проекты.

Раздел со списком проектов автора вместо одной кнопки. Проекты хранятся
данными, а не в коде: суперадминистратор добавляет, скрывает и меняет
порядок из бота, без правки исходников и пересборки образа.

Границы, заданные в дорожной карте и здесь соблюдаемые:

* реклама только собственных проектов автора — сторонних объявлений
  в «Радаре» нет и не планируется;
* оповещения об опасности не место для промо: раздел живёт в меню,
  а внутрь тревог не попадает (`PROMO_IN_ALERTS` по умолчанию выключен).

Первый проект — HydraSite — переносится из настроек `.env`, чтобы
существующие установки не потеряли кнопку при обновлении.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from . import config

log = logging.getLogger("radar.partners")

MAX_PROJECTS = 20
MAX_TITLE = 48
MAX_DESCRIPTION = 300
MAX_TERMS = 600

# Режимы промокода
NONE = "none"
SHARED = "shared"
UNIQUE = "unique"
KINDS = (NONE, SHARED, UNIQUE)
KIND_TITLES = {
    NONE: "нет промокода",
    SHARED: "один код на всех",
    UNIQUE: "свой код каждому",
}

# Ссылка ведёт наружу, и по ней пойдут люди, которым бот сообщает
# об опасности. Схемы кроме http(s) и telegram-ссылок не принимаем.
ALLOWED_SCHEMES = ("http", "https", "tg")

_SLUG_RE = re.compile(r"^[a-z0-9-]{2,32}$")


@dataclass
class Project:
    """Один партнёрский проект."""

    slug: str
    title: str
    url: str
    description: str = ""
    icon: str = "🔗"
    order: int = 100
    visible: bool = True
    clicks: int = 0

    # --- промокоды (с 4.7) ---
    # Три режима. NONE — у проекта промокода нет.
    # SHARED — код один на всех (партнёр раздал одну строку); закрепляем
    #   за человеком дату получения, потому что срок считается от неё.
    # UNIQUE — код генерируется каждому свой; партнёру отдаётся выгрузка
    #   кодов с датами, без наших идентификаторов.
    promo_kind: str = "none"
    promo_value: str = ""            # для SHARED — сама строка кода
    promo_prefix: str = ""           # для UNIQUE — приставка вида HYDRA
    promo_terms: str = ""            # условия, пишет суперадминистратор

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "title": self.title, "url": self.url,
            "description": self.description, "icon": self.icon,
            "order": self.order, "visible": self.visible, "clicks": self.clicks,
            "promo_kind": self.promo_kind, "promo_value": self.promo_value,
            "promo_prefix": self.promo_prefix, "promo_terms": self.promo_terms,
        }

    @property
    def has_promo(self) -> bool:
        if self.promo_kind == SHARED:
            return bool(self.promo_value)
        return self.promo_kind == UNIQUE

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "Project | None":
        """Разбор записи. None — если запись негодная.

        Мусор в данных не должен ронять раздел целиком: одна битая запись
        просто выпадает из списка, остальные показываются.
        """
        if not isinstance(raw, dict):
            return None
        slug = str(raw.get("slug") or "").strip().lower()
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not valid_slug(slug) or not title or not valid_url(url):
            return None
        return cls(
            slug=slug,
            title=title[:MAX_TITLE],
            url=url,
            description=str(raw.get("description") or "")[:MAX_DESCRIPTION],
            icon=str(raw.get("icon") or "🔗")[:4],
            order=_as_int(raw.get("order"), 100),
            visible=bool(raw.get("visible", True)),
            clicks=max(0, _as_int(raw.get("clicks"), 0)),
            promo_kind=_as_kind(raw.get("promo_kind")),
            promo_value=str(raw.get("promo_value") or "")[:64].strip(),
            promo_prefix=str(raw.get("promo_prefix") or "")[:12].strip().upper(),
            promo_terms=str(raw.get("promo_terms") or "")[:MAX_TERMS],
        )


def _as_kind(value: Any) -> str:
    kind = str(value or NONE).strip().lower()
    return kind if kind in KINDS else NONE


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or ""))


def valid_url(url: str) -> bool:
    if not url or len(url) > 500:
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False
    # tg://resolve?domain=… не имеет netloc в привычном смысле
    return bool(parsed.netloc or parsed.path)


def order_projects(projects: list[Project]) -> list[Project]:
    """Порядок показа: по полю order, при равенстве — по названию."""
    return sorted(projects, key=lambda item: (item.order, item.title.lower()))


def visible_projects(projects: list[Project]) -> list[Project]:
    return [item for item in order_projects(projects) if item.visible]


def parse_all(raw: Any) -> list[Project]:
    """Список проектов из хранилища, с отбрасыванием негодных записей."""
    if not isinstance(raw, list):
        return []
    result: list[Project] = []
    seen: set[str] = set()
    for item in raw[:MAX_PROJECTS * 2]:
        project = Project.from_dict(item)
        if project is None:
            log.debug("Пропущена негодная запись партнёрского проекта")
            continue
        if project.slug in seen:
            continue
        seen.add(project.slug)
        result.append(project)
    return result[:MAX_PROJECTS]


def default_projects() -> list[Project]:
    """Проект из настроек .env — чтобы обновление не потеряло кнопку.

    До 4.6.5 партнёрский проект был один и жил в PROMO_*. При первом
    открытии раздела он переносится в список как обычная запись, дальше
    правится из бота наравне с остальными.
    """
    if not config.PROMO_ENABLED or not config.PROMO_URL:
        return []
    title = config.PROMO_TITLE or "Партнёрский проект"
    icon = "🔗"
    # В PROMO_TITLE обычно уже есть значок — отделяем его, чтобы не
    # дублировать в списке.
    parts = title.split(maxsplit=1)
    if len(parts) == 2 and not parts[0].isalnum() and len(parts[0]) <= 4:
        icon, title = parts[0], parts[1]
    # PROMO_TEXT писался под прямую отправку и содержит HTML-разметку.
    # В списке он выводится как обычный текст с экранированием, поэтому
    # теги надо снять здесь — иначе человек увидит «<b>HydraSite</b>».
    # Заодно убираем первую строку, если она повторяет название: в списке
    # название уже стоит заголовком, и повтор выглядит ошибкой.
    from .textutils import strip_tags

    description = strip_tags(config.PROMO_TEXT or "").strip()
    lines = [line for line in description.split("\n")]
    while lines and _echoes_title(lines[0], title, icon):
        lines.pop(0)
    description = "\n".join(lines).strip()

    return [Project(
        slug="hydrasite",
        title=title[:MAX_TITLE],
        url=config.PROMO_URL,
        description=description[:MAX_DESCRIPTION],
        icon=icon,
        order=10,
    )]


def _echoes_title(line: str, title: str, icon: str) -> bool:
    """Повторяет ли строка описания название проекта."""
    cleaned = line.replace(icon, "").strip()
    if not cleaned:
        return True
    return cleaned.lower().startswith(title.lower())


# --------------------------------------------------------------------------
#  Хранение
# --------------------------------------------------------------------------
#
# Проекты лежат в таблице meta одной записью, а не отдельной таблицей:
# их единицы, они меняются вручную и никогда не участвуют в выборках.
# Отдельная таблица с миграцией дала бы ту же функциональность дороже.

META_KEY = "partners"

_cache: list[Project] | None = None


async def load() -> list[Project]:
    """Список проектов. При первом обращении переносит проект из .env."""
    global _cache
    if _cache is not None:
        return _cache

    from .db import repo

    try:
        raw = await repo.get_meta(META_KEY, None)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось прочитать партнёрские проекты")
        return default_projects()

    if raw is None:
        _cache = default_projects()
        if _cache:
            await save(_cache)
        return _cache

    _cache = parse_all(raw)
    return _cache


async def save(projects: list[Project]) -> None:
    global _cache
    from .db import repo

    ordered = order_projects(projects)[:MAX_PROJECTS]
    await repo.set_meta(META_KEY, [item.to_dict() for item in ordered])
    _cache = ordered


def forget() -> None:
    """Сбросить кэш — нужен тестам и после правки извне."""
    global _cache
    _cache = None


async def by_slug(slug: str) -> Project | None:
    for project in await load():
        if project.slug == slug:
            return project
    return None


async def remember_click(slug: str) -> None:
    """Считает переход. Ошибка счётчика не должна мешать переходу."""
    projects = await load()
    for project in projects:
        if project.slug == slug:
            project.clicks += 1
            try:
                await save(projects)
            except Exception:  # noqa: BLE001
                log.debug("Счётчик переходов не сохранился")
            return
