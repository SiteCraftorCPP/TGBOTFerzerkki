from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.oferta_text import OFERTA_ACCEPT_CB
from app.bot.staff import is_listed_admin
from app.core.config import get_settings
from app.db.repositories import get_user_by_tg_id, user_needs_oferta_acceptance
from app.db.session import SessionLocal


def _is_start_command(message: Message) -> bool:
    if not message.text:
        return False
    return message.text.startswith("/start")


async def _should_block_for_oferta(event: TelegramObject, session: Any) -> bool:
    if isinstance(event, Message):
        chat = event.chat
        tg_user = event.from_user
    elif isinstance(event, CallbackQuery):
        chat = event.message.chat if event.message else None
        tg_user = event.from_user
    else:
        return False

    if chat is None or chat.type != "private":
        return False
    if tg_user is None or tg_user.is_bot:
        return False
    if is_listed_admin(tg_user.id):
        return False
    settings = get_settings()

    if isinstance(event, CallbackQuery) and event.data == OFERTA_ACCEPT_CB:
        return False
    if isinstance(event, Message) and _is_start_command(event):
        return False

    user = await get_user_by_tg_id(session, tg_user.id)
    return user_needs_oferta_acceptance(user, current_version=settings.oferta_version)


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with SessionLocal() as session:
            data["session"] = session
            if await _should_block_for_oferta(event, session):
                if isinstance(event, Message):
                    await event.answer("⚠️ Сначала прими публичную оферту — отправь команду /start.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Сначала открой /start и прими оферту.", show_alert=True)
                return None
            return await handler(event, data)

