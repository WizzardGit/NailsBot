from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Iterable

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


def services_kb(services: list[dict[str, Any]], selected_ids: Iterable[str] | None = None) -> InlineKeyboardMarkup:
    selected = set(selected_ids or [])
    builder = InlineKeyboardBuilder()
    for service in services:
        mark = "✅" if service["id"] in selected else "⬜"
        builder.button(
            text=f"{mark} {service['title']} · {service['price']} ₽",
            callback_data=f"book:svc:{service['id']}",
        )
    builder.button(text="✅ Продолжить", callback_data="book:continue")
    builder.button(text="🧹 Очистить выбор", callback_data="book:clear")
    builder.button(text="❌ Отмена", callback_data="book:cancel")
    builder.adjust(1)
    return builder.as_markup()


def booking_calendar_kb(
    year: int,
    month: int,
    today: date,
    horizon_end: date,
    unavailable_by_date: dict[str, set[str]],
    blocked_dates: set[str],
    callback_prefix: str = "book",
    back_callback: str | None = None,
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
            unavailable = unavailable_by_date.get(current_iso, set())

            if callback_prefix != "book":
                is_selectable = today <= current <= horizon_end
                label = "×" if current_iso in blocked_dates else str(day_number)
            else:
                is_past_or_too_far = current < today or current > horizon_end
                is_full_or_blocked = current_iso in blocked_dates or len(unavailable) >= len(TIME_SLOTS)
                is_selectable = (
                    today <= current <= horizon_end
                    and is_workday(current)
                    and current_iso not in blocked_dates
                    and len(unavailable) < len(TIME_SLOTS)
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

    back = back_callback or ("book:services" if callback_prefix == "book" else "adm:menu")
    nav_buttons.append(InlineKeyboardButton(text="↩️", callback_data=back))

    if date(next_year, next_month, 1) <= horizon_end:
        nav_buttons.append(InlineKeyboardButton(text="›", callback_data=f"{callback_prefix}:month:{next_year}-{next_month:02d}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
    builder.row(*nav_buttons)
    return builder.as_markup()


def time_slots_kb(
    available_slots: Iterable[str],
    callback_prefix: str = "book:time",
    back_callback: str = "book:change_date",
) -> InlineKeyboardMarkup:
    available = set(available_slots)
    builder = InlineKeyboardBuilder()
    for time_slot in TIME_SLOTS:
        if time_slot in available:
            builder.button(text=f"✓ {time_slot}", callback_data=f"{callback_prefix}:{time_slot}")
        else:
            builder.button(text=f"× {time_slot} занято", callback_data="noop")
    builder.button(text="Выбрать другую дату", callback_data=back_callback)
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


def admin_menu_kb(role: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Сегодня", callback_data="adm:b:today")
    builder.button(text="📆 Завтра", callback_data="adm:b:tomorrow")
    builder.button(text="🗓 Неделя", callback_data="adm:b:week")
    builder.button(text="🔎 Выбрать дату", callback_data="adm:b:pick")
    if role in {"owner", "super_admin", "admin"}:
        builder.button(text="👥 Клиенты", callback_data="adm:clients")
    if role in {"owner", "super_admin"}:
        builder.button(text="💅 Услуги и цены", callback_data="adm:s:menu")
        builder.button(text="📤 Выгрузка", callback_data="adm:export")
    if role in {"owner", "super_admin", "admin"}:
        builder.button(text="🚫 Закрыть дату/время", callback_data="adm:blk:menu")
        builder.button(text="⭐ Отзывы", callback_data="adm:reviews")
    builder.button(text="📊 Статистика", callback_data="adm:stats")
    if role == "owner":
        builder.button(text="⚙️ Админы", callback_data="adm:admins")
    builder.adjust(2, 2, 1, 1, 1, 1, 1)
    return builder.as_markup()


def admin_back_kb(callback_data: str = "adm:menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data=callback_data)
    return builder.as_markup()


def admin_booking_list_kb(bookings: list[dict[str, Any]], back_callback: str = "adm:menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for booking in bookings:
        name = booking.get("contact", {}).get("name") or booking.get("client", {}).get("display_name") or "Клиент"
        builder.button(text=f"{booking['start_time']} {name}", callback_data=f"adm:b:view:{booking['id']}")
    builder.button(text="⬅️ Назад", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()


def admin_booking_card_kb(booking: dict[str, Any], back_callback: str = "adm:menu") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"adm:b:cancel:{booking['id']}"),
            InlineKeyboardButton(text="🔁 Перенести", callback_data=f"adm:b:res:{booking['id']}"),
        ],
        [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"adm:b:done:{booking['id']}")],
    ]
    username = booking.get("client", {}).get("username")
    if username:
        rows.append([InlineKeyboardButton(text="📞 Написать клиенту", url=f"https://t.me/{username}")])
    else:
        rows.append([InlineKeyboardButton(text="📞 Написать клиенту", callback_data=f"adm:b:contact:{booking['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_booking_notice_kb(booking: dict[str, Any]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Открыть запись", callback_data=f"adm:b:view:{booking['id']}")]]
    username = booking.get("client", {}).get("username")
    if username:
        rows.append([InlineKeyboardButton(text="Написать клиенту", url=f"https://t.me/{username}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_action_kb(confirm_callback: str, back_callback: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, отменить", callback_data=confirm_callback)
    builder.button(text="Нет, назад", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()


def admin_services_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Список услуг", callback_data="adm:s:list")
    builder.button(text="➕ Добавить услугу", callback_data="adm:s:add")
    builder.button(text="✏️ Изменить услугу", callback_data="adm:s:list")
    builder.button(text="🙈 Скрыть/показать услугу", callback_data="adm:s:list")
    builder.button(text="🗑 Удалить услугу", callback_data="adm:s:list")
    builder.button(text="⬅️ Назад", callback_data="adm:menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_services_list_kb(services: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in services:
        mark = "✅" if service.get("active", True) else "🙈"
        builder.button(text=f"{mark} {service['title']}", callback_data=f"adm:s:edit:{service['id']}")
    builder.button(text="⬅️ Назад", callback_data="adm:s:menu")
    builder.adjust(1)
    return builder.as_markup()


def service_edit_kb(service: dict[str, Any]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data=f"adm:s:title:{service['id']}")
    builder.button(text="💰 Цена", callback_data=f"adm:s:price:{service['id']}")
    builder.button(text="⏳ Длительность", callback_data=f"adm:s:dur:{service['id']}")
    builder.button(text="📝 Описание", callback_data=f"adm:s:desc:{service['id']}")
    builder.button(text="🙈 Скрыть" if service.get("active", True) else "👁 Показать", callback_data=f"adm:s:toggle:{service['id']}")
    builder.button(text="🗑 Удалить", callback_data=f"adm:s:del:{service['id']}")
    builder.button(text="⬅️ Назад", callback_data="adm:s:list")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def service_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Сохранить", callback_data="adm:s:add:save")
    builder.button(text="❌ Отмена", callback_data="adm:s:menu")
    builder.adjust(2)
    return builder.as_markup()


def clients_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Последние клиенты", callback_data="adm:c:list")
    builder.button(text="🔎 Поиск", callback_data="adm:c:search")
    builder.button(text="⬅️ Назад", callback_data="adm:menu")
    builder.adjust(1)
    return builder.as_markup()


def clients_list_kb(clients: list[dict[str, Any]], back_callback: str = "adm:clients") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for client in clients:
        name = client.get("display_name") or f"id {client['telegram_id']}"
        builder.button(text=name, callback_data=f"adm:c:view:{client['telegram_id']}")
    builder.button(text="⬅️ Назад", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()


def client_card_kb(client: dict[str, Any]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="📜 История записей", callback_data=f"adm:c:hist:{client['telegram_id']}")]]
    if client.get("username"):
        rows.append([InlineKeyboardButton(text="📞 Написать", url=f"https://t.me/{client['username']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:clients")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def export_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Сегодня CSV", callback_data="adm:x:today")
    builder.button(text="🗓 Неделя CSV", callback_data="adm:x:week")
    builder.button(text="📆 Месяц CSV", callback_data="adm:x:month")
    builder.button(text="📚 Все записи CSV", callback_data="adm:x:all")
    builder.button(text="⬅️ Назад", callback_data="adm:menu")
    builder.adjust(1)
    return builder.as_markup()


def blocked_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Закрыть день", callback_data="adm:blk:day")
    builder.button(text="⏰ Закрыть время", callback_data="adm:blk:slot")
    builder.button(text="📋 Закрытые даты/время", callback_data="adm:blk:list")
    builder.button(text="🔓 Открыть обратно", callback_data="adm:blk:open")
    builder.button(text="⬅️ Назад", callback_data="adm:menu")
    builder.adjust(1)
    return builder.as_markup()


def blocked_slots_kb(slots: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=f"{slot['date']} {slot['start_time']}–{slot['end_time']}", callback_data=f"adm:blk:rm:{slot['id']}")
    builder.button(text="⬅️ Назад", callback_data="adm:blk:menu")
    builder.adjust(1)
    return builder.as_markup()


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    month += delta
    if month < 1:
        return year - 1, 12
    if month > 12:
        return year + 1, 1
    return year, month
