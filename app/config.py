from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")
PLACEHOLDER_IDS = {123456789}


@dataclass(frozen=True)
class BotConfig:
    token: str
    owner_id: int | None
    master_chat_id: int | None
    admin_ids: set[int]
    timezone: ZoneInfo
    data_dir: Path
    brand_name: str
    instagram_url: str
    contact_phone: str
    address: str
    map_url: str
    booking_horizon_days: int = 30


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if "telegram_id" in value.lower():
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Expected integer value, got {value!r}") from exc


def _parse_admin_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            try:
                admin_id = int(item)
            except ValueError:
                continue
            if admin_id not in PLACEHOLDER_IDS:
                result.add(admin_id)
    return result


def load_config() -> BotConfig:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "123456:replace_me":
        raise RuntimeError("Set BOT_TOKEN in .env before running the bot.")

    owner_id = _parse_int(os.getenv("OWNER_ID"))
    if owner_id in PLACEHOLDER_IDS:
        owner_id = None

    master_chat_id = _parse_int(os.getenv("MASTER_CHAT_ID"))
    if master_chat_id in PLACEHOLDER_IDS:
        master_chat_id = None

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS"))
    if master_chat_id is not None:
        admin_ids.add(master_chat_id)

    return BotConfig(
        token=token,
        owner_id=owner_id,
        master_chat_id=master_chat_id,
        admin_ids=admin_ids,
        timezone=ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
        data_dir=Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data"))).resolve(),
        brand_name=os.getenv("BRAND_NAME", "Studio Liana Nails").strip(),
        instagram_url=os.getenv("INSTAGRAM_URL", "https://instagram.com/studio_liana_nails").strip(),
        contact_phone=os.getenv("CONTACT_PHONE", "+7 999 123-45-67").strip(),
        address=os.getenv("ADDRESS", "Москва, ул. Петровка, 21").strip(),
        map_url=os.getenv("MAP_URL", "https://yandex.ru/maps").strip(),
    )
