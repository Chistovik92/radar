"""Роли и права доступа.

Иерархия: superadmin (3) > admin (2) > moderator (1) > user (0).

* Суперадминистратор может всё, включая назначение администраторов.
* Администратор назначает модераторов и обычных пользователей, удаляет
  пользователей уровнем ниже себя.
* Модератор редактирует локации и настройки оповещений пользователей,
  модерирует источники, пользуется ИИ-ассистентом, но никого не назначает
  и не удаляет.
* Пользователь управляет только собой.
"""

from __future__ import annotations

USER = "user"
MODERATOR = "moderator"
ADMIN = "admin"
SUPERADMIN = "superadmin"

ORDER = (USER, MODERATOR, ADMIN, SUPERADMIN)
LEVEL = {role: index for index, role in enumerate(ORDER)}

TITLES = {
    USER: "👤 Пользователь",
    MODERATOR: "🛡 Модератор",
    ADMIN: "👑 Администратор",
    SUPERADMIN: "⭐️ Суперадминистратор",
}


def level(role: str | None) -> int:
    return LEVEL.get(role or USER, 0)


def title(role: str | None) -> str:
    return TITLES.get(role or USER, TITLES[USER])


def at_least(role: str | None, minimum: str) -> bool:
    return level(role) >= level(minimum)


def is_moderator(role: str | None) -> bool:
    return at_least(role, MODERATOR)


def is_admin(role: str | None) -> bool:
    return at_least(role, ADMIN)


def is_superadmin(role: str | None) -> bool:
    return role == SUPERADMIN


def assignable_roles(actor_role: str | None) -> list[str]:
    """Какие роли актор вправе выдавать."""
    if is_superadmin(actor_role):
        return [USER, MODERATOR, ADMIN]
    if is_admin(actor_role):
        return [USER, MODERATOR]
    return []


def can_assign(actor_role: str | None, target_role: str | None, new_role: str) -> bool:
    """Может ли актор сменить роль target_role на new_role."""
    if new_role not in assignable_roles(actor_role):
        return False
    if target_role == SUPERADMIN:
        return False
    if is_superadmin(actor_role):
        return True
    # админ не трогает равных и старших
    return level(target_role) < level(actor_role)


def can_delete_user(actor_role: str | None, target_role: str | None) -> bool:
    """Удаление пользователей — от администратора и выше."""
    if not is_admin(actor_role):
        return False
    if target_role == SUPERADMIN:
        return False
    if is_superadmin(actor_role):
        return True
    return level(target_role) < level(actor_role)


def can_edit_user(actor_role: str | None, target_role: str | None) -> bool:
    """Правка локаций и настроек оповещений — от модератора и выше."""
    if not is_moderator(actor_role):
        return False
    if target_role == SUPERADMIN:
        return is_superadmin(actor_role)
    if is_superadmin(actor_role):
        return True
    return level(target_role) < level(actor_role)


def can_moderate_sources(actor_role: str | None) -> bool:
    return is_moderator(actor_role)


def can_use_assistant(actor_role: str | None) -> bool:
    return is_moderator(actor_role)
