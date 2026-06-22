from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from app.keyboards import book_cta_kb, portfolio_categories_kb
from app.storage import JsonStore
from app.texts import MENU_PORTFOLIO


router = Router()


@router.message(F.text == MENU_PORTFOLIO)
async def show_portfolio(message: Message, store: JsonStore) -> None:
    await send_portfolio_categories(message, store)


@router.callback_query(F.data == "portfolio:open")
async def show_portfolio_from_callback(callback: CallbackQuery, store: JsonStore) -> None:
    await send_portfolio_categories(callback.message, store)
    await callback.answer()


@router.callback_query(F.data.startswith("portfolio:cat:"))
async def show_portfolio_category(callback: CallbackQuery, store: JsonStore) -> None:
    category_id = callback.data.rsplit(":", 1)[1]
    categories = await store.load("portfolio.json", [])
    category = next((item for item in categories if item["id"] == category_id), None)
    if category is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    works = category.get("works", [])
    media = [
        InputMediaPhoto(
            media=work["photo_url"],
            caption=f"{category['title']}\n{work['caption']}" if index == 0 else work["caption"],
        )
        for index, work in enumerate(works[:10])
    ]

    if media:
        try:
            await callback.message.answer_media_group(media)
        except TelegramAPIError:
            await callback.message.answer("\n\n".join(work["caption"] for work in works[:5]))
    await callback.message.answer("Если понравился стиль, можно сразу выбрать дату.", reply_markup=book_cta_kb())
    await callback.answer()


async def send_portfolio_categories(message: Message, store: JsonStore) -> None:
    categories = await store.load("portfolio.json", [])
    await message.answer(
        "<b>Примеры работ</b>\nВыберите направление. Внутри — короткий альбом и кнопка записи.",
        reply_markup=portfolio_categories_kb(categories),
    )
