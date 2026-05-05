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


class OutsideTopicModFsm(BaseFilter):
    """Релэй в ЛС не забирает сообщения, пока модератор в FSM закрытия/баланса в подтеме."""

    async def __call__(self, message: Message, state: FSMContext) -> bool:
        st = await state.get_state()
        if st is None:
            return True
        return not str(st).startswith(TopicModStates.__name__)


@router.message(
    InModerationForumTopicFilter(),
    OutsideTopicModFsm(),
    F.text,
    ~F.text.startswith("/"),
)
async def relay_forum_reply_to_user(message: Message, bot: Bot, state: FSMContext) -> None:
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
                "relay: нет открытого тикета для thread_id=%s (тикет закрыт или это старая подтема)",
                thread_id,
            )
            try:
                await bot.send_message(
                    message.chat.id,
                    "⚠️ Здесь нет <b>открытого</b> тикета: либо он уже закрыт, либо ты в старой подтеме. "
                    "Открой <b>актуальное</b> сообщение бота с кнопками или нажми «Закрыть» заново на свежем тикете.",
                    message_thread_id=thread_id,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("relay: не удалось отправить подсказку в подтему %s", thread_id)
            return
        try:
            await bot.send_message(
                ticket.user.telegram_id,
                f"💬 Сообщение от поддержки:\n{message.text}",
            )
        except Exception:
            logger.exception("Ошибка отправки ответа пользователю из ветки тикета")
