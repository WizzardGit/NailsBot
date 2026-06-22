from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_FILES: dict[str, Any] = {
    "bookings.json": [],
    "leads.json": [],
    "blocked_dates.json": [],
}


class JsonStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self._lock = asyncio.Lock()

    async def ensure_files(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            for name, default in DEFAULT_FILES.items():
                path = self._path(name)
                if not path.exists():
                    self._write(path, default)

    async def load(self, name: str, default: Any) -> Any:
        async with self._lock:
            path = self._path(name)
            if not path.exists():
                return default
            return self._read(path, default)

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

    async def add_booking_if_free(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        async with self._lock:
            bookings_path = self._path("bookings.json")
            blocked_path = self._path("blocked_dates.json")
            bookings = self._read(bookings_path, [])
            blocked_dates = set(self._read(blocked_path, []))

            if payload["date"] in blocked_dates:
                return None

            for booking in bookings:
                if booking.get("status") != "confirmed":
                    continue
                if booking.get("date") == payload["date"] and booking.get("time") == payload["time"]:
                    return None

            booking = {
                "id": uuid.uuid4().hex[:10],
                "status": "confirmed",
                "created_at": utc_now(),
                **payload,
            }
            bookings.append(booking)
            self._write(bookings_path, bookings)
            return booking

    async def list_bookings(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        bookings = await self.load("bookings.json", [])
        result = [
            booking
            for booking in bookings
            if booking.get("status") == "confirmed" and date_from <= booking.get("date", "") <= date_to
        ]
        return sorted(result, key=lambda item: (item.get("date", ""), item.get("time", "")))

    async def booked_times(self, day: str) -> set[str]:
        bookings = await self.load("bookings.json", [])
        return {
            booking["time"]
            for booking in bookings
            if booking.get("status") == "confirmed" and booking.get("date") == day
        }

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

    async def stats(self) -> dict[str, Any]:
        bookings = await self.load("bookings.json", [])
        leads = await self.load("leads.json", [])
        source_counts: dict[str, int] = {}
        for lead in leads:
            source = lead.get("source", "Не указано")
            source_counts[source] = source_counts.get(source, 0) + 1
        return {
            "bookings_total": len([item for item in bookings if item.get("status") == "confirmed"]),
            "leads_total": len(leads),
            "sources": source_counts,
        }

    def _path(self, name: str) -> Path:
        return self.data_dir / name

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
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

