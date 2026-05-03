"""Отображение имён пользователей в сообщениях бота."""

from aiogram.types import User as TgUser

from app.db.models import User


def display_db_user(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    if user.first_name:
        return user.first_name
    return "Игрок"


def display_tg_user(tg_user: TgUser | None) -> str:
    if tg_user is None:
        return "Игрок"
    if tg_user.username:
        return f"@{tg_user.username}"
    if tg_user.first_name:
        return tg_user.first_name
    return "Игрок"
