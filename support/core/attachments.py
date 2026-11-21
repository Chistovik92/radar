"""Преобразование вложений Telegram в данные, пригодные для хранения."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Attachment:
    file_id: str
    kind: str
    name: str = ""
    caption: str = ""


def from_message(message: Any) -> Attachment | None:
    caption = getattr(message, "caption", "") or ""
    document = getattr(message, "document", None)
    if document:
        return Attachment(document.file_id, "document", document.file_name or "document", caption)
    photos = getattr(message, "photo", None)
    if photos:
        photo = photos[-1]
        return Attachment(photo.file_id, "photo", "photo.jpg", caption)
    for attribute, kind, extension in (
        ("video", "video", "video.mp4"),
        ("animation", "animation", "animation.mp4"),
        ("audio", "audio", "audio"),
        ("voice", "voice", "voice.ogg"),
        ("video_note", "video_note", "video_note.mp4"),
        ("sticker", "sticker", "sticker"),
    ):
        item = getattr(message, attribute, None)
        if item:
            name = getattr(item, "file_name", "") or extension
            return Attachment(item.file_id, kind, name, caption)
    return None


def describe(attachment: Attachment) -> str:
    label = attachment.name or attachment.kind
    return f"[{attachment.kind}: {label}]" + (f" {attachment.caption}" if attachment.caption else "")
