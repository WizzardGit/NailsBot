from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import load_config
from app.handlers import admin, booking, info, portfolio, reviews, start
from app.storage import JsonStore


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config()
    store = JsonStore(config.data_dir)
    await store.ensure_files(
        owner_id=config.owner_id,
        master_chat_id=config.master_chat_id,
        admin_ids=config.admin_ids,
    )

    bot = Bot(token=config.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher["config"] = config
        dispatcher["store"] = store

        dispatcher.include_router(start.router)
        dispatcher.include_router(booking.router)
        dispatcher.include_router(portfolio.router)
        dispatcher.include_router(reviews.router)
        dispatcher.include_router(info.router)
        dispatcher.include_router(admin.router)

        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except TelegramUnauthorizedError:
        print("Telegram rejected BOT_TOKEN. Put a fresh token from @BotFather into .env.", file=sys.stderr)
        raise SystemExit(1)
    except TelegramNetworkError as exc:
        print(f"Cannot connect to Telegram API: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Bot stopped.")
        raise SystemExit(0)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
