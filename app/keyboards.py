from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.schedule import MONTH_TITLES, TIME_SLOTS, is_workday
from app.texts import (
    MENU_BACK,
    MENU_BOOK,
    MENU_CONTACTS,
    MENU_FAQ,
    MENU_PORTFOLIO,
    MENU_REVIEWS,
    MENU_SERVICES,
)


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_BOOK), KeyboardButton(text=MENU_PORTFOLIO)],
            [KeyboardButton(text=MENU_REVIEWS), KeyboardButton(text=MENU_SERVICES)],
            [KeyboardButton(text=MENU_FAQ), KeyboardButton(text=MENU_CONTACTS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел",
    )


def contact_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить телефон", request_contact=True)],
            [KeyboardButton(text=MENU_BACK)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Имя и телефон",
    )


def lead_source_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Instagram", callback_data="lead:instagram")
    builder.button(text="Рекомендация подруги", callback_data="lead:friend")
    builder.button(text="Поиск в интернете", callback_data="lead:search")
    builder.button(text="Другое", callback_data="lead:other")
    builder.adjust(1)
    return builder.as_markup()


def services_kb(services: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in services:
        builder.button(
            text=f"{service['title']} · {service['price']} ₽",
            callback_data=f"book:service:{service['id']}",
        )
    builder.button(text="↩️ В меню", callback_data="nav:home")
    builder.adjust(1)
    return builder.as_markup()


def booking_calendar_kb(
    year: int,
    month: int,
    today: date,
    horizon_end: date,
    booked_by_date: dict[str, set[str]],
    blocked_dates: set[str],
    callback_prefix: str = "book",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"{MONTH_TITLES[month]} {year}", callback_data="noop"))
    builder.row(
        *[InlineKeyboardButton(text=item, callback_data="noop") for item in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]]
    )

    for week in calendar.monthcalendar(year, month):
        buttons: list[InlineKeyboardButton] = []
        for day_number in week:
            if day_number == 0:
                buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
                continue

            current = date(year, month, day_number)
            current_iso = current.isoformat()
            booked_times = booked_by_date.get(current_iso, set())

            if callback_prefix != "book":
                is_selectable = today <= current <= horizon_end
                label = "×" if current_iso in blocked_dates else str(day_number)
            else:
                is_past_or_too_far = current < today or current > horizon_end
                is_full_or_blocked = current_iso in blocked_dates or len(booked_times) >= len(TIME_SLOTS)
                is_selectable = (
                    today <= current <= horizon_end
                    and is_workday(current)
                    and current_iso not in blocked_dates
                    and len(booked_times) < len(TIME_SLOTS)
                )

                if is_past_or_too_far:
                    label = " "
                elif is_full_or_blocked:
                    label = "×"
                elif not is_workday(current):
                    label = "·"
                else:
                    label = str(day_number)

            if is_selectable:
                buttons.append(InlineKeyboardButton(text=label, callback_data=f"{callback_prefix}:date:{current_iso}"))
            else:
                buttons.append(InlineKeyboardButton(text=label, callback_data="noop"))
        builder.row(*buttons)

    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)
    nav_buttons = []
    if date(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1]) >= today:
        nav_buttons.append(InlineKeyboardButton(text="‹", callback_data=f"{callback_prefix}:month:{prev_year}-{prev_month:02d}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
    nav_buttons.append(InlineKeyboardButton(text="↩️", callback_data="book:services" if callback_prefix == "book" else "admin:menu"))
    if date(next_year, next_month, 1) <= horizon_end:
        nav_buttons.append(InlineKeyboardButton(text="›", callback_data=f"{callback_prefix}:month:{next_year}-{next_month:02d}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
    builder.row(*nav_buttons)
    return builder.as_markup()


def time_slots_kb(booked_times: set[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for time_slot in TIME_SLOTS:
        if time_slot in booked_times:
            builder.button(text=f"× {time_slot} занято", callback_data="noop")
        else:
            builder.button(text=f"✓ {time_slot}", callback_data=f"book:time:{time_slot}")
    builder.button(text="Выбрать другую дату", callback_data="book:change_date")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def confirm_booking_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="book:confirm")
    builder.button(text="❌ Отменить", callback_data="book:cancel")
    builder.adjust(2)
    return builder.as_markup()


def portfolio_categories_kb(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(text=category["title"], callback_data=f"portfolio:cat:{category['id']}")
    builder.button(text="🗓 Записаться", callback_data="book:start")
    builder.adjust(1)
    return builder.as_markup()


def book_cta_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗓 Записаться", callback_data="book:start")
    builder.button(text="Показать еще", callback_data="portfolio:open")
    builder.adjust(1)
    return builder.as_markup()


def review_nav_kb(index: int, total: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if total > 1:
        builder.button(text="‹", callback_data=f"review:show:{(index - 1) % total}")
        builder.button(text="›", callback_data=f"review:show:{(index + 1) % total}")
    builder.button(text="Оставить отзыв", callback_data="review:leave")
    builder.button(text="🗓 Записаться", callback_data="book:start")
    builder.adjust(2 if total > 1 else 1, 1, 1)
    return builder.as_markup()


def rating_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for rating in range(1, 6):
        builder.button(text="★" * rating, callback_data=f"review:rate:{rating}")
    builder.adjust(1)
    return builder.as_markup()


def moderation_kb(review_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Опубликовать", callback_data=f"review:publish:{review_id}")
    builder.button(text="❌ Скрыть", callback_data=f"review:hide:{review_id}")
    builder.adjust(2)
    return builder.as_markup()


def faq_kb(items: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=item["question"], callback_data=f"faq:{item['id']}")
    builder.button(text="🗓 Записаться", callback_data="book:start")
    builder.adjust(1)
    return builder.as_markup()


def contacts_kb(instagram_url: str, map_url: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Instagram", url=instagram_url)],
        [InlineKeyboardButton(text="Открыть карту", url=map_url)],
        [InlineKeyboardButton(text="🗓 Записаться", callback_data="book:start")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="admin:today")
    builder.button(text="Неделя", callback_data="admin:week")
    builder.button(text="Закрыть дату", callback_data="admin:block")
    builder.button(text="Статистика", callback_data="admin:stats")
    builder.adjust(2, 2)
    return builder.as_markup()


def admin_back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ Панель мастера", callback_data="admin:menu")
    return builder.as_markup()


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    month += delta
    if month < 1:
        return year - 1, 12
    if month > 12:
        return year + 1, 1
    return year, month
