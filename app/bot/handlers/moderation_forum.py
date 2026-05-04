"""Ответы модераторов из веток (топиков) чата поддержки → пользователю в ЛС."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.states import TopicModStates
from app.core.config import get_settings
from app.db.repositories import get_open_ticket_by_forum_thread
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

router = Router()


class InModerationForumTopicFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        settings = get_settings()
        chat_id = settings.moderation_chat_id_int
        if chat_id is None or message.chat.id != chat_id:
            return False
        return message.message_thread_id is not None


@router.message(InModerationForumTopicFilter(), F.text, ~F.text.startswith("/"))
async def relay_forum_reply_to_user(message: Message, bot: Bot, state: FSMContext) -> None:
    st = await state.get_state()
    if st is not None and str(st).startswith(TopicModStates.__name__):
        return
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.from_user.id not in get_settings().admin_ids_list:
        logger.info(
            "relay: не админ user_id=%s — нет в ADMIN_IDS, в ЛС пользователю не отправлено",
            message.from_user.id,
        )
        return

    thread_id = message.message_thread_id
    if thread_id is None:
        return

    async with SessionLocal() as session:
        ticket = await get_open_ticket_by_forum_thread(session, thread_id)
        if ticket is None or ticket.user is None:
            logger.warning(
                "relay: нет открытого тикета для thread_id=%s (ответь в подтеме тикета, не в General)",
                thread_id,
            )
            return
        try:
            await bot.send_message(
                ticket.user.telegram_id,
                f"💬 Сообщение от поддержки:\n{message.text}",
            )
        except Exception:
            logger.exception("Ошибка отправки ответа пользователю из ветки тикета")
