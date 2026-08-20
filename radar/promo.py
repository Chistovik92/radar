"""Промокоды партнёрских проектов.

Правило одно и жёсткое: **один код на человека на проект**. Повторное
нажатие возвращает уже выданный код, а не новый. Иначе выдача превращается
в бесконечный источник кодов, и партнёр справедливо перестанет их принимать.

Два режима, потому что партнёры работают по-разному:

* один код на всех — партнёр дал одну строку. Сам код у всех одинаковый,
  но дата получения у каждого своя: срок действия считается от неё,
  а не от того дня, когда код придумали;
* свой код каждому — код генерируется здесь. Партнёру отдаётся выгрузка
  «код и дата выдачи», **без наших идентификаторов**: ему нужно проверять
  коды, а не знать, кто из наших людей за каким пришёл.

Выгрузка намеренно не содержит user_id ни в каком виде — в том числе
не выводится из кода. Код случайный, а не производный от идентификатора:
иначе партнёр смог бы сопоставить коды с людьми, а обещание
«без привязки» оказалось бы неправдой.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import secrets as _random
from dataclasses import dataclass
from datetime import datetime, timezone

from . import partners

log = logging.getLogger("radar.promo")

# Без похожих знаков: код диктуют голосом и переписывают руками.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
MAX_ATTEMPTS = 12


@dataclass
class Issued:
    """Выданный код."""

    code: str
    project: str
    issued_at: datetime
    shared: bool = False

    @property
    def date(self) -> str:
        return self.issued_at.strftime("%d.%m.%Y")


def generate(prefix: str = "") -> str:
    """Случайный код. Приставка помогает партнёру отличить свои коды."""
    body = "".join(_random.choice(ALPHABET) for _ in range(CODE_LENGTH))
    clean = "".join(char for char in (prefix or "").upper() if char.isalnum())[:8]
    return f"{clean}-{body}" if clean else body


async def issue(project: partners.Project, user_key: str) -> Issued | None:
    """Выдать код человеку. Повтор возвращает прежний.

    None означает «у проекта нет промокода» — вызывающий не должен был
    предлагать кнопку, но проверить дешевле, чем доверять.
    """
    if not project.has_promo:
        return None

    from .db import repo

    existing = await repo.promo_for_user(project.slug, user_key)
    if existing is not None:
        return Issued(
            code=existing["code"],
            project=project.slug,
            issued_at=existing["issued_at"],
            shared=project.promo_kind == partners.SHARED,
        )

    now = datetime.now(timezone.utc)

    if project.promo_kind == partners.SHARED:
        # Код общий, но запись всё равно личная: дата получения у каждого
        # своя, и именно от неё считается срок.
        code = project.promo_value.strip()
        await repo.save_promo(project.slug, user_key, code, now, shared=True)
        return Issued(code=code, project=project.slug, issued_at=now, shared=True)

    # Уникальный: подбираем свободный код. Совпадение маловероятно, но
    # выдать двум людям один код хуже, чем сделать лишний запрос.
    for _ in range(MAX_ATTEMPTS):
        code = generate(project.promo_prefix)
        if await repo.promo_code_taken(code):
            continue
        await repo.save_promo(project.slug, user_key, code, now, shared=False)
        return Issued(code=code, project=project.slug, issued_at=now)

    log.error("Не удалось подобрать свободный промокод для «%s»", project.slug)
    return None


async def export_for_partner(slug: str) -> list[dict[str, str]]:
    """Выгрузка для партнёра: код и дата выдачи, без наших идентификаторов.

    Это обещание, а не оформление: партнёру нужно проверять коды, а не
    знать, кто из наших людей за каким пришёл.
    """
    from .db import repo

    rows = await repo.promo_list(slug)
    return [
        {"code": row["code"], "issued": row["issued_at"].strftime("%Y-%m-%d")}
        for row in rows
    ]


def render_csv(rows: list[dict[str, str]]) -> str:
    """CSV для передачи партнёру. Заголовок — чтобы файл читался без пояснений."""
    lines = ["code,issued"]
    lines.extend(f"{row['code']},{row['issued']}" for row in rows)
    return "\n".join(lines) + "\n"
