"""Экстренная кнопка: отправка геопозиции доверенному контакту.

Устройство и ограничение платформы
----------------------------------
Telegram не позволяет боту написать первым тому, кто с ним не общался.
Поэтому доверенный контакт не может быть просто «номером из записной книжки»:
он должен один раз открыть бота по пригласительной ссылке. До этого момента
контакт числится неподтверждённым, и при тревоге бот честно об этом
предупреждает, а сообщение уходит запасному адресату — администраторам.

Что отправляется
----------------
Имя и ссылка на отправителя, координаты, разобранный адрес, время и карта.
Координаты дублируются отдельным сообщением-геопозицией: его удобно открыть
в навигаторе одним касанием.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .textutils import esc

log = logging.getLogger("radar.sos")

# Сколько минут повторять тревогу, пока не нажато «Я в порядке»
REPEAT_MINUTES = 10
MAX_REPEATS = 6
MAX_CONTACTS = 3


@dataclass
class Contact:
    """Доверенный контакт пользователя."""

    key: str                 # ключ рабочего набора: telegram-id или max:<id>
    title: str               # как показывать в списке
    confirmed: bool = False  # нажал ли контакт «Старт» у бота
    invite: str = ""         # одноразовый код приглашения
    added: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Contact":
        return cls(
            key=str(data.get("key") or ""),
            title=str(data.get("title") or data.get("key") or "контакт"),
            confirmed=bool(data.get("confirmed")),
            invite=str(data.get("invite") or ""),
            added=int(data.get("added") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "confirmed": self.confirmed,
            "invite": self.invite,
            "added": self.added,
        }


def contacts_of(user: dict[str, Any]) -> list[Contact]:
    return [Contact.from_dict(item) for item in (user.get("sos_contacts") or [])]


def store_contacts(user: dict[str, Any], contacts: list[Contact]) -> None:
    user["sos_contacts"] = [item.to_dict() for item in contacts]


def add_contact(user: dict[str, Any], key: str, title: str) -> tuple[Contact | None, str]:
    """Добавляет контакт. Возвращает (контакт, сообщение об ошибке)."""
    contacts = contacts_of(user)
    if len(contacts) >= MAX_CONTACTS:
        return None, f"Больше {MAX_CONTACTS} контактов не поддерживается."
    if any(item.key == key for item in contacts):
        return None, "Такой контакт уже добавлен."

    contact = Contact(
        key=key,
        title=title or key,
        confirmed=False,
        invite=secrets.token_urlsafe(9),
        added=int(time.time()),
    )
    contacts.append(contact)
    store_contacts(user, contacts)
    return contact, ""


def remove_contact(user: dict[str, Any], key: str) -> bool:
    contacts = contacts_of(user)
    kept = [item for item in contacts if item.key != key]
    if len(kept) == len(contacts):
        return False
    store_contacts(user, kept)
    return True


def confirm_by_invite(user: dict[str, Any], invite: str, key: str) -> Contact | None:
    """Отмечает контакт подтверждённым, когда он открыл бота по ссылке."""
    contacts = contacts_of(user)
    for contact in contacts:
        if contact.invite and contact.invite == invite:
            contact.confirmed = True
            contact.key = key or contact.key
            store_contacts(user, contacts)
            return contact
    return None


def find_by_invite(users: dict[str, dict[str, Any]], invite: str) -> tuple[str, Contact] | None:
    """Ищет, кому принадлежит пригласительный код."""
    for owner, data in users.items():
        for contact in contacts_of(data):
            if contact.invite and contact.invite == invite:
                return owner, contact
    return None


def confirmed_contacts(user: dict[str, Any]) -> list[Contact]:
    return [item for item in contacts_of(user) if item.confirmed]


# --------------------------------------------------------------------------
#  Сообщения
# --------------------------------------------------------------------------

def map_link(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat:.6f},{lon:.6f}"


def build_alert(
    sender_name: str,
    sender_link: str,
    lat: float,
    lon: float,
    address: str = "",
    note: str = "",
    repeat: int = 0,
) -> str:
    """Сообщение доверенному контакту."""
    lines = [
        "🆘 <b>ПРОСЬБА О ПОМОЩИ</b>",
        "",
        f"<b>{esc(sender_name)}</b> нажал кнопку SOS в системе «Радар»"
        + (f" — {esc(sender_link)}" if sender_link else ""),
    ]
    if note:
        lines.append(f"\n💬 <i>{esc(note)}</i>")

    lines.append("")
    lines.append(f"📍 <b>Координаты:</b> <code>{lat:.6f}, {lon:.6f}</code>")
    if address:
        lines.append(f"🏠 <b>Адрес:</b> {esc(address)}")
    lines.append(f"🕒 <b>Время:</b> {datetime.now():%H:%M:%S, %d.%m.%Y}")
    lines.append("")
    lines.append(f'🗺 <a href="{map_link(lat, lon)}">Открыть на карте</a>')

    if repeat:
        lines.append("")
        lines.append(
            f"<i>Повтор {repeat}: отправитель ещё не отметил, что с ним всё в порядке.</i>"
        )

    lines.append("")
    lines.append("<b>Если человек в опасности — звоните 112.</b>")
    return "\n".join(lines)


def build_receipt(contacts: list[Contact], failed: list[str]) -> str:
    """Подтверждение отправителю: кому ушло, кому нет."""
    lines = ["🆘 <b>Сигнал отправлен</b>", ""]
    delivered = [item for item in contacts if item.title not in failed]
    if delivered:
        lines.append("Получили:")
        lines += [f"• {esc(item.title)}" for item in delivered]
    if failed:
        lines.append("")
        lines.append("⚠️ Не доставлено:")
        lines += [f"• {esc(name)}" for name in failed]
        lines.append("<i>Контакт не открывал бота или заблокировал его.</i>")

    lines.append("")
    lines.append(
        f"Сигнал будет повторяться каждые {REPEAT_MINUTES} мин "
        f"(до {MAX_REPEATS} раз), пока вы не нажмёте «Я в порядке»."
    )
    lines.append("")
    lines.append("<b>При угрозе жизни звоните 112 — бот не заменяет экстренные службы.</b>")
    return "\n".join(lines)


def build_invite_text(owner_name: str, bot_username: str, invite: str) -> str:
    """Текст приглашения, который отправитель пересылает контакту."""
    return (
        "🆘 <b>Приглашение стать доверенным контактом</b>\n\n"
        f"{esc(owner_name)} указал вас как человека, которому придёт сигнал "
        "о помощи с координатами, если он нажмёт кнопку SOS.\n\n"
        "Чтобы сигнал доходил, откройте бота по ссылке и нажмите «Старт» — "
        "иначе Telegram не позволит боту написать вам первым:\n"
        f"https://t.me/{bot_username}?start=sos_{invite}\n\n"
        "<i>Никаких других сообщений бот присылать не будет.</i>"
    )


def build_cancel_notice(sender_name: str) -> str:
    return (
        f"✅ <b>Отбой</b>\n\n{esc(sender_name)} отметил, что всё в порядке. "
        "Повторные сигналы прекращены."
    )


# --------------------------------------------------------------------------
#  Активные тревоги
# --------------------------------------------------------------------------

@dataclass
class ActiveAlert:
    owner: str
    lat: float
    lon: float
    address: str
    note: str
    started: float
    repeats: int = 0
    last_sent: float = 0.0

    def due(self, now: float | None = None) -> bool:
        moment = now if now is not None else time.time()
        if self.repeats >= MAX_REPEATS:
            return False
        return moment - self.last_sent >= REPEAT_MINUTES * 60


_active: dict[str, ActiveAlert] = {}


def start_alert(owner: str, lat: float, lon: float, address: str, note: str) -> ActiveAlert:
    alert = ActiveAlert(
        owner=owner, lat=lat, lon=lon, address=address, note=note,
        started=time.time(), last_sent=time.time(),
    )
    _active[owner] = alert
    return alert


def stop_alert(owner: str) -> bool:
    return _active.pop(owner, None) is not None


def active_alert(owner: str) -> ActiveAlert | None:
    return _active.get(owner)


def due_alerts(now: float | None = None) -> list[ActiveAlert]:
    return [alert for alert in _active.values() if alert.due(now)]


def active_count() -> int:
    return len(_active)
