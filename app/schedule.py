from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


TIME_SLOTS = ["10:00", "12:00", "14:00", "16:00", "18:00"]
WORKING_WEEKDAYS = {1, 2, 3, 4, 5}  # Tuesday-Saturday

WEEKDAY_NAMES = {
    0: "понедельник",
    1: "вторник",
    2: "среда",
    3: "четверг",
    4: "пятница",
    5: "суббота",
    6: "воскресенье",
}

MONTH_NAMES = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

MONTH_TITLES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def today_in(timezone: ZoneInfo) -> date:
    return datetime.now(timezone).date()


def is_workday(day: date) -> bool:
    return day.weekday() in WORKING_WEEKDAYS


def human_date(value: str | date) -> str:
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{day.day} {MONTH_NAMES[day.month]}, {WEEKDAY_NAMES[day.weekday()]}"


def iter_booking_dates(today: date, horizon_days: int) -> list[date]:
    return [today + timedelta(days=offset) for offset in range(horizon_days + 1)]

