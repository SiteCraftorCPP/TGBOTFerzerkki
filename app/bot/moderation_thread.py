"""Создание подтемы пользователя в форум-чате модерации (как при первом тикете)."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import display_db_user
from app.bot.telegram_log import telegram_error_details
from app.core.config import get_settings
from app.db.models import User
from app.db.repositories import invalidate_user_support_forum_if_mod_chat_mismatch, set_user_support_forum_thread

logger = logging.getLogger(__name__)


async def ensure_user_moderation_thread(bot: Bot, session: AsyncSession, user: User) -> int | None:
    """
    Возвращает message_thread_id подтемы этого пользователя; при отсутствии — создаёт тему в MODERATION_CHAT_ID.
    Для обычной (не форум) группы возвращает None.
    """
    mod_chat = get_settings().moderation_chat_id_int
    if mod_chat is None:
        logger.info("ensure_user_moderation_thread: MODERATION_CHAT_ID пуст — подтема не создаётся")
        return None

    await session.refresh(user)
    await invalidate_user_support_forum_if_mod_chat_mismatch(session, user, mod_chat)
    await session.refresh(user)
    if user.support_forum_thread_id is not None:
        return user.support_forum_thread_id

    label = display_db_user(user)
    topic_title = f"👤 {label}"[:128]
    logger.info(
        "ensure_user_moderation_thread: user_id=%s create_forum_topic chat=%s title=%r",
        user.id,
        mod_chat,
        topic_title,
    )
    try:
        topic = await bot.create_forum_topic(chat_id=mod_chat, name=topic_title)
        thread_id = topic.message_thread_id
        await set_user_support_forum_thread(session, user.id, thread_id, moderation_chat_id=mod_chat)
        await session.refresh(user)
        logger.info("Подтема для user_id=%s: thread_id=%s", user.id, thread_id)
        return thread_id
    except TelegramBadRequest as e:
        err = (getattr(e, "message", None) or str(e)).lower()
        if "not a forum" in err or "chat_not_forum" in err:
            logger.info(
                "ensure_user_moderation_thread: чат %s не форум (%s)",
                mod_chat,
                telegram_error_details(e),
            )
            return None
        logger.error(
            "ensure_user_moderation_thread: create_forum_topic FAILED user_id=%s chat=%s: %s",
            user.id,
            mod_chat,
            telegram_error_details(e),
        )
        return None
    except Exception:
        logger.exception("create_forum_topic user_id=%s", user.id)
        return None
