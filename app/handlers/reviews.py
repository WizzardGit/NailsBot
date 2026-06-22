from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import BotConfig
from app.keyboards import moderation_kb, rating_kb, review_nav_kb
from app.permissions import has_permission, notification_recipients
from app.states import ReviewStates
from app.storage import JsonStore
from app.texts import MENU_REVIEWS, review_text, user_payload


router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == MENU_REVIEWS)
async def show_reviews(message: Message, store: JsonStore) -> None:
    await send_review(message, store, 0)


@router.callback_query(F.data.startswith("review:show:"))
async def show_review_callback(callback: CallbackQuery, store: JsonStore) -> None:
    index = int(callback.data.rsplit(":", 1)[1])
    reviews = await published_reviews(store)
    if not reviews:
        await callback.message.edit_text(
            "<b>Отзывы</b>\nПока нет опубликованных отзывов.",
            reply_markup=review_nav_kb(0, 0),
        )
        await callback.answer()
        return

    index = index % len(reviews)
    await callback.message.edit_text(
        review_text(reviews[index], index, len(reviews)),
        reply_markup=review_nav_kb(index, len(reviews)),
    )
    await callback.answer()


@router.callback_query(F.data == "review:leave")
async def start_review(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("<b>Оцените визит</b>\nВыберите количество звезд:", reply_markup=rating_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("review:rate:"))
async def choose_review_rating(callback: CallbackQuery, state: FSMContext) -> None:
    rating = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(rating=rating)
    await state.set_state(ReviewStates.waiting_text)
    await callback.message.answer("Напишите отзыв одним сообщением. Мастер сможет опубликовать его после модерации.")
    await callback.answer()


@router.message(ReviewStates.waiting_text)
async def capture_review_text(message: Message, state: FSMContext, store: JsonStore, config: BotConfig) -> None:
    text = (message.text or "").strip()
    if len(text) < 10:
        await message.answer("Отзыв слишком короткий. Напишите, пожалуйста, чуть подробнее.")
        return

    data = await state.get_data()
    review = await store.add_review(
        {
            "rating": int(data.get("rating", 5)),
            "text": text[:700],
            "name": message.from_user.full_name if message.from_user else "Клиент",
            "telegram_user": user_payload(message.from_user),
        }
    )
    await state.clear()
    await message.answer("Спасибо! Отзыв отправлен мастеру на модерацию.")

    stars = "★" * int(review["rating"])
    for admin_id in await notification_recipients(store, config):
        try:
            await message.bot.send_message(
                admin_id,
                f"<b>Новый отзыв</b>\n\n{stars}\n«{escape(review['text'])}»\n\n— {escape(review['name'])}",
                reply_markup=moderation_kb(review["id"]),
            )
        except TelegramAPIError as exc:
            logger.warning("Could not notify admin %s about review: %s", admin_id, exc)


@router.callback_query(F.data.startswith("review:publish:"))
async def publish_review(callback: CallbackQuery, store: JsonStore) -> None:
    if not await has_permission(callback.from_user.id, "manage_reviews", store):
        await callback.answer("Недоступно", show_alert=True)
        return
    review_id = callback.data.rsplit(":", 1)[1]
    changed = await store.set_review_published(review_id, True)
    await callback.answer("Опубликовано" if changed else "Отзыв не найден", show_alert=not changed)


@router.callback_query(F.data.startswith("review:hide:"))
async def hide_review(callback: CallbackQuery, store: JsonStore) -> None:
    if not await has_permission(callback.from_user.id, "manage_reviews", store):
        await callback.answer("Недоступно", show_alert=True)
        return
    review_id = callback.data.rsplit(":", 1)[1]
    changed = await store.set_review_published(review_id, False)
    await callback.answer("Скрыто" if changed else "Отзыв не найден", show_alert=not changed)


async def send_review(message: Message, store: JsonStore, index: int) -> None:
    reviews = await published_reviews(store)
    if not reviews:
        await message.answer("<b>Отзывы</b>\nПока нет опубликованных отзывов.", reply_markup=review_nav_kb(0, 0))
        return
    index = index % len(reviews)
    await message.answer(review_text(reviews[index], index, len(reviews)), reply_markup=review_nav_kb(index, len(reviews)))


async def published_reviews(store: JsonStore) -> list[dict]:
    reviews = await store.load("reviews.json", [])
    return [review for review in reviews if review.get("published")]
