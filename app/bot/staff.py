"""Проверка прав модератора в MODERATION_CHAT (включая «анонимный админ» группы)."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from app.core.config import get_settings
from app.core.constants import TELEGRAM_ANONYMOUS_GROUP_ADMIN_USER_ID


def is_listed_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in get_settings().admin_ids_list


def acts_as_moderator_in_chat(user_id: int | None, *, chat_id: int, mod_chat_id: int | None) -> bool:
    """
    True, если действие в чате модерации от объявленного админа или от плейсхолдера
    анонимного администратора (фиксированный id у Telegram в этой группе).
    """
    if mod_chat_id is None or chat_id != mod_chat_id:
        return False
    if is_listed_admin(user_id):
        return True
    if user_id == TELEGRAM_ANONYMOUS_GROUP_ADMIN_USER_ID:
        return True
    return False


def acts_as_moderator_callback(callback: CallbackQuery, mod_chat_id: int | None) -> bool:
    if callback.from_user is None or callback.message is None:
        return False
    return acts_as_moderator_in_chat(
        callback.from_user.id,
        chat_id=callback.message.chat.id,
        mod_chat_id=mod_chat_id,
    )


def acts_as_moderator_message(message: Message, mod_chat_id: int | None) -> bool:
    uid = message.from_user.id if message.from_user else None
    return acts_as_moderator_in_chat(uid, chat_id=message.chat.id, mod_chat_id=mod_chat_id)
