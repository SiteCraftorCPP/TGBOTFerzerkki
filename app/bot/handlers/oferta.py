from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.common import main_menu
from app.bot.oferta_text import OFERTA_ACCEPT_CB, iter_oferta_chunks
from app.bot.texts import WELCOME_HTML
from app.core.config import get_settings
from app.db.repositories import get_or_create_user

router = Router()


def oferta_accept_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Принять оферту", callback_data=OFERTA_ACCEPT_CB)]]
    )


async def send_oferta_to_chat(bot: Bot, chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        "📜 Чтобы пользоваться ботом, прочитай текст оферты ниже. "
        "После прочтения нажми «Принять оферту» в последнем сообщении.",
    )
    chunks = iter_oferta_chunks()
    for i, ch in enumerate(chunks):
        last = i == len(chunks) - 1
        await bot.send_message(chat_id, ch, reply_markup=oferta_accept_keyboard() if last else None)


@router.callback_query(F.data == OFERTA_ACCEPT_CB)
async def oferta_accept(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = get_settings()
    user = await get_or_create_user(session, callback.from_user)
    user.oferta_accepted_version = settings.oferta_version
    await session.commit()
    await callback.answer("Оферта принята.")
    if callback.message:
        await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
