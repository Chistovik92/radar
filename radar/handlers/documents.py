"""Единая точка приёма документов (с 5.9.0.1).

Раньше `F.document` слушали два раздела сразу — источники и cookies, —
и побеждал тот, что раньше в цепочке. Подробности — в `radar/uploads.py`.
Сам разбор остаётся в разделах: они регистрируют обработчик своего вида,
а здесь решается, чей это файл.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from .. import roles, uploads

router = Router(name="documents")


@router.message(F.document)
async def route_document(message: Message, role: str, user: dict) -> None:
    document = message.document
    owner = str(message.from_user.id) if message.from_user else ""
    kind = uploads.classify(
        owner, (document.file_name or "") if document else "",
        superadmin=roles.is_superadmin(role),
    )
    handler = uploads.handler_for(kind)
    if handler is None:
        await message.answer("❌ Этот файл сейчас принять некуда.")
        return
    await handler(message, role, user)


__all__ = ["router"]
