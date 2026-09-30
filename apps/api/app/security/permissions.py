"""Role based access control. Enforced server-side on every endpoint."""

from enum import StrEnum

from cmc_shared.enums import UserRole


class Permission(StrEnum):
    VIEW_DATA = "VIEW_DATA"
    SEND_MESSAGE = "SEND_MESSAGE"
    UPDATE_ORDER = "UPDATE_ORDER"
    MANAGE_TEMPLATES = "MANAGE_TEMPLATES"
    VIEW_OPERATIONS = "VIEW_OPERATIONS"
    TRIGGER_SYNC = "TRIGGER_SYNC"
    MANAGE_ACTIONS = "MANAGE_ACTIONS"
    MANAGE_CONNECTION = "MANAGE_CONNECTION"
    MANAGE_USERS = "MANAGE_USERS"
    MANAGE_SETTINGS = "MANAGE_SETTINGS"
    PURGE_DATA = "PURGE_DATA"


_STAFF = frozenset({Permission.VIEW_DATA, Permission.SEND_MESSAGE, Permission.UPDATE_ORDER})
_MANAGER = _STAFF | {
    Permission.MANAGE_TEMPLATES,
    Permission.VIEW_OPERATIONS,
    Permission.TRIGGER_SYNC,
    Permission.MANAGE_ACTIONS,
}
_ADMIN = frozenset(Permission)

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.STAFF: _STAFF,
    UserRole.MANAGER: frozenset(_MANAGER),
    UserRole.ADMIN: _ADMIN,
}


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def permissions_for(role: UserRole) -> list[Permission]:
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))
