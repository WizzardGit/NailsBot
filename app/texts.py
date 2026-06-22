from __future__ import annotations

from html import escape
from typing import Any

from app.schedule import human_date


MENU_BOOK = "🗓 Записаться"
MENU_PORTFOLIO = "🖼 Примеры работ"
MENU_REVIEWS = "⭐ Отзывы"
MENU_FAQ = "❓ FAQ"
MENU_CONTACTS = "📍 Контакты"
MENU_SERVICES = "💅 Услуги"
MENU_BACK = "↩️ В меню"


def user_payload(user: Any) -> dict[str, Any]:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
    }


def welcome_text(brand_name: str) -> str:
    return (
        f"<b>{escape(brand_name)}</b>\n\n"
        "Привет! Я помогу быстро выбрать услугу, посмотреть работы мастера и записаться на удобное время.\n\n"
        "Подскажите, пожалуйста, откуда вы о нас узнали?"
    )


def home_text(brand_name: str) -> str:
    return (
        f"<b>{escape(brand_name)}</b>\n"
        "Ниже главное меню. Можно сразу записаться, посмотреть портфолио, отзывы или уточнить детали перед визитом."
    )


def services_text(services: list[dict[str, Any]]) -> str:
    lines = ["<b>Услуги и стоимость</b>", "Цены для демо можно менять в <code>data/services.json</code>.", ""]
    for service in services:
        lines.append(
            f"• <b>{escape(service['title'])}</b> — {service['price']} ₽, {service['duration_min']} мин\n"
            f"  {escape(service['description'])}"
        )
    return "\n".join(lines)


def booking_intro() -> str:
    return (
        "<b>Запись</b>\n"
        "Выберите услугу, затем дату и свободное время. После подтверждения мастер получит уведомление с вашими данными."
    )


def ask_contact_text() -> str:
    return (
        "<b>Почти готово</b>\n"
        "Отправьте имя и телефон одним сообщением, например:\n"
        "<code>Анна, +7 999 123-45-67</code>"
    )


def booking_card(data: dict[str, Any]) -> str:
    service = data["service"]
    return (
        "<b>Проверьте запись</b>\n\n"
        f"Услуга: <b>{escape(service['title'])}</b>\n"
        f"Дата: <b>{human_date(data['date'])}</b>\n"
        f"Время: <b>{escape(data['time'])}</b>\n"
        f"Стоимость: <b>{service['price']} ₽</b>\n"
        f"Длительность: <b>{service['duration_min']} мин</b>\n\n"
        f"Имя: <b>{escape(data['client_name'])}</b>\n"
        f"Телефон: <b>{escape(data['client_phone'])}</b>"
    )


def booking_success(booking: dict[str, Any]) -> str:
    service = booking["service"]
    return (
        "<b>Вы записаны</b>\n\n"
        f"{escape(service['title'])}\n"
        f"{human_date(booking['date'])} в {escape(booking['time'])}\n\n"
        "Напомним о визите заранее. Если нужно перенести запись, напишите мастеру через раздел «Контакты»."
    )


def admin_booking_notice(booking: dict[str, Any]) -> str:
    user = booking.get("telegram_user", {})
    username = user.get("username")
    profile = f"@{username}" if username else f"id {user.get('id')}"
    service = booking["service"]
    return (
        "<b>Новая запись</b>\n\n"
        f"{escape(service['title'])}\n"
        f"{human_date(booking['date'])} в {escape(booking['time'])}\n"
        f"Клиент: {escape(booking['client_name'])}\n"
        f"Телефон: {escape(booking['client_phone'])}\n"
        f"Telegram: {escape(profile)}"
    )


def format_booking_list(title: str, bookings: list[dict[str, Any]]) -> str:
    if not bookings:
        return f"<b>{escape(title)}</b>\n\nЗаписей нет."

    lines = [f"<b>{escape(title)}</b>", ""]
    for booking in bookings:
        service = booking["service"]
        lines.append(
            f"• {human_date(booking['date'])}, {escape(booking['time'])}\n"
            f"  {escape(service['title'])} — {escape(booking['client_name'])}, {escape(booking['client_phone'])}"
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
        "<b>Статистика</b>",
        f"Записей: <b>{stats['bookings_total']}</b>",
        f"Ответов на входной вопрос: <b>{stats['leads_total']}</b>",
        "",
        "<b>Откуда пришли</b>",
    ]
    if stats["sources"]:
        for source, count in sorted(stats["sources"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"• {escape(source)} — {count}")
    else:
        lines.append("Пока нет данных.")
    return "\n".join(lines)

