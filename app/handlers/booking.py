from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import BotConfig
from app.keyboards import (
    admin_booking_notice_kb,
    booking_calendar_kb,
    confirm_booking_kb,
    contact_request_kb,
    main_menu_kb,
    services_kb,
    time_slots_kb,
)
from app.permissions import notification_recipients
from app.schedule import TIME_SLOTS, calculate_end_time, human_date, is_workday, today_in
from app.states import BookingStates
from app.storage import JsonStore
from app.texts import (
    MENU_BACK,
    MENU_BOOK,
    admin_booking_notice,
    ask_contact_text,
    booking_card,
    booking_intro,
    booking_success,
    home_text,
    selected_services_text,
    user_payload,
)


router = Router()
logger = logging.getLogger(__name__)
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{6,}\d)")


@router.message(F.text == MENU_BOOK)
async def booking_from_menu(message: Message, state: FSMContext, store: JsonStore) -> None:
    await show_services(message, state, store)


@router.callback_query(F.data == "book:start")
async def booking_from_callback(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await show_services(callback.message, state, store)
    await callback.answer()


@router.callback_query(F.data == "book:services")
async def booking_services_back(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    services = await store.list_services()
    data = await state.get_data()
    selected_ids = list(data.get("selected_service_ids", []))
    await state.set_state(BookingStates.choosing_services)
    await callback.message.edit_text(
        selected_services_text(services, selected_ids),
        reply_markup=services_kb(services, selected_ids),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("book:svc:"))
async def toggle_service(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    service_id = callback.data.removeprefix("book:svc:")
    services = await store.list_services()
    if not any(item["id"] == service_id for item in services):
        await callback.answer("Услуга недоступна", show_alert=True)
        return

    data = await state.get_data()
    selected_ids = list(data.get("selected_service_ids", []))
    if service_id in selected_ids:
        selected_ids.remove(service_id)
    else:
        selected_ids.append(service_id)
    await state.update_data(selected_service_ids=selected_ids)
    await state.set_state(BookingStates.choosing_services)
    await callback.message.edit_text(
        selected_services_text(services, selected_ids),
        reply_markup=services_kb(services, selected_ids),
    )
    await callback.answer()


@router.callback_query(F.data == "book:clear")
async def clear_services(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    services = await store.list_services()
    await state.update_data(selected_service_ids=[])
    await state.set_state(BookingStates.choosing_services)
    await callback.message.edit_text(selected_services_text(services, []), reply_markup=services_kb(services, []))
    await callback.answer("Выбор очищен")


@router.callback_query(F.data == "book:continue")
async def continue_to_date(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    selected = await selected_services_from_state(state, store)
    if not selected:
        await callback.answer("Выберите хотя бы одну услугу", show_alert=True)
        return
    await state.update_data(services=selected)
    await state.set_state(BookingStates.choosing_date)
    await send_calendar(callback, state, store, config)


@router.callback_query(F.data.startswith("book:month:"))
async def change_booking_month(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    await send_calendar(callback, state, store, config)


@router.callback_query(F.data == "book:change_date")
async def change_booking_date(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    await state.set_state(BookingStates.choosing_date)
    await send_calendar(callback, state, store, config)


@router.callback_query(F.data.startswith("book:date:"))
async def choose_date(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    date_iso = callback.data.removeprefix("book:date:")
    selected_date = date.fromisoformat(date_iso)
    today = today_in(config.timezone)
    horizon_end = today + timedelta(days=config.booking_horizon_days)
    blocked_dates = set(await store.list_blocked_dates())
    selected = await selected_services_from_state(state, store)
    duration = total_duration(selected)

    if selected_date < today or selected_date > horizon_end or not is_workday(selected_date):
        await callback.answer("Эта дата недоступна для записи", show_alert=True)
        return

    statuses = await store.time_slot_statuses(date_iso, duration)
    available_slots = [slot for slot, status in statuses.items() if status == "available"]
    if date_iso in blocked_dates or not available_slots:
        await callback.answer("На эту дату уже нет свободных окон", show_alert=True)
        return

    await state.update_data(date=date_iso)
    await state.set_state(BookingStates.choosing_time)
    await callback.message.edit_text(
        f"<b>{human_date(date_iso)}</b>\n"
        "Выберите свободное время.\n"
        f"Длительность выбранных услуг: <b>{duration} мин</b>.\n"
        "× — причина указана на кнопке.",
        reply_markup=time_slots_kb(available_slots, unavailable_reasons=statuses),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("book:time:"))
async def choose_time(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    time_slot = callback.data.removeprefix("book:time:")
    if time_slot not in TIME_SLOTS:
        await callback.answer("Это время недоступно", show_alert=True)
        return

    data = await state.get_data()
    date_iso = data.get("date")
    if not date_iso:
        await callback.answer("Сначала выберите дату", show_alert=True)
        return

    selected = await selected_services_from_state(state, store)
    duration = total_duration(selected)
    available_slots = await store.available_time_slots(date_iso, duration)
    if time_slot not in available_slots:
        await callback.answer("Это время уже заняли или запись не помещается", show_alert=True)
        return

    await state.update_data(time=time_slot, start_time=time_slot, end_time=calculate_end_time(time_slot, duration), services=selected)
    await state.set_state(BookingStates.waiting_contact)
    await callback.message.answer(ask_contact_text(), reply_markup=contact_request_kb())
    await callback.answer()


@router.message(BookingStates.waiting_contact)
async def capture_contact(message: Message, state: FSMContext) -> None:
    if message.text == MENU_BACK:
        await state.clear()
        await message.answer("Вернула в меню.", reply_markup=main_menu_kb())
        return

    name, phone = extract_contact(message)
    if not phone:
        await message.answer("Не вижу телефон. Отправьте контакт кнопкой или напишите имя и номер одним сообщением.")
        return

    await state.update_data(client_name=name, client_phone=phone)
    await state.set_state(BookingStates.confirming)
    data = await state.get_data()
    await message.answer(booking_card(data), reply_markup=confirm_booking_kb())


@router.callback_query(F.data == "book:confirm")
async def confirm_booking(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    data = await state.get_data()
    required = {"selected_service_ids", "date", "time", "client_name", "client_phone"}
    if not required.issubset(data):
        await callback.answer("Данные записи устарели. Начните заново.", show_alert=True)
        await state.clear()
        return

    services = await selected_services_from_state(state, store)
    if not services:
        await callback.answer("Выбранные услуги больше недоступны. Начните заново.", show_alert=True)
        await state.clear()
        return

    duration = total_duration(services)
    start_time = data["time"]
    end_time = calculate_end_time(start_time, duration)
    booking = await store.create_booking_if_free(
        {
            "date": data["date"],
            "start_time": start_time,
            "end_time": end_time,
            "total_duration_min": duration,
            "total_price": total_price(services),
            "services": services,
            "client": telegram_client(callback.from_user),
            "contact": {
                "name": data["client_name"],
                "phone": data["client_phone"],
            },
            "notes": "",
        }
    )
    if booking is None:
        await callback.message.answer(
            "Это время уже недоступно. Пожалуйста, выберите другое окно.",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        await callback.answer("Слот занят", show_alert=True)
        return

    await state.clear()
    await callback.message.answer(booking_success(booking), reply_markup=main_menu_kb())
    for admin_id in await notification_recipients(store, config):
        try:
            await callback.bot.send_message(
                admin_id,
                admin_booking_notice(booking),
                reply_markup=admin_booking_notice_kb(booking),
            )
        except TelegramAPIError as exc:
            logger.warning("Could not notify admin %s: %s", admin_id, exc)
    await callback.answer("Запись подтверждена")


@router.callback_query(F.data == "book:cancel")
async def cancel_booking(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    await state.clear()
    await callback.message.answer(
        f"Запись отменена.\n\n{home_text(config.brand_name)}",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


async def show_services(message: Message, state: FSMContext, store: JsonStore) -> None:
    services = await store.list_services()
    await state.clear()
    if not services:
        await message.answer("Сейчас нет активных услуг для записи. Пожалуйста, попробуйте позже.", reply_markup=main_menu_kb())
        return
    await state.update_data(selected_service_ids=[])
    await state.set_state(BookingStates.choosing_services)
    await message.answer(f"{booking_intro()}\n\n{selected_services_text(services, [])}", reply_markup=services_kb(services, []))


async def send_calendar(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    current_month = callback.data.removeprefix("book:month:") if callback.data and callback.data.startswith("book:month:") else None
    today = today_in(config.timezone)
    horizon_end = today + timedelta(days=config.booking_horizon_days)
    year, month = (map(int, current_month.split("-")) if current_month else (today.year, today.month))
    selected = await selected_services_from_state(state, store)
    duration = total_duration(selected)
    blocked_dates = set(await store.list_blocked_dates())
    unavailable_by_date = await unavailable_slots_map(store, today, horizon_end, duration)
    markup = booking_calendar_kb(year, month, today, horizon_end, unavailable_by_date, blocked_dates)
    await callback.message.edit_text(
        "Выберите дату.\n\n"
        "Обычные числа — доступные дни.\n"
        "× — мест нет или дата закрыта.\n"
        "· — выходной.",
        reply_markup=markup,
    )
    await callback.answer()


async def unavailable_slots_map(store: JsonStore, start: date, end: date, duration_min: int) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    current = start
    while current <= end:
        day = current.isoformat()
        available = set(await store.available_time_slots(day, duration_min))
        result[day] = {slot for slot in TIME_SLOTS if slot not in available}
        current += timedelta(days=1)
    return result


async def selected_services_from_state(state: FSMContext, store: JsonStore) -> list[dict[str, Any]]:
    data = await state.get_data()
    selected_ids = list(data.get("selected_service_ids", []))
    services = await store.list_services()
    by_id = {item["id"]: item for item in services}
    return [by_id[service_id] for service_id in selected_ids if service_id in by_id]


def booked_dates_map(bookings: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for booking in bookings:
        if booking.get("status") != "confirmed":
            continue
        time_slot = booking.get("start_time") or booking.get("time")
        if time_slot in TIME_SLOTS:
            result.setdefault(booking["date"], set()).add(time_slot)
    return result


def extract_contact(message: Message) -> tuple[str, str | None]:
    if message.contact:
        name = " ".join(filter(None, [message.contact.first_name, message.contact.last_name])).strip()
        if not name:
            name = message.from_user.full_name if message.from_user else "Клиент"
        return name, message.contact.phone_number

    text = (message.text or "").strip()
    match = PHONE_RE.search(text)
    if not match:
        return text or "Клиент", None

    phone = match.group(1).strip()
    name = text.replace(match.group(1), "").replace(",", " ").strip()
    if not name and message.from_user:
        name = message.from_user.full_name
    return name or "Клиент", phone


def telegram_client(user: Any) -> dict[str, Any]:
    payload = user_payload(user)
    display_name = " ".join(part for part in [payload.get("first_name"), payload.get("last_name")] if part).strip()
    return {
        "telegram_id": payload["telegram_id"],
        "username": payload.get("username") or "",
        "first_name": payload.get("first_name") or "",
        "last_name": payload.get("last_name") or "",
        "display_name": display_name or payload.get("username") or f"id {payload['telegram_id']}",
    }


def total_duration(services: list[dict[str, Any]]) -> int:
    return sum(int(item.get("duration_min", 0)) for item in services)


def total_price(services: list[dict[str, Any]]) -> int:
    return sum(int(item.get("price", 0)) for item in services)
