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

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "title": self.title, "url": self.url,
            "description": self.description, "icon": self.icon,
            "order": self.order, "visible": self.visible, "clicks": self.clicks,
        }

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
        )


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
    return [Project(
        slug="hydrasite",
        title=title[:MAX_TITLE],
        url=config.PROMO_URL,
        description=(config.PROMO_TEXT or "")[:MAX_DESCRIPTION],
        icon=icon,
        order=10,
    )]
