from __future__ import annotations

from collections.abc import Iterable

from app.config import BotConfig
from app.storage import JsonStore


ROLE_TITLES = {
    "owner": "Owner",
    "super_admin": "Super admin",
    "admin": "Admin",
    "viewer": "Viewer",
}

PERMISSIONS = {
    "view_bookings": {"owner", "super_admin", "admin", "viewer"},
    "view_stats": {"owner", "super_admin", "admin", "viewer"},
    "manage_bookings": {"owner", "super_admin", "admin"},
    "manage_clients": {"owner", "super_admin", "admin"},
    "manage_blocked": {"owner", "super_admin", "admin"},
    "manage_reviews": {"owner", "super_admin", "admin"},
    "manage_services": {"owner", "super_admin"},
    "export_bookings": {"owner", "super_admin"},
    "manage_roles": {"owner"},
}


async def get_role(user_id: int | None, store: JsonStore) -> str | None:
    return await store.get_user_role(user_id)


async def is_owner(user_id: int | None, store: JsonStore) -> bool:
    return await store.is_owner(user_id)


async def has_role(user_id: int | None, roles: Iterable[str], store: JsonStore) -> bool:
    role = await get_role(user_id, store)
    return role in set(roles)


async def has_permission(user_id: int | None, permission: str, store: JsonStore) -> bool:
    return await has_role(user_id, PERMISSIONS.get(permission, set()), store)


async def can_view_bookings(user_id: int | None, store: JsonStore) -> bool:
    return await has_permission(user_id, "view_bookings", store)


async def can_manage_bookings(user_id: int | None, store: JsonStore) -> bool:
    return await has_permission(user_id, "manage_bookings", store)


async def can_manage_services(user_id: int | None, store: JsonStore) -> bool:
    return await has_permission(user_id, "manage_services", store)


async def can_manage_roles(user_id: int | None, store: JsonStore) -> bool:
    return await has_permission(user_id, "manage_roles", store)


async def can_export_bookings(user_id: int | None, store: JsonStore) -> bool:
    return await has_permission(user_id, "export_bookings", store)


async def notification_recipients(
    store: JsonStore,
    config: BotConfig,
    roles: Iterable[str] = ("owner", "super_admin"),
) -> set[int]:
    recipients = await store.get_admin_ids_by_roles(roles)
    if config.master_chat_id is not None:
        recipients.add(config.master_chat_id)
    return recipients
