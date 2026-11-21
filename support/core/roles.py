"""Иерархия ролей: user < moderator < admin < superadmin."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

USER = "user"
MODERATOR = "moderator"
ADMIN = "admin"
SUPERADMIN = "superadmin"
ORDER = (USER, MODERATOR, ADMIN, SUPERADMIN)
LEVEL = {role: index for index, role in enumerate(ORDER)}


def level(role: str | None) -> int:
    return LEVEL.get(role or USER, 0)


def at_least(role: str | None, minimum: str) -> bool:
    return level(role) >= level(minimum)


def is_moderator(role: str | None) -> bool:
    return at_least(role, MODERATOR)


def is_admin(role: str | None) -> bool:
    return at_least(role, ADMIN)


def assignable_roles(actor_role: str | None) -> list[str]:
    if actor_role == SUPERADMIN:
        return [USER, MODERATOR, ADMIN]
    if actor_role == ADMIN:
        return [USER, MODERATOR]
    return []


def can_assign(actor_role: str | None, target_role: str | None, new_role: str) -> bool:
    if new_role not in assignable_roles(actor_role) or target_role == SUPERADMIN:
        return False
    return actor_role == SUPERADMIN or level(target_role) < level(actor_role)
