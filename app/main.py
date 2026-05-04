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
    log = logging.getLogger(__name__)
    settings = get_settings()
    mod = settings.moderation_chat_id_int
    log.info(
        "Старт бота: MODERATION_CHAT_ID=%s (в .env строка moderation_chat_id / MODERATION_CHAT_ID)",
        mod if mod is not None else "не задан — тикеты только в ЛС админам",
    )
    admins = settings.admin_ids_list
    log.info(
        "ADMIN_IDS: всего %s — id=%s (если второй админ «молчит», проверь что его id в этом списке)",
        len(admins),
        admins,
    )
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

