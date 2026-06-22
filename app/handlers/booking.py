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
    booking_calendar_kb,
    confirm_booking_kb,
    contact_request_kb,
    main_menu_kb,
    services_kb,
    time_slots_kb,
)
from app.schedule import TIME_SLOTS, human_date, is_workday, today_in
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
    services = await store.load("services.json", [])
    await state.set_state(BookingStates.choosing_service)
    await callback.message.edit_text(booking_intro(), reply_markup=services_kb(services))
    await callback.answer()


@router.callback_query(F.data.startswith("book:service:"))
async def choose_service(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    service_id = callback.data.removeprefix("book:service:")
    services = await store.load("services.json", [])
    service = next((item for item in services if item["id"] == service_id), None)
    if service is None:
        await callback.answer("Услуга не найдена", show_alert=True)
        return

    await state.update_data(service=service)
    await state.set_state(BookingStates.choosing_date)
    await send_calendar(callback, store, config)


@router.callback_query(F.data.startswith("book:month:"))
async def change_booking_month(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    await send_calendar(callback, store, config)


@router.callback_query(F.data == "book:change_date")
async def change_booking_date(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    await state.set_state(BookingStates.choosing_date)
    await send_calendar(callback, store, config)


@router.callback_query(F.data.startswith("book:date:"))
async def choose_date(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    date_iso = callback.data.removeprefix("book:date:")
    selected_date = date.fromisoformat(date_iso)
    today = today_in(config.timezone)
    horizon_end = today + timedelta(days=config.booking_horizon_days)
    blocked_dates = set(await store.load("blocked_dates.json", []))
    booked_times = await store.booked_times(date_iso)

    if selected_date < today or selected_date > horizon_end or not is_workday(selected_date):
        await callback.answer("Эта дата недоступна для записи", show_alert=True)
        return

    if date_iso in blocked_dates or len(booked_times) >= len(TIME_SLOTS):
        await callback.answer("На эту дату уже нет свободных окон", show_alert=True)
        return

    await state.update_data(date=date_iso)
    await state.set_state(BookingStates.choosing_time)
    await callback.message.edit_text(
        f"<b>{human_date(date_iso)}</b>\n"
        "Выберите свободное время.\n"
        "× — время уже занято.",
        reply_markup=time_slots_kb(booked_times),
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

    booked_times = await store.booked_times(date_iso)
    if time_slot in booked_times:
        await callback.answer("Это время уже заняли", show_alert=True)
        return

    await state.update_data(time=time_slot)
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
    required = {"service", "date", "time", "client_name", "client_phone"}
    if not required.issubset(data):
        await callback.answer("Данные записи устарели. Начните заново.", show_alert=True)
        await state.clear()
        return

    if data["time"] not in TIME_SLOTS:
        await callback.answer("Время записи некорректно. Выберите слот заново.", show_alert=True)
        await state.clear()
        return

    booking = await store.add_booking_if_free(
        {
            "service": data["service"],
            "date": data["date"],
            "time": data["time"],
            "client_name": data["client_name"],
            "client_phone": data["client_phone"],
            "telegram_user": user_payload(callback.from_user),
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
    if config.master_chat_id is not None:
        try:
            await callback.bot.send_message(config.master_chat_id, admin_booking_notice(booking))
        except TelegramAPIError as exc:
            logger.warning("Could not notify master chat %s: %s", config.master_chat_id, exc)
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
    services = await store.load("services.json", [])
    await state.set_state(BookingStates.choosing_service)
    await message.answer(booking_intro(), reply_markup=services_kb(services))


async def send_calendar(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    current_month = callback.data.removeprefix("book:month:") if callback.data and callback.data.startswith("book:month:") else None
    today = today_in(config.timezone)
    horizon_end = today + timedelta(days=config.booking_horizon_days)
    year, month = (map(int, current_month.split("-")) if current_month else (today.year, today.month))
    bookings = await store.load("bookings.json", [])
    blocked_dates = set(await store.load("blocked_dates.json", []))
    booked_by_date = booked_dates_map(bookings)
    markup = booking_calendar_kb(year, month, today, horizon_end, booked_by_date, blocked_dates)
    await callback.message.edit_text(
        "Выберите дату.\n\n"
        "Обычные числа — доступные дни.\n"
        "× — мест нет или дата закрыта.\n"
        "· — выходной.\n"
        "Пустые клетки — прошедшие даты или даты вне периода записи.",
        reply_markup=markup,
    )
    await callback.answer()


def booked_dates_map(bookings: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for booking in bookings:
        if booking.get("status") != "confirmed":
            continue
        time_slot = booking.get("time")
        if time_slot not in TIME_SLOTS:
            continue
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
