from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.config import BotConfig
from app.keyboards import contacts_kb, faq_kb
from app.storage import JsonStore
from app.texts import MENU_CONTACTS, MENU_FAQ, MENU_SERVICES, services_text


router = Router()


@router.message(F.text == MENU_SERVICES)
async def show_services_info(message: Message, store: JsonStore) -> None:
    services = await store.load("services.json", [])
    await message.answer(services_text(services))


@router.message(F.text == MENU_FAQ)
async def show_faq(message: Message, store: JsonStore) -> None:
    items = await store.load("faq.json", [])
    await message.answer("<b>FAQ</b>\nВыберите вопрос:", reply_markup=faq_kb(items))


@router.callback_query(F.data.startswith("faq:"))
async def show_faq_answer(callback: CallbackQuery, store: JsonStore) -> None:
    faq_id = callback.data.rsplit(":", 1)[1]
    items = await store.load("faq.json", [])
    item = next((entry for entry in items if entry["id"] == faq_id), None)
    if item is None:
        await callback.answer("Вопрос не найден", show_alert=True)
        return

    await callback.message.edit_text(
        f"<b>{escape(item['question'])}</b>\n\n{escape(item['answer'])}",
        reply_markup=faq_kb(items),
    )
    await callback.answer()


@router.message(F.text == MENU_CONTACTS)
async def show_contacts(message: Message, config: BotConfig) -> None:
    text = (
        f"<b>{escape(config.brand_name)}</b>\n\n"
        f"Адрес: {escape(config.address)}\n"
        f"Телефон: {escape(config.contact_phone)}\n"
        "Instagram и карта доступны по кнопкам ниже."
    )
    await message.answer(text, reply_markup=contacts_kb(config.instagram_url, config.map_url))

