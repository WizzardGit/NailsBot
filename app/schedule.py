from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


TIME_SLOTS = ["10:00", "12:00", "14:00", "16:00", "18:00"]
WORKING_DAY_END = "22:00"
WORKING_WEEKDAYS = {1, 2, 3, 4, 5}  # Tuesday-Saturday
DEFAULT_SERVICE_DURATION_MIN = 60

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


def short_date(value: str | date) -> str:
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return day.strftime("%d.%m.%Y")


def iter_booking_dates(today: date, horizon_days: int) -> list[date]:
    return [today + timedelta(days=offset) for offset in range(horizon_days + 1)]


def parse_time_to_minutes(value: str) -> int:
    hours, minutes = value.split(":", 1)
    return int(hours) * 60 + int(minutes)


def minutes_to_time(value: int) -> str:
    hours, minutes = divmod(value, 60)
    return f"{hours:02d}:{minutes:02d}"


def add_minutes_to_time(start_time: str, duration_min: int) -> str:
    return minutes_to_time(parse_time_to_minutes(start_time) + int(duration_min))


def calculate_end_time(start_time: str, duration_min: int) -> str:
    return add_minutes_to_time(start_time, duration_min)


def intervals_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    return parse_time_to_minutes(start1) < parse_time_to_minutes(end2) and parse_time_to_minutes(start2) < parse_time_to_minutes(end1)


def fits_working_day(start_time: str, duration_min: int) -> bool:
    return parse_time_to_minutes(calculate_end_time(start_time, duration_min)) <= parse_time_to_minutes(WORKING_DAY_END)
