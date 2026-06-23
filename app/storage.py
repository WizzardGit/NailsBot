from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.schedule import (
    DEFAULT_SERVICE_DURATION_MIN,
    TIME_SLOTS,
    calculate_end_time,
    fits_working_day,
    intervals_overlap,
    parse_time_to_minutes,
)


VALID_ROLES = {"owner", "super_admin", "admin", "viewer"}
MANAGEMENT_ROLES = {"owner", "super_admin", "admin", "viewer"}

DEFAULT_FILES: dict[str, Any] = {
    "admins.json": {"users": []},
    "bookings.json": [],
    "leads.json": [],
    "blocked_dates.json": [],
    "blocked_slots.json": [],
    "clients.json": [],
}


class JsonStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self._lock = asyncio.Lock()

    async def ensure_files(
        self,
        owner_id: int | None = None,
        master_chat_id: int | None = None,
        admin_ids: Iterable[int] | None = None,
    ) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            for name, default in DEFAULT_FILES.items():
                path = self._path(name)
                if not path.exists():
                    self._write(path, default)

            self._bootstrap_admins_locked(owner_id, master_chat_id, set(admin_ids or set()))
            self._rebuild_clients_locked()

    async def load(self, name: str, default: Any) -> Any:
        async with self._lock:
            path = self._path(name)
            if not path.exists():
                return default
            payload = self._read(path, default)
            if name == "services.json":
                return self._normalize_services(payload)
            if name == "bookings.json":
                services_by_id = {item["id"]: item for item in self._normalize_services(self._read(self._path("services.json"), []))}
                return [self._normalize_booking(item, services_by_id) for item in payload if isinstance(item, dict)]
            if name == "admins.json":
                return self._normalize_admins(payload)
            if name == "blocked_slots.json":
                return self._normalize_blocked_slots(payload)
            if name == "clients.json":
                return self._normalize_clients(payload)
            return payload

    async def save(self, name: str, payload: Any) -> None:
        async with self._lock:
            self._write(self._path(name), payload)

    async def append(self, name: str, item: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            path = self._path(name)
            items = self._read(path, [])
            items.append(item)
            self._write(path, items)
            return item

    async def add_lead(self, user: dict[str, Any], source: str) -> None:
        await self.append(
            "leads.json",
            {
                "id": uuid.uuid4().hex[:10],
                "created_at": utc_now(),
                "source": source,
                "user": user,
            },
        )

    # Admins and roles

    async def get_admins(self) -> dict[str, Any]:
        return await self.load("admins.json", {"users": []})

    async def get_admin_ids_by_roles(self, roles: Iterable[str]) -> set[int]:
        role_set = set(roles)
        admins = await self.get_admins()
        return {int(item["telegram_id"]) for item in admins["users"] if item.get("role") in role_set}

    async def get_user_role(self, telegram_id: int | None) -> str | None:
        if telegram_id is None:
            return None
        admins = await self.get_admins()
        for user in admins["users"]:
            if int(user.get("telegram_id", 0)) == int(telegram_id):
                role = user.get("role")
                return role if role in VALID_ROLES else None
        return None

    async def is_owner(self, telegram_id: int | None) -> bool:
        return await self.get_user_role(telegram_id) == "owner"

    async def set_role(self, telegram_id: int, role: str, actor_user: Any | None = None) -> tuple[bool, str]:
        role = role.strip().lower()
        if role not in VALID_ROLES:
            return False, "Неизвестная роль. Доступны: owner, super_admin, admin, viewer."
        if role == "owner":
            return False, "Роль owner задается через OWNER_ID и не назначается командой."

        async with self._lock:
            path = self._path("admins.json")
            admins = self._normalize_admins(self._read(path, {"users": []}))
            now = utc_now()
            for user in admins["users"]:
                if int(user["telegram_id"]) != int(telegram_id):
                    continue
                if user.get("role") == "owner":
                    return False, "Владельца нельзя понизить или удалить через бота."
                user["role"] = role
                user["updated_at"] = now
                self._write(path, admins)
                return True, f"Роль пользователя {telegram_id} изменена на {role}."

            admins["users"].append(
                {
                    "telegram_id": int(telegram_id),
                    "role": role,
                    "name": f"id {telegram_id}",
                    "username": "",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            self._write(path, admins)
            return True, f"Пользователь {telegram_id} добавлен с ролью {role}."

    async def touch_admin_profile(self, telegram_user: Any | None) -> None:
        if telegram_user is None:
            return
        async with self._lock:
            path = self._path("admins.json")
            admins = self._normalize_admins(self._read(path, {"users": []}))
            changed = False
            for admin in admins["users"]:
                if int(admin["telegram_id"]) == int(telegram_user.id):
                    admin["name"] = getattr(telegram_user, "full_name", None) or getattr(telegram_user, "first_name", "") or admin.get("name", "")
                    admin["username"] = getattr(telegram_user, "username", None) or ""
                    admin["updated_at"] = utc_now()
                    changed = True
                    break
            if changed:
                self._write(path, admins)

    # Services

    async def list_services(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        services = await self.load("services.json", [])
        if not include_inactive:
            services = [item for item in services if item.get("active", True)]
        return sorted(services, key=lambda item: (int(item.get("sort_order", 0)), item.get("title", "")))

    async def get_service(self, service_id: str) -> dict[str, Any] | None:
        services = await self.list_services(include_inactive=True)
        return next((item for item in services if item["id"] == service_id), None)

    async def add_service(self, title: str, price: int, duration_min: int, description: str) -> dict[str, Any]:
        async with self._lock:
            path = self._path("services.json")
            services = self._normalize_services(self._read(path, []))
            service_id = self._make_service_id(title, {item["id"] for item in services})
            sort_order = max([int(item.get("sort_order", 0)) for item in services] or [0]) + 10
            service = {
                "id": service_id,
                "title": title.strip(),
                "price": int(price),
                "duration_min": int(duration_min),
                "description": description.strip(),
                "active": True,
                "sort_order": sort_order,
            }
            services.append(service)
            self._write(path, services)
            return service

    async def update_service(self, service_id: str, **changes: Any) -> dict[str, Any] | None:
        async with self._lock:
            path = self._path("services.json")
            services = self._normalize_services(self._read(path, []))
            service: dict[str, Any] | None = None
            for item in services:
                if item["id"] == service_id:
                    item.update({key: value for key, value in changes.items() if value is not None})
                    item["price"] = int(item.get("price", 0))
                    item["duration_min"] = int(item.get("duration_min", DEFAULT_SERVICE_DURATION_MIN))
                    item["active"] = bool(item.get("active", True))
                    service = item
                    break
            if service is None:
                return None
            self._write(path, services)
            return service

    async def deactivate_service(self, service_id: str) -> dict[str, Any] | None:
        return await self.update_service(service_id, active=False)

    async def delete_service_if_unused(self, service_id: str) -> tuple[bool, dict[str, Any] | None]:
        async with self._lock:
            services_path = self._path("services.json")
            services = self._normalize_services(self._read(services_path, []))
            bookings = self._normalized_bookings_locked()
            service = next((item for item in services if item["id"] == service_id), None)
            if service is None:
                return False, None
            used = any(service_id in {svc.get("id") for svc in booking.get("services", [])} for booking in bookings)
            if used:
                service["active"] = False
                self._write(services_path, services)
                return False, service
            services = [item for item in services if item["id"] != service_id]
            self._write(services_path, services)
            return True, service

    # Bookings

    async def create_booking_if_free(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        async with self._lock:
            path = self._path("bookings.json")
            raw_bookings = self._read(path, [])
            bookings = self._normalized_bookings_locked(raw_bookings)
            services_by_id = {item["id"]: item for item in self._normalize_services(self._read(self._path("services.json"), []))}
            booking = self._normalize_booking(
                {
                    "id": uuid.uuid4().hex[:10],
                    "status": "confirmed",
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                    **payload,
                },
                services_by_id,
            )
            if self._booking_conflicts_locked(
                bookings,
                booking["date"],
                booking["start_time"],
                booking["end_time"],
            ):
                return None
            raw_bookings.append(self._booking_for_write(booking))
            self._write(path, raw_bookings)
            self._upsert_client_from_booking_locked(booking, self._normalized_bookings_locked(raw_bookings))
            return booking

    async def add_booking_if_free(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return await self.create_booking_if_free(payload)

    async def list_bookings(
        self,
        date_from: str,
        date_to: str,
        include_statuses: Iterable[str] | None = ("confirmed",),
    ) -> list[dict[str, Any]]:
        bookings = await self.load("bookings.json", [])
        status_set = set(include_statuses) if include_statuses is not None else None
        result = [
            booking
            for booking in bookings
            if date_from <= booking.get("date", "") <= date_to
            and (status_set is None or booking.get("status") in status_set)
        ]
        return sorted(result, key=lambda item: (item.get("date", ""), item.get("start_time", "")))

    async def get_booking(self, booking_id: str) -> dict[str, Any] | None:
        bookings = await self.load("bookings.json", [])
        return next((item for item in bookings if item.get("id") == booking_id), None)

    async def update_booking(self, booking_id: str, **changes: Any) -> dict[str, Any] | None:
        async with self._lock:
            path = self._path("bookings.json")
            raw_bookings = self._read(path, [])
            services_by_id = {item["id"]: item for item in self._normalize_services(self._read(self._path("services.json"), []))}
            updated: dict[str, Any] | None = None
            for index, raw in enumerate(raw_bookings):
                booking = self._normalize_booking(raw, services_by_id)
                if booking.get("id") != booking_id:
                    continue
                booking.update(changes)
                booking["updated_at"] = utc_now()
                booking = self._normalize_booking(booking, services_by_id)
                raw_bookings[index] = self._booking_for_write(booking)
                updated = booking
                break
            if updated is None:
                return None
            self._write(path, raw_bookings)
            self._upsert_client_from_booking_locked(updated, self._normalized_bookings_locked(raw_bookings))
            return updated

    async def cancel_booking(self, booking_id: str) -> dict[str, Any] | None:
        return await self.update_booking(booking_id, status="cancelled")

    async def complete_booking(self, booking_id: str) -> dict[str, Any] | None:
        return await self.update_booking(booking_id, status="completed")

    async def reschedule_booking(self, booking_id: str, date: str, start_time: str) -> tuple[dict[str, Any] | None, bool]:
        async with self._lock:
            path = self._path("bookings.json")
            raw_bookings = self._read(path, [])
            services_by_id = {item["id"]: item for item in self._normalize_services(self._read(self._path("services.json"), []))}
            bookings = self._normalized_bookings_locked(raw_bookings)
            booking = next((item for item in bookings if item.get("id") == booking_id), None)
            if booking is None:
                return None, False
            duration = int(booking.get("total_duration_min") or DEFAULT_SERVICE_DURATION_MIN)
            end_time = calculate_end_time(start_time, duration)
            if self._booking_conflicts_locked(bookings, date, start_time, end_time, exclude_booking_id=booking_id):
                return booking, False
            booking.update({"date": date, "start_time": start_time, "end_time": end_time, "updated_at": utc_now()})
            for index, raw in enumerate(raw_bookings):
                if self._normalize_booking(raw, services_by_id).get("id") == booking_id:
                    raw_bookings[index] = self._booking_for_write(booking)
                    break
            self._write(path, raw_bookings)
            self._upsert_client_from_booking_locked(booking, self._normalized_bookings_locked(raw_bookings))
            return booking, True

    async def booking_conflicts(
        self,
        date: str,
        start_time: str,
        end_time: str,
        exclude_booking_id: str | None = None,
    ) -> bool:
        async with self._lock:
            return self._booking_conflicts_locked(
                self._normalized_bookings_locked(),
                date,
                start_time,
                end_time,
                exclude_booking_id,
            )

    async def available_time_slots(
        self,
        day: str,
        duration_min: int,
        exclude_booking_id: str | None = None,
    ) -> list[str]:
        async with self._lock:
            bookings = self._normalized_bookings_locked()
            blocked_dates = set(self._read(self._path("blocked_dates.json"), []))
            if day in blocked_dates:
                return []
            result: list[str] = []
            for start_time in TIME_SLOTS:
                if not fits_working_day(start_time, duration_min):
                    continue
                end_time = calculate_end_time(start_time, duration_min)
                if not self._booking_conflicts_locked(bookings, day, start_time, end_time, exclude_booking_id):
                    result.append(start_time)
            return result

    async def booked_times(self, day: str) -> set[str]:
        available = set(await self.available_time_slots(day, DEFAULT_SERVICE_DURATION_MIN))
        return {slot for slot in TIME_SLOTS if slot not in available}

    # Blocked dates and slots

    async def list_blocked_dates(self) -> list[str]:
        return await self.load("blocked_dates.json", [])

    async def toggle_blocked_date(self, day: str) -> bool:
        async with self._lock:
            path = self._path("blocked_dates.json")
            blocked = set(self._read(path, []))
            if day in blocked:
                blocked.remove(day)
                is_blocked = False
            else:
                blocked.add(day)
                is_blocked = True
            self._write(path, sorted(blocked))
            return is_blocked

    async def list_blocked_slots(self) -> list[dict[str, Any]]:
        return await self.load("blocked_slots.json", [])

    async def add_blocked_slot(self, day: str, start_time: str, end_time: str, reason: str = "") -> dict[str, Any]:
        if parse_time_to_minutes(start_time) >= parse_time_to_minutes(end_time):
            raise ValueError("start_time must be before end_time")
        slot = {
            "id": uuid.uuid4().hex[:10],
            "date": day,
            "start_time": start_time,
            "end_time": end_time,
            "reason": reason.strip(),
            "created_at": utc_now(),
        }
        await self.append("blocked_slots.json", slot)
        return slot

    async def remove_blocked_slot(self, slot_id: str) -> bool:
        async with self._lock:
            path = self._path("blocked_slots.json")
            slots = self._normalize_blocked_slots(self._read(path, []))
            new_slots = [item for item in slots if item.get("id") != slot_id]
            changed = len(new_slots) != len(slots)
            if changed:
                self._write(path, new_slots)
            return changed

    # Reviews

    async def add_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        review = {
            "id": uuid.uuid4().hex[:10],
            "created_at": utc_now(),
            "published": False,
            **payload,
        }
        return await self.append("reviews.json", review)

    async def set_review_published(self, review_id: str, published: bool) -> bool:
        async with self._lock:
            path = self._path("reviews.json")
            reviews = self._read(path, [])
            changed = False
            for review in reviews:
                if review.get("id") == review_id:
                    review["published"] = published
                    changed = True
                    break
            if changed:
                self._write(path, reviews)
            return changed

    # Clients

    async def upsert_client_from_booking(self, booking: dict[str, Any]) -> None:
        async with self._lock:
            self._upsert_client_from_booking_locked(booking, self._normalized_bookings_locked())

    async def list_clients(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._lock:
            self._rebuild_clients_locked(force=True)
            clients = self._normalize_clients(self._read(self._path("clients.json"), []))
        return sorted(clients, key=lambda item: item.get("updated_at", ""), reverse=True)[:limit]

    async def find_clients(self, query: str) -> list[dict[str, Any]]:
        query_norm = _normalize_search_text(query)
        if not query_norm:
            return await self.list_clients()
        async with self._lock:
            self._rebuild_clients_locked(force=True)
            clients = self._normalize_clients(self._read(self._path("clients.json"), []))
        result = []
        for client in clients:
            haystack = _normalize_search_text(
                " ".join(
                    [
                        str(client.get("telegram_id", "")),
                        str(client.get("username", "")),
                        str(client.get("first_name", "")),
                        str(client.get("last_name", "")),
                        str(client.get("display_name", "")),
                        str(client.get("telegram_name", "")),
                        str(client.get("phone", "")),
                        " ".join(client.get("contact_names", [])),
                    ]
                )
            )
            if query_norm in haystack:
                result.append(client)
        return sorted(result, key=lambda item: item.get("updated_at", ""), reverse=True)[:20]

    async def get_client(self, telegram_id: int) -> dict[str, Any] | None:
        async with self._lock:
            self._rebuild_clients_locked(force=True)
            clients = self._normalize_clients(self._read(self._path("clients.json"), []))
        return next((item for item in clients if int(item.get("telegram_id", 0)) == int(telegram_id)), None)

    async def delete_client_with_bookings(self, telegram_id: int) -> tuple[bool, int]:
        async with self._lock:
            bookings_path = self._path("bookings.json")
            raw_bookings = self._read(bookings_path, [])
            services_by_id = {item["id"]: item for item in self._normalize_services(self._read(self._path("services.json"), []))}
            kept_bookings = []
            removed_count = 0
            for raw_booking in raw_bookings:
                booking = self._normalize_booking(raw_booking, services_by_id)
                if int(booking.get("client", {}).get("telegram_id") or 0) == int(telegram_id):
                    removed_count += 1
                else:
                    kept_bookings.append(raw_booking)

            clients_path = self._path("clients.json")
            clients = self._normalize_clients(self._read(clients_path, []))
            kept_clients = [
                client
                for client in clients
                if int(client.get("telegram_id", 0)) != int(telegram_id)
            ]
            changed = removed_count > 0 or len(kept_clients) != len(clients)
            if changed:
                self._write(bookings_path, kept_bookings)
                self._write(clients_path, kept_clients)
            return changed, removed_count

    async def client_bookings(self, telegram_id: int) -> list[dict[str, Any]]:
        bookings = await self.load("bookings.json", [])
        result = [
            item
            for item in bookings
            if int(item.get("client", {}).get("telegram_id") or 0) == int(telegram_id)
        ]
        return sorted(result, key=lambda item: (item.get("date", ""), item.get("start_time", "")), reverse=True)

    # Stats

    async def stats(self) -> dict[str, Any]:
        bookings = await self.load("bookings.json", [])
        leads = await self.load("leads.json", [])
        clients = await self.load("clients.json", [])
        source_counts: dict[str, int] = {}
        for lead in leads:
            source = lead.get("source", "Не указано")
            source_counts[source] = source_counts.get(source, 0) + 1
        return {
            "bookings_total": len(bookings),
            "bookings_confirmed": len([item for item in bookings if item.get("status") == "confirmed"]),
            "bookings_completed": len([item for item in bookings if item.get("status") == "completed"]),
            "bookings_cancelled": len([item for item in bookings if item.get("status") == "cancelled"]),
            "revenue_completed": sum(int(item.get("total_price", 0)) for item in bookings if item.get("status") == "completed"),
            "clients_total": len(clients),
            "leads_total": len(leads),
            "sources": source_counts,
        }

    def _path(self, name: str) -> Path:
        return self.data_dir / name

    def _bootstrap_admins_locked(
        self,
        owner_id: int | None,
        master_chat_id: int | None,
        admin_ids: set[int],
    ) -> None:
        path = self._path("admins.json")
        admins = self._normalize_admins(self._read(path, {"users": []}))
        users = admins["users"]
        now = utc_now()

        def upsert(telegram_id: int | None, role: str) -> None:
            if telegram_id is None or int(telegram_id) == 123456789:
                return
            for user in users:
                if int(user["telegram_id"]) == int(telegram_id):
                    if role == "owner":
                        user["role"] = "owner"
                        user["updated_at"] = now
                    return
            users.append(
                {
                    "telegram_id": int(telegram_id),
                    "role": role,
                    "name": "Owner" if role == "owner" else f"id {telegram_id}",
                    "username": "",
                    "created_at": now,
                    "updated_at": now,
                }
            )

        upsert(owner_id, "owner")
        upsert(master_chat_id, "super_admin")
        for admin_id in admin_ids:
            upsert(admin_id, "super_admin")
        self._write(path, admins)

    def _normalized_bookings_locked(self, raw_bookings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        services_by_id = {item["id"]: item for item in self._normalize_services(self._read(self._path("services.json"), []))}
        raw = raw_bookings if raw_bookings is not None else self._read(self._path("bookings.json"), [])
        return [self._normalize_booking(item, services_by_id) for item in raw if isinstance(item, dict)]

    def _booking_conflicts_locked(
        self,
        bookings: list[dict[str, Any]],
        day: str,
        start_time: str,
        end_time: str,
        exclude_booking_id: str | None = None,
    ) -> bool:
        blocked_dates = set(self._read(self._path("blocked_dates.json"), []))
        if day in blocked_dates:
            return True

        for slot in self._normalize_blocked_slots(self._read(self._path("blocked_slots.json"), [])):
            if slot.get("date") == day and intervals_overlap(start_time, end_time, slot["start_time"], slot["end_time"]):
                return True

        for booking in bookings:
            if booking.get("id") == exclude_booking_id:
                continue
            if booking.get("status") != "confirmed" or booking.get("date") != day:
                continue
            if intervals_overlap(start_time, end_time, booking["start_time"], booking["end_time"]):
                return True
        return False

    def _upsert_client_from_booking_locked(self, booking: dict[str, Any], bookings: list[dict[str, Any]]) -> None:
        client = booking.get("client", {})
        contact = booking.get("contact", {})
        telegram_id = client.get("telegram_id")
        if not telegram_id:
            return
        telegram_id = int(telegram_id)
        path = self._path("clients.json")
        clients = self._normalize_clients(self._read(path, []))
        related = [
            item
            for item in bookings
            if int(item.get("client", {}).get("telegram_id") or 0) == telegram_id
        ]
        related_sorted = sorted(related, key=lambda item: (item.get("date", ""), item.get("start_time", "")))
        last_booking = related_sorted[-1] if related_sorted else booking
        now = utc_now()
        existing = next((item for item in clients if int(item.get("telegram_id", 0)) == telegram_id), None)
        contact_name = str(contact.get("name") or "").strip()
        contact_names = sorted(
            {
                str(item.get("contact", {}).get("name") or "").strip()
                for item in related
                if str(item.get("contact", {}).get("name") or "").strip()
            },
            key=str.casefold,
        )
        telegram_name = " ".join(
            part
            for part in [
                str(client.get("first_name") or "").strip(),
                str(client.get("last_name") or "").strip(),
            ]
            if part
        ) or str(client.get("display_name") or "").strip()
        payload = {
            "telegram_id": telegram_id,
            "username": client.get("username") or "",
            "first_name": client.get("first_name") or "",
            "last_name": client.get("last_name") or "",
            "display_name": contact_name or client.get("display_name") or client.get("first_name") or f"id {telegram_id}",
            "telegram_name": telegram_name,
            "contact_names": contact_names,
            "phone": contact.get("phone") or "",
            "bookings_count": len(related),
            "last_booking_at": last_booking.get("date", ""),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        if existing:
            existing.update(payload)
        else:
            clients.append(payload)
        self._write(path, clients)

    def _rebuild_clients_locked(self, force: bool = False) -> None:
        bookings = self._normalized_bookings_locked()
        clients_path = self._path("clients.json")
        if not force and self._read(clients_path, []):
            return
        self._write(clients_path, [])
        if not bookings:
            return
        for booking in bookings:
            self._upsert_client_from_booking_locked(booking, bookings)

    @staticmethod
    def _normalize_admins(payload: Any) -> dict[str, Any]:
        users = payload.get("users", []) if isinstance(payload, dict) else []
        normalized: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in users:
            if not isinstance(item, dict):
                continue
            try:
                telegram_id = int(item.get("telegram_id"))
            except (TypeError, ValueError):
                continue
            if telegram_id in seen:
                continue
            seen.add(telegram_id)
            role = item.get("role") if item.get("role") in VALID_ROLES else "viewer"
            normalized.append(
                {
                    "telegram_id": telegram_id,
                    "role": role,
                    "name": str(item.get("name") or f"id {telegram_id}"),
                    "username": str(item.get("username") or "").lstrip("@"),
                    "created_at": item.get("created_at") or utc_now(),
                    "updated_at": item.get("updated_at") or item.get("created_at") or utc_now(),
                }
            )
        return {"users": normalized}

    @staticmethod
    def _normalize_services(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []
        result: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                continue
            service_id = str(item.get("id") or f"service_{index + 1}")
            if service_id in used_ids:
                service_id = f"{service_id}_{index + 1}"
            used_ids.add(service_id)
            result.append(
                {
                    "id": service_id,
                    "title": str(item.get("title") or "Услуга"),
                    "price": _int_or_default(item.get("price"), 0),
                    "duration_min": max(_int_or_default(item.get("duration_min"), DEFAULT_SERVICE_DURATION_MIN), 1),
                    "description": str(item.get("description") or ""),
                    "active": bool(item.get("active", True)),
                    "sort_order": _int_or_default(item.get("sort_order"), (index + 1) * 10),
                }
            )
        return result

    @staticmethod
    def _normalize_booking(item: dict[str, Any], services_by_id: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        services_by_id = services_by_id or {}
        raw_services = item.get("services")
        services: list[dict[str, Any]] = []
        if isinstance(raw_services, list):
            for raw_service in raw_services:
                service = _service_snapshot(raw_service, services_by_id)
                if service:
                    services.append(service)
        elif item.get("service") is not None:
            service = _service_snapshot(item.get("service"), services_by_id)
            if service:
                services.append(service)
        elif item.get("service_id"):
            service = _service_snapshot(item.get("service_id"), services_by_id)
            if service:
                services.append(service)

        start_time = str(item.get("start_time") or item.get("time") or "")
        total_duration = _int_or_default(item.get("total_duration_min"), sum(int(svc.get("duration_min", 0)) for svc in services))
        if total_duration <= 0:
            total_duration = DEFAULT_SERVICE_DURATION_MIN
        end_time = str(item.get("end_time") or (calculate_end_time(start_time, total_duration) if start_time else ""))
        total_price = _int_or_default(item.get("total_price"), sum(int(svc.get("price", 0)) for svc in services))

        raw_client = item.get("client") if isinstance(item.get("client"), dict) else {}
        raw_telegram = item.get("telegram_user") if isinstance(item.get("telegram_user"), dict) else {}
        raw_user = item.get("user") if isinstance(item.get("user"), dict) else {}
        telegram_id = (
            raw_client.get("telegram_id")
            or raw_client.get("id")
            or raw_telegram.get("telegram_id")
            or raw_telegram.get("id")
            or raw_user.get("telegram_id")
            or raw_user.get("id")
            or item.get("telegram_id")
        )
        try:
            telegram_id = int(telegram_id) if telegram_id is not None else None
        except (TypeError, ValueError):
            telegram_id = None

        first_name = str(raw_client.get("first_name") or raw_telegram.get("first_name") or raw_user.get("first_name") or "")
        last_name = str(raw_client.get("last_name") or raw_telegram.get("last_name") or raw_user.get("last_name") or "")
        username = str(raw_client.get("username") or raw_telegram.get("username") or raw_user.get("username") or "").lstrip("@")
        display_name = str(raw_client.get("display_name") or " ".join(part for part in [first_name, last_name] if part).strip() or item.get("client_name") or item.get("name") or "Клиент")
        contact_raw = item.get("contact") if isinstance(item.get("contact"), dict) else {}
        contact_name = str(contact_raw.get("name") or item.get("client_name") or item.get("name") or display_name)
        contact_phone = str(contact_raw.get("phone") or item.get("client_phone") or item.get("phone") or "")

        booking = {
            "id": str(item.get("id") or uuid.uuid4().hex[:10]),
            "status": str(item.get("status") or "confirmed"),
            "created_at": str(item.get("created_at") or utc_now()),
            "updated_at": str(item.get("updated_at") or item.get("created_at") or utc_now()),
            "date": str(item.get("date") or ""),
            "start_time": start_time,
            "end_time": end_time,
            "total_duration_min": total_duration,
            "total_price": total_price,
            "services": services,
            "client": {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "display_name": display_name,
            },
            "contact": {
                "name": contact_name,
                "phone": contact_phone,
            },
            "notes": str(item.get("notes") or ""),
        }

        # Legacy aliases keep older handlers and custom snippets from crashing.
        booking["time"] = booking["start_time"]
        booking["service"] = booking["services"][0] if booking["services"] else {}
        booking["client_name"] = contact_name
        booking["client_phone"] = contact_phone
        booking["telegram_user"] = {
            "id": telegram_id,
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        }
        return booking

    @staticmethod
    def _booking_for_write(booking: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": booking["id"],
            "status": booking["status"],
            "created_at": booking["created_at"],
            "updated_at": booking["updated_at"],
            "date": booking["date"],
            "start_time": booking["start_time"],
            "end_time": booking["end_time"],
            "total_duration_min": booking["total_duration_min"],
            "total_price": booking["total_price"],
            "services": booking.get("services", []),
            "client": booking.get("client", {}),
            "contact": booking.get("contact", {}),
            "notes": booking.get("notes", ""),
        }

    @staticmethod
    def _normalize_blocked_slots(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []
        result: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if not item.get("date") or not item.get("start_time") or not item.get("end_time"):
                continue
            result.append(
                {
                    "id": str(item.get("id") or uuid.uuid4().hex[:10]),
                    "date": str(item["date"]),
                    "start_time": str(item["start_time"]),
                    "end_time": str(item["end_time"]),
                    "reason": str(item.get("reason") or ""),
                    "created_at": str(item.get("created_at") or utc_now()),
                }
            )
        return sorted(result, key=lambda item: (item["date"], item["start_time"]))

    @staticmethod
    def _normalize_clients(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []
        result = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                telegram_id = int(item.get("telegram_id"))
            except (TypeError, ValueError):
                continue
            result.append(
                {
                    "telegram_id": telegram_id,
                    "username": str(item.get("username") or "").lstrip("@"),
                    "first_name": str(item.get("first_name") or ""),
                    "last_name": str(item.get("last_name") or ""),
                    "display_name": str(item.get("display_name") or item.get("first_name") or f"id {telegram_id}"),
                    "telegram_name": str(item.get("telegram_name") or ""),
                    "contact_names": [
                        str(name)
                        for name in (item.get("contact_names") if isinstance(item.get("contact_names"), list) else [])
                        if str(name).strip()
                    ],
                    "phone": str(item.get("phone") or ""),
                    "bookings_count": _int_or_default(item.get("bookings_count"), 0),
                    "last_booking_at": str(item.get("last_booking_at") or ""),
                    "created_at": str(item.get("created_at") or utc_now()),
                    "updated_at": str(item.get("updated_at") or item.get("created_at") or utc_now()),
                }
            )
        return result

    @staticmethod
    def _make_service_id(title: str, used_ids: set[str]) -> str:
        value = re.sub(r"[^a-z0-9_]+", "_", title.lower().strip())
        value = re.sub(r"_+", "_", value).strip("_")
        if not value:
            value = f"service_{uuid.uuid4().hex[:6]}"
        candidate = value[:32]
        suffix = 2
        while candidate in used_ids:
            candidate = f"{value[:26]}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _read(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _write(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def _service_snapshot(raw_service: Any, services_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(raw_service, str):
        raw_service = services_by_id.get(raw_service, {"id": raw_service, "title": raw_service})
    if not isinstance(raw_service, dict):
        return None
    service_id = str(raw_service.get("id") or raw_service.get("title") or "service")
    source = services_by_id.get(service_id, raw_service)
    return {
        "id": service_id,
        "title": str(source.get("title") or raw_service.get("title") or "Услуга"),
        "price": _int_or_default(source.get("price", raw_service.get("price")), 0),
        "duration_min": max(_int_or_default(source.get("duration_min", raw_service.get("duration_min")), DEFAULT_SERVICE_DURATION_MIN), 1),
    }


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_search_text(value: Any) -> str:
    return " ".join(str(value or "").replace("@", " ").casefold().split())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
