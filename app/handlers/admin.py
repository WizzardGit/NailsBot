from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import BotConfig
from app.handlers.booking import booked_dates_map
from app.keyboards import admin_back_kb, admin_menu_kb, booking_calendar_kb
from app.schedule import human_date, today_in
from app.storage import JsonStore
from app.texts import format_booking_list, stats_text


router = Router()


@router.message(Command("admin"))
async def admin_command(message: Message, config: BotConfig) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer("Панель мастера недоступна.")
        return
    await message.answer("<b>Панель мастера</b>\nВыберите действие:", reply_markup=admin_menu_kb())


@router.callback_query(F.data == "admin:menu")
async def admin_menu(callback: CallbackQuery, config: BotConfig) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.message.edit_text("<b>Панель мастера</b>\nВыберите действие:", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:today")
async def admin_today(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Недоступно", show_alert=True)
        return
    today = today_in(config.timezone).isoformat()
    bookings = await store.list_bookings(today, today)
    await callback.message.edit_text(format_booking_list("Записи на сегодня", bookings), reply_markup=admin_back_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:week")
async def admin_week(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Недоступно", show_alert=True)
        return
    start = today_in(config.timezone)
    end = start + timedelta(days=7)
    bookings = await store.list_bookings(start.isoformat(), end.isoformat())
    await callback.message.edit_text(format_booking_list("Записи на ближайшие 7 дней", bookings), reply_markup=admin_back_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Недоступно", show_alert=True)
        return
    stats = await store.stats()
    await callback.message.edit_text(stats_text(stats), reply_markup=admin_back_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:block")
async def admin_block_calendar(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Недоступно", show_alert=True)
        return
    await send_admin_calendar(callback, store, config)


@router.callback_query(F.data.startswith("admin:block:month:"))
async def admin_block_month(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Недоступно", show_alert=True)
        return
    await send_admin_calendar(callback, store, config)


@router.callback_query(F.data.startswith("admin:block:date:"))
async def admin_toggle_date(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Недоступно", show_alert=True)
        return
    day = callback.data.rsplit(":", 1)[1]
    is_blocked = await store.toggle_blocked_date(day)
    await callback.answer("Дата закрыта" if is_blocked else "Дата снова открыта")
    await callback.message.edit_text(
        f"{human_date(day)}: {'закрыта' if is_blocked else 'открыта'}.\n\nВыберите следующую дату или вернитесь в панель.",
        reply_markup=admin_back_kb(),
    )


async def send_admin_calendar(callback: CallbackQuery, store: JsonStore, config: BotConfig) -> None:
    current_month = (
        callback.data.rsplit(":", 1)[1] if callback.data and callback.data.startswith("admin:block:month:") else None
    )
    today = today_in(config.timezone)
    horizon_end = today + timedelta(days=config.booking_horizon_days)
    year, month = (map(int, current_month.split("-")) if current_month else (today.year, today.month))
    bookings = await store.load("bookings.json", [])
    blocked_dates = set(await store.load("blocked_dates.json", []))
    await callback.message.edit_text(
        "Выберите дату, чтобы закрыть или открыть ее для записи. Закрытые и заполненные даты отмечены ×.",
        reply_markup=booking_calendar_kb(
            year,
            month,
            today,
            horizon_end,
            booked_dates_map(bookings),
            blocked_dates,
            callback_prefix="admin:block",
        ),
    )
    await callback.answer()


def is_admin(user_id: int | None, config: BotConfig) -> bool:
    return user_id is not None and user_id in config.admin_ids

