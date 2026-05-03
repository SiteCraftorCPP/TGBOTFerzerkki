import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.middleware import DbSessionMiddleware
from app.bot.router import build_router
from app.core.config import get_settings
from app.db.session import init_db


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    session = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.update.middleware(DbSessionMiddleware())
    dispatcher.include_router(build_router())

    await init_db()
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

