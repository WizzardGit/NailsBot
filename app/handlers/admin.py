from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, timedelta
from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import BotConfig
from app.keyboards import (
    admin_back_kb,
    admin_booking_card_kb,
    admin_booking_list_kb,
    admin_menu_kb,
    admin_services_list_kb,
    admin_services_menu_kb,
    admins_manage_kb,
    blocked_menu_kb,
    booking_calendar_kb,
    cancel_booking_choice_kb,
    client_card_kb,
    clients_list_kb,
    clients_menu_kb,
    export_kb,
    role_select_kb,
    service_confirm_kb,
    service_edit_kb,
    time_slots_kb,
)
from app.permissions import can_manage_roles, has_permission
from app.schedule import TIME_SLOTS, calculate_end_time, human_date, parse_time_to_minutes, short_date, today_in
from app.states import AdminBlockedStates, AdminBookingStates, AdminRoleStates, AdminServiceStates, ClientSearchStates
from app.storage import JsonStore
from app.texts import (
    admin_booking_card,
    admins_text,
    blocked_list_text,
    client_card_text,
    format_booking_list,
    format_money,
    format_services_inline,
    service_card_text,
    stats_text,
)


router = Router()
logger = logging.getLogger(__name__)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


@router.message(Command("admin"))
async def admin_command(message: Message, store: JsonStore) -> None:
    await store.touch_admin_profile(message.from_user)
    role = await store.get_user_role(message.from_user.id if message.from_user else None)
    if role is None:
        await message.answer("Панель мастера недоступна.")
        return
    await message.answer("<b>💅 Панель мастера</b>\n\nВыберите действие:", reply_markup=admin_menu_kb(role))


@router.message(Command("admins"))
async def admins_command(message: Message, store: JsonStore) -> None:
    await store.touch_admin_profile(message.from_user)
    role = await store.get_user_role(message.from_user.id if message.from_user else None)
    if role is None:
        await message.answer("Недоступно.")
        return
    await message.answer(admins_text(await store.get_admins()), reply_markup=admin_back_kb())


@router.message(Command("setrole"))
async def setrole_command(message: Message, store: JsonStore) -> None:
    if not await can_manage_roles(message.from_user.id if message.from_user else None, store):
        await message.answer("Команда доступна только owner.")
        return

    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Формат: <code>/setrole telegram_id role</code>\nРоли: super_admin, admin, viewer.")
        return
    try:
        telegram_id = int(parts[1])
    except ValueError:
        await message.answer("telegram_id должен быть числом.")
        return

    ok, text = await store.set_role(telegram_id, parts[2], message.from_user)
    await message.answer(text)


@router.callback_query(F.data == "adm:menu")
async def admin_menu(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await state.clear()
    role = await store.get_user_role(callback.from_user.id)
    if role is None:
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.message.edit_text("<b>💅 Панель мастера</b>\n\nВыберите действие:", reply_markup=admin_menu_kb(role))
    await callback.answer()


@router.callback_query(F.data.in_({"adm:b:today", "adm:b:tomorrow", "adm:b:week"}))
async def admin_booking_period(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "view_bookings"):
        return
    start = today_in(config.timezone)
    if callback.data == "adm:b:today":
        end = start
        title = "Записи на сегодня"
    elif callback.data == "adm:b:tomorrow":
        start = start + timedelta(days=1)
        end = start
        title = "Записи на завтра"
    else:
        end = start + timedelta(days=7)
        title = "Записи на ближайшие 7 дней"
    await show_bookings_range(callback, store, title, start.isoformat(), end.isoformat())


@router.callback_query(F.data == "adm:b:pick")
async def admin_pick_date(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "view_bookings"):
        return
    await send_admin_pick_calendar(callback, store, config)


@router.callback_query(F.data.startswith("adm:b:pick:month:"))
async def admin_pick_month(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "view_bookings"):
        return
    await send_admin_pick_calendar(callback, store, config)


@router.callback_query(F.data.startswith("adm:b:pick:date:"))
async def admin_pick_date_show(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "view_bookings"):
        return
    day = callback.data.rsplit(":", 1)[1]
    await show_bookings_range(callback, store, f"Записи на {short_date(day)}", day, day)


@router.callback_query(F.data.startswith("adm:b:view:"))
async def admin_view_booking(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "view_bookings"):
        return
    booking_id = callback.data.rsplit(":", 1)[1]
    booking = await store.get_booking(booking_id)
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    await callback.message.edit_text(admin_booking_card(booking), reply_markup=admin_booking_card_kb(booking))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:b:contact:"))
async def admin_contact_hint(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "view_bookings"):
        return
    booking = await store.get_booking(callback.data.rsplit(":", 1)[1])
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    phone = booking.get("contact", {}).get("phone") or "телефон не указан"
    await callback.answer(f"У клиента нет username. Связаться можно по телефону: {phone}", show_alert=True)


@router.callback_query(F.data.startswith("adm:b:cancel:"))
async def admin_cancel_booking_prompt(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    booking_id = callback.data.rsplit(":", 1)[1]
    booking = await store.get_booking(booking_id)
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    name = booking.get("contact", {}).get("name") or "клиент"
    await callback.message.edit_text(
        f"Точно отменить запись {escape(name)} на {short_date(booking['date'])} {booking['start_time']}?\n\n"
        "Можно отправить клиенту стандартное уведомление или написать причину вручную.",
        reply_markup=cancel_booking_choice_kb(booking_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:b:cancelauto:"))
async def admin_cancel_booking_auto(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    booking_id = callback.data.rsplit(":", 1)[1]
    booking = await store.cancel_booking(booking_id)
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    warning = await notify_client(
        callback,
        booking,
        f"Ваша запись на {short_date(booking['date'])} в {booking['start_time']} была отменена мастером.\n"
        "Напишите мастеру, чтобы узнать подробности или подобрать новое время.",
    )
    await callback.message.edit_text(f"Запись отменена.{warning}", reply_markup=admin_back_kb())
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("adm:b:cancelreason:"))
async def admin_cancel_booking_reason_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    booking_id = callback.data.rsplit(":", 1)[1]
    if await store.get_booking(booking_id) is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    await state.update_data(cancel_booking_id=booking_id)
    await state.set_state(AdminBookingStates.waiting_cancel_reason)
    await callback.message.edit_text(
        "Напишите текст, который получит клиент при отмене записи:",
        reply_markup=admin_back_kb(f"adm:b:view:{booking_id}"),
    )
    await callback.answer()


@router.message(AdminBookingStates.waiting_cancel_reason)
async def admin_cancel_booking_with_reason(message: Message, state: FSMContext, store: JsonStore) -> None:
    if not await has_permission(message.from_user.id if message.from_user else None, "manage_bookings", store):
        await message.answer("Недоступно.")
        await state.clear()
        return
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("Причина не должна быть пустой.")
        return
    data = await state.get_data()
    booking = await store.cancel_booking(data.get("cancel_booking_id", ""))
    await state.clear()
    if booking is None:
        await message.answer("Запись не найдена.", reply_markup=admin_back_kb())
        return
    warning = await notify_client(
        message,
        booking,
        f"Ваша запись на {short_date(booking['date'])} в {booking['start_time']} была отменена мастером.\n\n"
        f"{reason}",
    )
    await message.answer(f"Запись отменена.{warning}", reply_markup=admin_back_kb())


@router.callback_query(F.data.startswith("adm:b:done:"))
async def admin_complete_booking(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    booking = await store.complete_booking(callback.data.rsplit(":", 1)[1])
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    await callback.message.edit_text("Запись отмечена выполненной.", reply_markup=admin_back_kb())
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("adm:b:res:"))
async def admin_reschedule_start(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    booking_id = callback.data.rsplit(":", 1)[1]
    booking = await store.get_booking(booking_id)
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    await state.update_data(reschedule_booking_id=booking_id, old_date=booking["date"], old_time=booking["start_time"])
    await state.set_state(AdminBookingStates.choosing_reschedule_date)
    await send_reschedule_calendar(callback, state, store, config, booking)


@router.callback_query(F.data.startswith("adm:b:r:month:"))
async def admin_reschedule_month(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    data = await state.get_data()
    booking = await store.get_booking(data.get("reschedule_booking_id", ""))
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    await send_reschedule_calendar(callback, state, store, config, booking)


@router.callback_query(F.data.startswith("adm:b:r:date:"))
async def admin_reschedule_date(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    data = await state.get_data()
    booking = await store.get_booking(data.get("reschedule_booking_id", ""))
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    day = callback.data.rsplit(":", 1)[1]
    duration = int(booking.get("total_duration_min", 60))
    available = await store.available_time_slots(day, duration, exclude_booking_id=booking["id"])
    if not available:
        await callback.answer("На эту дату нет свободного времени", show_alert=True)
        return
    await state.update_data(new_date=day)
    await state.set_state(AdminBookingStates.choosing_reschedule_time)
    await callback.message.edit_text(
        f"<b>{human_date(day)}</b>\nВыберите новое время:",
        reply_markup=time_slots_kb(available, callback_prefix="adm:b:restime", back_callback=f"adm:b:res:{booking['id']}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:b:restime:"))
async def admin_reschedule_time(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    new_time = callback.data.removeprefix("adm:b:restime:")
    data = await state.get_data()
    booking = await store.get_booking(data.get("reschedule_booking_id", ""))
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    new_date = data.get("new_date")
    if not new_date:
        await callback.answer("Сначала выберите дату", show_alert=True)
        return
    end_time = calculate_end_time(new_time, int(booking.get("total_duration_min", 60)))
    await state.update_data(new_time=new_time)
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Перенести", callback_data="adm:b:resok")
    builder.button(text="⬅️ Назад", callback_data=f"adm:b:view:{booking['id']}")
    builder.adjust(1)
    await callback.message.edit_text(
        f"Перенести запись?\n\n"
        f"Было: {short_date(booking['date'])} {booking['start_time']}\n"
        f"Стало: {short_date(new_date)} {new_time}–{end_time}",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:b:resok")
async def admin_reschedule_confirm(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_bookings"):
        return
    data = await state.get_data()
    booking_id = data.get("reschedule_booking_id")
    new_date = data.get("new_date")
    new_time = data.get("new_time")
    if not booking_id or not new_date or not new_time:
        await callback.answer("Данные переноса устарели", show_alert=True)
        await state.clear()
        return
    old_date = data.get("old_date", "")
    old_time = data.get("old_time", "")
    booking, ok = await store.reschedule_booking(booking_id, new_date, new_time)
    if booking is None:
        await callback.answer("Запись не найдена", show_alert=True)
        await state.clear()
        return
    if not ok:
        await callback.answer("Новое время уже занято", show_alert=True)
        return
    warning = await notify_client(
        callback,
        booking,
        f"Ваша запись перенесена:\nБыло: {short_date(old_date)} {old_time}\nСтало: {short_date(new_date)} {new_time}",
    )
    await state.clear()
    await callback.message.edit_text(f"Запись перенесена.{warning}", reply_markup=admin_back_kb())
    await callback.answer("Перенесено")


@router.callback_query(F.data == "adm:s:menu")
async def admin_services_menu(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await state.clear()
    if not await require_permission(callback, store, "manage_services"):
        return
    await callback.message.edit_text("<b>💅 Услуги и цены</b>", reply_markup=admin_services_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:s:list")
async def admin_services_list(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_services"):
        return
    services = await store.list_services(include_inactive=True)
    await callback.message.edit_text("<b>📋 Список услуг</b>", reply_markup=admin_services_list_kb(services))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:s:edit:"))
async def admin_service_edit(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_services"):
        return
    service = await store.get_service(callback.data.rsplit(":", 1)[1])
    if service is None:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    await callback.message.edit_text(service_card_text(service), reply_markup=service_edit_kb(service))
    await callback.answer()


@router.callback_query(F.data == "adm:s:add")
async def admin_service_add_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_services"):
        return
    await state.clear()
    await state.set_state(AdminServiceStates.waiting_title)
    await callback.message.edit_text("Введите название услуги:", reply_markup=admin_back_kb("adm:s:menu"))
    await callback.answer()


@router.message(AdminServiceStates.waiting_title)
async def admin_service_add_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не должно быть пустым.")
        return
    await state.update_data(title=title)
    await state.set_state(AdminServiceStates.waiting_price)
    await message.answer("Введите цену числом, например 2500:")


@router.message(AdminServiceStates.waiting_price)
async def admin_service_add_price(message: Message, state: FSMContext) -> None:
    price = parse_non_negative_int(message.text)
    if price is None:
        await message.answer("Цена должна быть числом >= 0.")
        return
    await state.update_data(price=price)
    await state.set_state(AdminServiceStates.waiting_duration)
    await message.answer("Введите длительность в минутах:")


@router.message(AdminServiceStates.waiting_duration)
async def admin_service_add_duration(message: Message, state: FSMContext) -> None:
    duration = parse_positive_int(message.text)
    if duration is None:
        await message.answer("Длительность должна быть числом больше 0.")
        return
    await state.update_data(duration_min=duration)
    await state.set_state(AdminServiceStates.waiting_description)
    await message.answer("Введите описание услуги:")


@router.message(AdminServiceStates.waiting_description)
async def admin_service_add_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    data = await state.get_data()
    await state.set_state(AdminServiceStates.confirming_add)
    await message.answer(
        f"<b>Проверьте услугу</b>\n\n"
        f"Название: <b>{escape(data['title'])}</b>\n"
        f"Цена: <b>{format_money(data['price'])}</b>\n"
        f"Длительность: <b>{data['duration_min']} мин</b>\n"
        f"Описание: {escape(data.get('description') or '')}",
        reply_markup=service_confirm_kb(),
    )


@router.callback_query(F.data == "adm:s:add:save")
async def admin_service_add_save(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_services"):
        return
    data = await state.get_data()
    service = await store.add_service(data["title"], data["price"], data["duration_min"], data.get("description", ""))
    await state.clear()
    await callback.message.edit_text(service_card_text(service), reply_markup=service_edit_kb(service))
    await callback.answer("Услуга добавлена")


@router.callback_query(F.data.startswith("adm:s:title:"))
async def admin_service_edit_title_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await start_service_edit_field(callback, state, store, "editing_title", "Введите новое название:")


@router.callback_query(F.data.startswith("adm:s:price:"))
async def admin_service_edit_price_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await start_service_edit_field(callback, state, store, "editing_price", "Введите новую цену:")


@router.callback_query(F.data.startswith("adm:s:dur:"))
async def admin_service_edit_duration_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await start_service_edit_field(callback, state, store, "editing_duration", "Введите новую длительность в минутах:")


@router.callback_query(F.data.startswith("adm:s:desc:"))
async def admin_service_edit_description_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await start_service_edit_field(callback, state, store, "editing_description", "Введите новое описание:")


@router.message(AdminServiceStates.editing_title)
async def admin_service_edit_title(message: Message, state: FSMContext, store: JsonStore) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не должно быть пустым.")
        return
    await finish_service_update(message, state, store, title=title)


@router.message(AdminServiceStates.editing_price)
async def admin_service_edit_price(message: Message, state: FSMContext, store: JsonStore) -> None:
    price = parse_non_negative_int(message.text)
    if price is None:
        await message.answer("Цена должна быть числом >= 0.")
        return
    await finish_service_update(message, state, store, price=price)


@router.message(AdminServiceStates.editing_duration)
async def admin_service_edit_duration(message: Message, state: FSMContext, store: JsonStore) -> None:
    duration = parse_positive_int(message.text)
    if duration is None:
        await message.answer("Длительность должна быть числом больше 0.")
        return
    await finish_service_update(message, state, store, duration_min=duration)


@router.message(AdminServiceStates.editing_description)
async def admin_service_edit_description(message: Message, state: FSMContext, store: JsonStore) -> None:
    await finish_service_update(message, state, store, description=(message.text or "").strip())


@router.callback_query(F.data.startswith("adm:s:toggle:"))
async def admin_service_toggle(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_services"):
        return
    service = await store.get_service(callback.data.rsplit(":", 1)[1])
    if service is None:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    service = await store.update_service(service["id"], active=not service.get("active", True))
    await callback.message.edit_text(service_card_text(service), reply_markup=service_edit_kb(service))
    await callback.answer("Сохранено")


@router.callback_query(F.data.startswith("adm:s:del:"))
async def admin_service_delete(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_services"):
        return
    deleted, service = await store.delete_service_if_unused(callback.data.rsplit(":", 1)[1])
    if service is None:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    text = "Услуга удалена." if deleted else "Услуга уже встречалась в записях, поэтому она скрыта для новых клиентов."
    await callback.message.edit_text(text, reply_markup=admin_back_kb("adm:s:list"))
    await callback.answer()


@router.callback_query(F.data == "adm:clients")
async def admin_clients_menu(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await state.clear()
    if not await require_permission(callback, store, "manage_clients"):
        return
    await callback.message.edit_text("<b>👥 Клиенты</b>", reply_markup=clients_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:c:list")
async def admin_clients_list(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_clients"):
        return
    clients = await store.list_clients()
    text = clients_results_text("Последние клиенты", clients)
    await callback.message.edit_text(text, reply_markup=clients_list_kb(clients))
    await callback.answer()


@router.callback_query(F.data == "adm:c:search")
async def admin_clients_search_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_clients"):
        return
    await state.set_state(ClientSearchStates.waiting_query)
    await callback.message.edit_text("Введите имя, телефон, username или Telegram ID:", reply_markup=admin_back_kb("adm:clients"))
    await callback.answer()


@router.message(ClientSearchStates.waiting_query)
async def admin_clients_search(message: Message, state: FSMContext, store: JsonStore) -> None:
    if not await has_permission(message.from_user.id if message.from_user else None, "manage_clients", store):
        await message.answer("Недоступно.")
        await state.clear()
        return
    clients = await store.find_clients(message.text or "")
    await state.clear()
    text = clients_results_text("Результаты поиска", clients)
    await message.answer(text, reply_markup=clients_list_kb(clients, back_callback="adm:clients"))


@router.callback_query(F.data.startswith("adm:c:view:"))
async def admin_client_view(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_clients"):
        return
    client = await store.get_client(int(callback.data.rsplit(":", 1)[1]))
    if client is None:
        await callback.answer("Клиент не найден", show_alert=True)
        return
    can_delete = await has_permission(callback.from_user.id if callback.from_user else None, "manage_roles", store)
    await callback.message.edit_text(client_card_text(client), reply_markup=client_card_kb(client, can_delete=can_delete))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:c:del:"))
async def admin_client_delete_prompt(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_roles"):
        return
    telegram_id = int(callback.data.rsplit(":", 1)[1])
    client = await store.get_client(telegram_id)
    if client is None:
        await callback.answer("Клиент не найден", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data=f"adm:c:delok:{telegram_id}")
    builder.button(text="Нет, назад", callback_data=f"adm:c:view:{telegram_id}")
    builder.adjust(1)
    await callback.message.edit_text(
        f"Удалить клиента {escape(client.get('display_name') or str(telegram_id))} и все его записи из базы?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:c:delok:"))
async def admin_client_delete_confirm(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_roles"):
        return
    telegram_id = int(callback.data.rsplit(":", 1)[1])
    changed, removed_count = await store.delete_client_with_bookings(telegram_id)
    text = (
        f"Клиент удален. Удалено записей: {removed_count}."
        if changed
        else "Клиент не найден."
    )
    await callback.message.edit_text(text, reply_markup=admin_back_kb("adm:clients"))
    await callback.answer("Удалено" if changed else "Не найдено", show_alert=not changed)


@router.callback_query(F.data.startswith("adm:c:hist:"))
async def admin_client_history(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_clients"):
        return
    telegram_id = int(callback.data.rsplit(":", 1)[1])
    bookings = await store.client_bookings(telegram_id)
    await callback.message.edit_text(
        format_booking_list("История записей клиента", bookings),
        reply_markup=admin_back_kb(f"adm:c:view:{telegram_id}"),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:export")
async def admin_export_menu(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "export_bookings"):
        return
    await callback.message.edit_text("<b>📤 Выгрузка</b>", reply_markup=export_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("adm:x:"))
async def admin_export_csv(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "export_bookings"):
        return
    period = callback.data.rsplit(":", 1)[1]
    today = today_in(config.timezone)
    filename = "bookings_all.csv"
    if period == "today":
        bookings = await store.list_bookings(today.isoformat(), today.isoformat(), include_statuses=None)
        filename = f"bookings_{today.isoformat()}.csv"
    elif period == "week":
        end = today + timedelta(days=7)
        bookings = await store.list_bookings(today.isoformat(), end.isoformat(), include_statuses=None)
        filename = f"bookings_week_{today.isoformat()}.csv"
    elif period == "month":
        end = today + timedelta(days=31)
        bookings = await store.list_bookings(today.isoformat(), end.isoformat(), include_statuses=None)
        filename = f"bookings_month_{today.isoformat()}.csv"
    else:
        bookings = await store.load("bookings.json", [])

    document = BufferedInputFile(build_bookings_csv(bookings), filename=filename)
    await callback.message.answer_document(document, caption="CSV-выгрузка записей")
    await callback.answer("Файл сформирован")


@router.callback_query(F.data == "adm:blk:menu")
async def admin_blocked_menu(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    await state.clear()
    if not await require_permission(callback, store, "manage_blocked"):
        return
    await callback.message.edit_text("<b>🚫 Закрыть дату/время</b>", reply_markup=blocked_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:blk:day")
async def admin_block_day_calendar(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "manage_blocked"):
        return
    await send_block_day_calendar(callback, store, config)


@router.callback_query(F.data.startswith("adm:blk:d:month:"))
async def admin_block_day_month(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "manage_blocked"):
        return
    await send_block_day_calendar(callback, store, config)


@router.callback_query(F.data.startswith("adm:blk:d:date:"))
async def admin_block_day_toggle(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not await require_permission(callback, store, "manage_blocked"):
        return
    day = callback.data.rsplit(":", 1)[1]
    if date.fromisoformat(day) < today_in(config.timezone):
        await callback.answer("Нельзя закрыть дату раньше сегодняшнего дня", show_alert=True)
        return
    is_blocked = await store.toggle_blocked_date(day)
    await callback.message.edit_text(
        f"{short_date(day)}: {'закрыта' if is_blocked else 'открыта'}.\n\n"
        "Можно выбрать следующую дату или вернуться в панель.",
        reply_markup=admin_back_kb("adm:blk:menu"),
    )
    await callback.answer("Дата закрыта" if is_blocked else "Дата открыта")


@router.callback_query(F.data == "adm:blk:slot")
async def admin_block_slot_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_blocked"):
        return
    await state.clear()
    await state.set_state(AdminBlockedStates.waiting_block_slot_date)
    await callback.message.edit_text("Введите дату в формате YYYY-MM-DD:", reply_markup=admin_back_kb("adm:blk:menu"))
    await callback.answer()


@router.message(AdminBlockedStates.waiting_block_slot_date)
async def admin_block_slot_date(message: Message, state: FSMContext, config: BotConfig) -> None:
    day = (message.text or "").strip()
    try:
        parsed_day = date.fromisoformat(day)
    except ValueError:
        await message.answer("Дата должна быть в формате YYYY-MM-DD.")
        return
    if parsed_day < today_in(config.timezone):
        await message.answer("Нельзя закрыть дату раньше сегодняшнего дня.")
        return
    await state.update_data(block_date=day)
    await state.set_state(AdminBlockedStates.waiting_block_start_time)
    await message.answer("Введите начало закрытого времени, например 12:00:")


@router.message(AdminBlockedStates.waiting_block_start_time)
async def admin_block_slot_start_time(message: Message, state: FSMContext) -> None:
    value = normalize_time(message.text or "")
    if value is None:
        await message.answer("Время должно быть в формате HH:MM.")
        return
    await state.update_data(block_start_time=value)
    await state.set_state(AdminBlockedStates.waiting_block_end_time)
    await message.answer("Введите конец закрытого времени, например 15:00:")


@router.message(AdminBlockedStates.waiting_block_end_time)
async def admin_block_slot_end_time(message: Message, state: FSMContext) -> None:
    value = normalize_time(message.text or "")
    if value is None:
        await message.answer("Время должно быть в формате HH:MM.")
        return
    data = await state.get_data()
    if parse_time_to_minutes(data["block_start_time"]) >= parse_time_to_minutes(value):
        await message.answer("Конец должен быть позже начала.")
        return
    await state.update_data(block_end_time=value)
    await state.set_state(AdminBlockedStates.waiting_block_reason)
    await message.answer("Введите причину или отправьте '-' без причины:")


@router.message(AdminBlockedStates.waiting_block_reason)
async def admin_block_slot_reason(message: Message, state: FSMContext, store: JsonStore) -> None:
    data = await state.get_data()
    reason = (message.text or "").strip()
    if reason == "-":
        reason = ""
    slot = await store.add_blocked_slot(data["block_date"], data["block_start_time"], data["block_end_time"], reason)
    await state.clear()
    await message.answer(
        f"Время закрыто: {short_date(slot['date'])} {slot['start_time']}–{slot['end_time']}",
        reply_markup=admin_back_kb("adm:blk:menu"),
    )


@router.callback_query(F.data == "adm:blk:list")
async def admin_blocked_list(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_blocked"):
        return
    await callback.message.edit_text(
        blocked_list_text(await store.list_blocked_dates(), await store.list_blocked_slots()),
        reply_markup=admin_back_kb("adm:blk:menu"),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:blk:open")
async def admin_blocked_open(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_blocked"):
        return
    dates = await store.list_blocked_dates()
    slots = await store.list_blocked_slots()
    rows: list[list[InlineKeyboardButton]] = []
    for day in dates:
        rows.append([InlineKeyboardButton(text=f"Открыть {short_date(day)}", callback_data=f"adm:blk:openday:{day}")])
    for slot in slots:
        rows.append([InlineKeyboardButton(text=f"{slot['date']} {slot['start_time']}–{slot['end_time']}", callback_data=f"adm:blk:rm:{slot['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:blk:menu")])
    await callback.message.edit_text("Выберите, что открыть обратно:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:blk:openday:"))
async def admin_blocked_open_day(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_blocked"):
        return
    day = callback.data.rsplit(":", 1)[1]
    if day in await store.list_blocked_dates():
        await store.toggle_blocked_date(day)
    await callback.message.edit_text(f"{short_date(day)} открыта.", reply_markup=admin_back_kb("adm:blk:menu"))
    await callback.answer("Открыто")


@router.callback_query(F.data.startswith("adm:blk:rm:"))
async def admin_blocked_remove_slot(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_blocked"):
        return
    changed = await store.remove_blocked_slot(callback.data.rsplit(":", 1)[1])
    await callback.message.edit_text(
        "Закрытое время удалено." if changed else "Закрытое время не найдено.",
        reply_markup=admin_back_kb("adm:blk:menu"),
    )
    await callback.answer("Открыто" if changed else "Не найдено", show_alert=not changed)


@router.callback_query(F.data == "adm:reviews")
async def admin_reviews(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_reviews"):
        return
    reviews = await store.load("reviews.json", [])
    published = [item for item in reviews if item.get("published")]
    pending = [item for item in reviews if not item.get("published")]
    lines = [
        "<b>⭐ Отзывы</b>",
        f"Опубликовано: <b>{len(published)}</b>",
        f"На модерации: <b>{len(pending)}</b>",
    ]
    rows = []
    for review in pending[:8]:
        lines.append(f"\n• {escape(review.get('name', 'Клиент'))}: {escape((review.get('text') or '')[:80])}")
        rows.append(
            [
                InlineKeyboardButton(text=f"✅ {review['id']}", callback_data=f"review:publish:{review['id']}"),
                InlineKeyboardButton(text=f"❌ {review['id']}", callback_data=f"review:hide:{review['id']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:menu")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "adm:stats")
async def admin_stats(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "view_stats"):
        return
    await callback.message.edit_text(stats_text(await store.stats()), reply_markup=admin_back_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:admins")
async def admin_admins(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_roles"):
        return
    await callback.message.edit_text(admins_text(await store.get_admins()), reply_markup=admins_manage_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:r:start")
async def admin_role_start(callback: CallbackQuery, state: FSMContext, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_roles"):
        return
    await state.set_state(AdminRoleStates.waiting_user_id)
    await callback.message.edit_text(
        "Введите Telegram ID пользователя, которому нужно выдать или изменить роль:",
        reply_markup=admin_back_kb("adm:admins"),
    )
    await callback.answer()


@router.message(AdminRoleStates.waiting_user_id)
async def admin_role_waiting_user_id(message: Message, state: FSMContext, store: JsonStore) -> None:
    if not await has_permission(message.from_user.id if message.from_user else None, "manage_roles", store):
        await message.answer("Недоступно.")
        await state.clear()
        return
    try:
        telegram_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Telegram ID должен быть числом.")
        return
    await state.clear()
    await message.answer(
        f"Выберите роль для <code>{telegram_id}</code>:",
        reply_markup=role_select_kb(telegram_id),
    )


@router.callback_query(F.data.startswith("adm:r:role:"))
async def admin_role_set(callback: CallbackQuery, store: JsonStore) -> None:
    if not await require_permission(callback, store, "manage_roles"):
        return
    _, _, _, telegram_id_raw, role = callback.data.split(":", 4)
    ok, text = await store.set_role(int(telegram_id_raw), role, callback.from_user)
    await callback.message.edit_text(text, reply_markup=admins_manage_kb())
    await callback.answer("Сохранено" if ok else "Не сохранено", show_alert=not ok)


async def show_bookings_range(callback: CallbackQuery, store: JsonStore, title: str, start: str, end: str) -> None:
    bookings = await store.list_bookings(start, end)
    await callback.message.edit_text(format_booking_list(title, bookings), reply_markup=admin_booking_list_kb(bookings))
    await callback.answer()


def clients_results_text(title: str, clients: list[dict[str, Any]]) -> str:
    if not clients:
        return f"<b>{escape(title)}</b>\n\nНичего не найдено."
    lines = [f"<b>{escape(title)}</b>", f"Найдено: <b>{len(clients)}</b>", ""]
    for index, client in enumerate(clients, start=1):
        username = f"@{client['username']}" if client.get("username") else "без username"
        phone = client.get("phone") or "без телефона"
        lines.append(
            f"{index}. {escape(client.get('display_name') or 'Клиент')} — "
            f"{escape(phone)} — {escape(username)} — <code>{client['telegram_id']}</code>"
        )
    return "\n".join(lines)


async def send_admin_pick_calendar(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    current_month = callback.data.removeprefix("adm:b:pick:month:") if callback.data.startswith("adm:b:pick:month:") else None
    today = today_in(config.timezone)
    horizon_end = today + timedelta(days=config.booking_horizon_days)
    year, month = (map(int, current_month.split("-")) if current_month else (today.year, today.month))
    await callback.message.edit_text(
        "Выберите дату:",
        reply_markup=booking_calendar_kb(
            year,
            month,
            today,
            horizon_end,
            {},
            set(await store.list_blocked_dates()),
            callback_prefix="adm:b:pick",
            back_callback="adm:menu",
        ),
    )
    await callback.answer()


async def send_reschedule_calendar(
    callback: CallbackQuery,
    state: FSMContext,
    store: JsonStore,
    config: BotConfig,
    booking: dict[str, Any],
) -> None:
    current_month = callback.data.removeprefix("adm:b:r:month:") if callback.data.startswith("adm:b:r:month:") else None
    today = today_in(config.timezone)
    horizon_end = today + timedelta(days=config.booking_horizon_days)
    year, month = (map(int, current_month.split("-")) if current_month else (today.year, today.month))
    duration = int(booking.get("total_duration_min", 60))
    unavailable = await unavailable_slots_map(store, today, horizon_end, duration, exclude_booking_id=booking["id"])
    await state.set_state(AdminBookingStates.choosing_reschedule_date)
    await callback.message.edit_text(
        "Выберите новую дату:",
        reply_markup=booking_calendar_kb(
            year,
            month,
            today,
            horizon_end,
            unavailable,
            set(await store.list_blocked_dates()),
            callback_prefix="adm:b:r",
            back_callback=f"adm:b:view:{booking['id']}",
        ),
    )
    await callback.answer()


async def send_block_day_calendar(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    current_month = callback.data.removeprefix("adm:blk:d:month:") if callback.data.startswith("adm:blk:d:month:") else None
    today = today_in(config.timezone)
    horizon_end = today + timedelta(days=config.booking_horizon_days)
    year, month = (map(int, current_month.split("-")) if current_month else (today.year, today.month))
    await callback.message.edit_text(
        "Выберите дату, чтобы закрыть или открыть ее для записи. Закрытые даты отмечены ×.",
        reply_markup=booking_calendar_kb(
            year,
            month,
            today,
            horizon_end,
            {},
            set(await store.list_blocked_dates()),
            callback_prefix="adm:blk:d",
            back_callback="adm:blk:menu",
        ),
    )
    await callback.answer()


async def unavailable_slots_map(
    store: JsonStore,
    start: date,
    end: date,
    duration_min: int,
    exclude_booking_id: str | None = None,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    current = start
    while current <= end:
        day = current.isoformat()
        available = set(await store.available_time_slots(day, duration_min, exclude_booking_id=exclude_booking_id))
        result[day] = {slot for slot in TIME_SLOTS if slot not in available}
        current += timedelta(days=1)
    return result


async def require_permission(callback: CallbackQuery, store: JsonStore, permission: str) -> bool:
    if await has_permission(callback.from_user.id if callback.from_user else None, permission, store):
        return True
    await callback.answer("Недоступно", show_alert=True)
    return False


async def notify_client(source: CallbackQuery | Message, booking: dict[str, Any], text: str) -> str:
    telegram_id = booking.get("client", {}).get("telegram_id")
    if not telegram_id:
        return "\n\n⚠️ У клиента нет Telegram ID для уведомления."
    try:
        await source.bot.send_message(int(telegram_id), text, parse_mode=None)
    except TelegramAPIError as exc:
        logger.warning("Could not notify client %s: %s", telegram_id, exc)
        return "\n\n⚠️ Клиенту не удалось отправить уведомление."
    return ""


async def start_service_edit_field(
    callback: CallbackQuery,
    state: FSMContext,
    store: JsonStore,
    state_name: str,
    prompt: str,
) -> None:
    if not await require_permission(callback, store, "manage_services"):
        return
    service_id = callback.data.rsplit(":", 1)[1]
    if await store.get_service(service_id) is None:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    await state.update_data(edit_service_id=service_id)
    await state.set_state(getattr(AdminServiceStates, state_name))
    await callback.message.edit_text(prompt, reply_markup=admin_back_kb(f"adm:s:edit:{service_id}"))
    await callback.answer()


async def finish_service_update(message: Message, state: FSMContext, store: JsonStore, **changes: Any) -> None:
    if not await has_permission(message.from_user.id if message.from_user else None, "manage_services", store):
        await message.answer("Недоступно.")
        await state.clear()
        return
    data = await state.get_data()
    service_id = data.get("edit_service_id")
    service = await store.update_service(service_id, **changes)
    await state.clear()
    if service is None:
        await message.answer("Услуга не найдена.", reply_markup=admin_back_kb("adm:s:list"))
        return
    await message.answer(service_card_text(service), reply_markup=service_edit_kb(service))


def build_bookings_csv(bookings: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "status",
            "date",
            "start_time",
            "end_time",
            "client_name",
            "phone",
            "telegram_username",
            "telegram_id",
            "services",
            "total_price",
            "total_duration_min",
            "created_at",
            "updated_at",
        ]
    )
    for booking in bookings:
        client = booking.get("client", {})
        contact = booking.get("contact", {})
        writer.writerow(
            [
                booking.get("id", ""),
                booking.get("status", ""),
                booking.get("date", ""),
                booking.get("start_time", ""),
                booking.get("end_time", ""),
                contact.get("name", ""),
                contact.get("phone", ""),
                client.get("username", ""),
                client.get("telegram_id", ""),
                format_services_inline(booking.get("services", [])),
                booking.get("total_price", 0),
                booking.get("total_duration_min", 0),
                booking.get("created_at", ""),
                booking.get("updated_at", ""),
            ]
        )
    return output.getvalue().encode("utf-8-sig")


def parse_non_negative_int(value: str | None) -> int | None:
    try:
        number = int((value or "").strip())
    except ValueError:
        return None
    return number if number >= 0 else None


def parse_positive_int(value: str | None) -> int | None:
    number = parse_non_negative_int(value)
    return number if number and number > 0 else None


def normalize_time(value: str) -> str | None:
    value = value.strip()
    if not TIME_RE.match(value):
        return None
    hours, minutes = value.split(":", 1)
    if int(hours) > 23 or int(minutes) > 59:
        return None
    normalized = f"{int(hours):02d}:{int(minutes):02d}"
    try:
        parse_time_to_minutes(normalized)
    except ValueError:
        return None
    return normalized
