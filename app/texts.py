from __future__ import annotations

from html import escape
from typing import Any

from app.schedule import human_date, short_date


MENU_BOOK = "🗓 Записаться"
MENU_PORTFOLIO = "🖼 Примеры работ"
MENU_REVIEWS = "⭐ Отзывы"
MENU_FAQ = "❓ FAQ"
MENU_CONTACTS = "📍 Контакты"
MENU_SERVICES = "💅 Услуги"
MENU_BACK = "↩️ В меню"

ROLE_GROUPS = [
    ("👑 Owner", "owner"),
    ("⭐ Super admins", "super_admin"),
    ("🛠 Admins", "admin"),
    ("👁 Viewers", "viewer"),
]


def user_payload(user: Any) -> dict[str, Any]:
    return {
        "id": user.id,
        "telegram_id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
    }


def welcome_text(brand_name: str) -> str:
    return (
        f"<b>{escape(brand_name)}</b>\n\n"
        "Привет! Я помогу выбрать услугу, посмотреть работы мастера и записаться на удобное время.\n\n"
        "Подскажите, пожалуйста, откуда вы о нас узнали?"
    )


def home_text(brand_name: str) -> str:
    return (
        f"<b>{escape(brand_name)}</b>\n"
        "Ниже главное меню. Можно записаться, посмотреть портфолио, отзывы или уточнить детали перед визитом."
    )


def services_text(services: list[dict[str, Any]]) -> str:
    active_services = [item for item in services if item.get("active", True)]
    if not active_services:
        return "<b>Услуги и стоимость</b>\n\nСейчас нет активных услуг для записи."

    lines = ["<b>Услуги и стоимость</b>", ""]
    for service in active_services:
        lines.append(
            f"• <b>{escape(service['title'])}</b> — {format_money(service['price'])}, {service['duration_min']} мин\n"
            f"  {escape(service.get('description', ''))}"
        )
    return "\n".join(lines)


def booking_intro() -> str:
    return (
        "<b>Запись</b>\n"
        "Выберите одну или несколько услуг. После этого я покажу свободные даты и время."
    )


def selected_services_text(services: list[dict[str, Any]], selected_ids: list[str]) -> str:
    selected = [item for item in services if item["id"] in selected_ids]
    total_price = sum(int(item.get("price", 0)) for item in selected)
    total_duration = sum(int(item.get("duration_min", 0)) for item in selected)
    lines = ["<b>Выберите услуги:</b>", ""]
    for service in services:
        mark = "✅" if service["id"] in selected_ids else "⬜"
        lines.append(
            f"{mark} {escape(service['title'])} — {format_money(service['price'])}, {service['duration_min']} мин"
        )
    lines.extend(
        [
            "",
            f"Итого: <b>{format_money(total_price)}</b>",
            f"Примерная длительность: <b>{total_duration} мин</b>",
        ]
    )
    return "\n".join(lines)


def ask_contact_text() -> str:
    return (
        "<b>Почти готово</b>\n"
        "Отправьте имя и телефон одним сообщением, например:\n"
        "<code>Анна, +7 999 123-45-67</code>"
    )


def booking_card(data: dict[str, Any]) -> str:
    services = data.get("services", [])
    total_price = sum(int(item.get("price", 0)) for item in services)
    total_duration = sum(int(item.get("duration_min", 0)) for item in services)
    end_time = data.get("end_time")
    time_text = data.get("time") or data.get("start_time", "")
    if end_time:
        time_text = f"{time_text}–{end_time}"
    return (
        "<b>Проверьте запись</b>\n\n"
        f"Дата: <b>{human_date(data['date'])}</b>\n"
        f"Время: <b>{escape(time_text)}</b>\n\n"
        f"{format_services_block(services)}\n\n"
        f"Итого: <b>{format_money(total_price)}</b>\n"
        f"Длительность: <b>{total_duration} мин</b>\n\n"
        f"Имя: <b>{escape(data['client_name'])}</b>\n"
        f"Телефон: <b>{escape(data['client_phone'])}</b>"
    )


def booking_success(booking: dict[str, Any]) -> str:
    return (
        "<b>Вы записаны</b>\n\n"
        f"{escape(format_services_inline(booking.get('services', [])))}\n"
        f"{human_date(booking['date'])} в {escape(booking['start_time'])}–{escape(booking['end_time'])}\n\n"
        "Мастер получил уведомление. Если нужно перенести запись, напишите мастеру через раздел «Контакты»."
    )


def admin_booking_notice(booking: dict[str, Any]) -> str:
    client = booking.get("client", {})
    contact = booking.get("contact", {})
    username = client.get("username")
    telegram = f"@{username}" if username else "без username"
    return (
        "<b>🆕 Новая запись</b>\n\n"
        f"📅 {short_date(booking['date'])}\n"
        f"⏰ {escape(booking['start_time'])}–{escape(booking['end_time'])}\n\n"
        f"👤 {escape(contact.get('name') or client.get('display_name') or 'Клиент')}\n"
        f"📞 {escape(contact.get('phone') or 'не указан')}\n"
        f"💬 Telegram: {escape(telegram)}\n"
        f"🆔 ID: {client.get('telegram_id') or 'неизвестно'}\n\n"
        f"{format_services_block(booking.get('services', []), prices=True)}\n\n"
        f"💰 Итого: <b>{format_money(booking.get('total_price', 0))}</b>\n"
        f"⏳ Длительность: <b>{booking.get('total_duration_min', 0)} мин</b>"
    )


def admin_booking_card(booking: dict[str, Any]) -> str:
    client = booking.get("client", {})
    contact = booking.get("contact", {})
    username = client.get("username")
    telegram = f"@{username}" if username else "без username"
    return (
        f"<b>📌 Запись #{escape(booking['id'])}</b>\n\n"
        f"📅 Дата: <b>{short_date(booking['date'])}</b>\n"
        f"⏰ Время: <b>{escape(booking['start_time'])}–{escape(booking['end_time'])}</b>\n"
        f"👤 Клиент: <b>{escape(contact.get('name') or client.get('display_name') or 'Клиент')}</b>\n"
        f"📞 Телефон: <b>{escape(contact.get('phone') or 'не указан')}</b>\n"
        f"💬 Telegram: <b>{escape(telegram)}</b>\n"
        f"🆔 Telegram ID: <code>{client.get('telegram_id') or 'неизвестно'}</code>\n\n"
        f"{format_services_block(booking.get('services', []), prices=True, durations=True)}\n\n"
        f"💰 Итого: <b>{format_money(booking.get('total_price', 0))}</b>\n"
        f"⏳ Длительность: <b>{booking.get('total_duration_min', 0)} мин</b>\n"
        f"📍 Статус: <b>{escape(booking.get('status', ''))}</b>\n"
        f"🕓 Создано: <code>{escape(booking.get('created_at', ''))}</code>"
    )


def format_booking_list(title: str, bookings: list[dict[str, Any]]) -> str:
    if not bookings:
        return f"<b>{escape(title)}</b>\n\nЗаписей нет."

    current_date = ""
    lines = [f"<b>{escape(title)}</b>", ""]
    for booking in bookings:
        if booking["date"] != current_date:
            current_date = booking["date"]
            lines.append(f"📅 <b>{short_date(current_date)}</b>")
        client_name = booking.get("contact", {}).get("name") or booking.get("client", {}).get("display_name") or "Клиент"
        username = booking.get("client", {}).get("username")
        phone = booking.get("contact", {}).get("phone") or "телефон не указан"
        contact_line = f"@{username} / {phone}" if username else f"без username / {phone}"
        lines.append(
            f"\n{escape(booking['start_time'])}–{escape(booking['end_time'])} — {escape(client_name)} — {format_money(booking.get('total_price', 0))}\n"
            f"{escape(format_services_inline(booking.get('services', [])))}\n"
            f"{escape(contact_line)}"
        )
    return "\n".join(lines)


def review_text(review: dict[str, Any], index: int, total: int) -> str:
    stars = "★" * int(review.get("rating", 5))
    return (
        f"<b>Отзывы</b> {index + 1}/{total}\n\n"
        f"{stars}\n"
        f"«{escape(review['text'])}»\n\n"
        f"— {escape(review.get('name', 'Клиент'))}"
    )


def stats_text(stats: dict[str, Any]) -> str:
    lines = [
        "<b>📊 Статистика</b>",
        f"Всего записей: <b>{stats['bookings_total']}</b>",
        f"Активные: <b>{stats['bookings_confirmed']}</b>",
        f"Выполненные: <b>{stats['bookings_completed']}</b>",
        f"Отмененные: <b>{stats['bookings_cancelled']}</b>",
        f"Клиентов: <b>{stats['clients_total']}</b>",
        f"Выручка по выполненным: <b>{format_money(stats['revenue_completed'])}</b>",
        f"Ответов на стартовый вопрос: <b>{stats['leads_total']}</b>",
        "",
        "<b>Откуда пришли</b>",
    ]
    if stats["sources"]:
        for source, count in sorted(stats["sources"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"• {escape(source)} — {count}")
    else:
        lines.append("Пока нет данных.")
    return "\n".join(lines)


def admins_text(admins: dict[str, Any]) -> str:
    lines = ["<b>⚙️ Админы</b>", ""]
    users = admins.get("users", [])
    for title, role in ROLE_GROUPS:
        lines.append(f"<b>{title}</b>")
        role_users = [item for item in users if item.get("role") == role]
        if not role_users:
            lines.append("• нет")
        for user in role_users:
            username = f"@{user['username']}" if user.get("username") else "без username"
            lines.append(f"• {escape(user.get('name') or 'Без имени')} — {escape(username)} — <code>{user['telegram_id']}</code>")
        lines.append("")
    return "\n".join(lines).strip()


def service_card_text(service: dict[str, Any]) -> str:
    status = "активна" if service.get("active", True) else "скрыта"
    description = service.get("description") or "Без описания"
    return (
        f"<b>💅 {escape(service['title'])}</b>\n\n"
        f"Цена: <b>{format_money(service['price'])}</b>\n"
        f"Длительность: <b>{service['duration_min']} мин</b>\n"
        f"Описание: {escape(description)}\n"
        f"Статус: <b>{status}</b>"
    )


def client_card_text(client: dict[str, Any]) -> str:
    username = f"@{client['username']}" if client.get("username") else "без username"
    last_booking = short_date(client["last_booking_at"]) if client.get("last_booking_at") else "нет"
    telegram_name = client.get("telegram_name") or "не указано"
    return (
        f"<b>👤 {escape(client.get('display_name') or 'Клиент')}</b>\n\n"
        f"Telegram: <b>{escape(username)}</b>\n"
        f"Имя в Telegram: <b>{escape(telegram_name)}</b>\n"
        f"ID: <code>{client.get('telegram_id')}</code>\n"
        f"Телефон: <b>{escape(client.get('phone') or 'не указан')}</b>\n"
        f"Записей всего: <b>{client.get('bookings_count', 0)}</b>\n"
        f"Последняя запись: <b>{last_booking}</b>"
    )


def blocked_list_text(dates: list[str], slots: list[dict[str, Any]]) -> str:
    lines = ["<b>🚫 Закрытые даты и время</b>", ""]
    if dates:
        lines.append("<b>Дни</b>")
        for day in dates:
            lines.append(f"• {short_date(day)}")
        lines.append("")
    if slots:
        lines.append("<b>Время</b>")
        for slot in slots:
            reason = f" — {escape(slot['reason'])}" if slot.get("reason") else ""
            lines.append(f"• {short_date(slot['date'])}, {slot['start_time']}–{slot['end_time']}{reason}")
    if not dates and not slots:
        lines.append("Пока ничего не закрыто.")
    return "\n".join(lines)


def format_services_block(
    services: list[dict[str, Any]],
    prices: bool = False,
    durations: bool = False,
) -> str:
    if not services:
        return "💅 Услуги: не указаны"
    lines = ["💅 <b>Услуги:</b>"]
    for service in services:
        details = []
        if prices:
            details.append(format_money(service.get("price", 0)))
        if durations:
            details.append(f"{service.get('duration_min', 0)} мин")
        suffix = f" — {', '.join(details)}" if details else ""
        lines.append(f"• {escape(service.get('title', 'Услуга'))}{suffix}")
    return "\n".join(lines)


def format_services_inline(services: list[dict[str, Any]]) -> str:
    if not services:
        return "Услуги не указаны"
    return ", ".join(service.get("title", "Услуга") for service in services)


def format_money(value: Any) -> str:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        amount = 0
    return f"{amount} ₽"
