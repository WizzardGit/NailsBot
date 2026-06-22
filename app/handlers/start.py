from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import BotConfig
from app.keyboards import lead_source_kb, main_menu_kb
from app.states import LeadStates
from app.storage import JsonStore
from app.texts import MENU_BACK, home_text, user_payload, welcome_text


router = Router()

SOURCE_LABELS = {
    "instagram": "Instagram",
    "friend": "Рекомендация подруги",
    "search": "Поиск в интернете",
}


@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext, config: BotConfig) -> None:
    await state.clear()
    await message.answer(welcome_text(config.brand_name), reply_markup=lead_source_kb())


@router.message(Command("menu"))
async def command_menu(message: Message, state: FSMContext, config: BotConfig) -> None:
    await state.clear()
    await message.answer(home_text(config.brand_name), reply_markup=main_menu_kb())


@router.message(Command("myid"))
async def command_myid(message: Message) -> None:
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        "Вставьте его в .env в MASTER_CHAT_ID и ADMIN_IDS."
    )


@router.callback_query(F.data == "nav:home")
async def callback_home(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    await state.clear()
    await callback.message.answer(home_text(config.brand_name), reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("lead:"))
async def capture_lead_source(callback: CallbackQuery, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    source_key = callback.data.split(":", 1)[1]
    if source_key == "other":
        await state.set_state(LeadStates.waiting_custom_source)
        await callback.message.answer("Напишите, пожалуйста, откуда вы о нас узнали. Одной фразы достаточно.")
        await callback.answer()
        return

    await store.add_lead(user_payload(callback.from_user), SOURCE_LABELS.get(source_key, source_key))
    await state.clear()
    await callback.message.answer(home_text(config.brand_name), reply_markup=main_menu_kb())
    await callback.answer("Спасибо")


@router.message(LeadStates.waiting_custom_source)
async def capture_custom_source(message: Message, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    source = (message.text or "").strip()
    if source == MENU_BACK:
        source = "Не указано"
    if not source:
        await message.answer("Напишите источник текстом или нажмите /menu, чтобы пропустить.")
        return

    await store.add_lead(user_payload(message.from_user), source[:120])
    await state.clear()
    await message.answer(home_text(config.brand_name), reply_markup=main_menu_kb())
