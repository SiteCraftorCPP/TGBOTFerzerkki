import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.common import main_menu
from app.bot.oferta_text import OFERTA_ACCEPT_CB, oferta_docx_path
from app.bot.texts import WELCOME_HTML
from app.core.config import get_settings
from app.db.repositories import get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


def oferta_accept_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Принять оферту", callback_data=OFERTA_ACCEPT_CB)]]
    )


async def send_oferta_to_chat(bot: Bot, chat_id: int) -> None:
    path = oferta_docx_path()
    if not path.is_file():
        logger.error("Файл оферты не найден: %s", path)
        await bot.send_message(
            chat_id,
            "⚠️ Файл оферты на сервере не найден. Напиши администратору. Пока бот недоступен.",
        )
        return
    await bot.send_document(
        chat_id,
        document=FSInputFile(path),
        caption=(
            "📜 <b>Публичная оферта</b> во вложении. Чтобы пользоваться ботом, открой документ, "
            "ознакомься с условиями и нажми «Принять оферту»."
        ),
        reply_markup=oferta_accept_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == OFERTA_ACCEPT_CB)
async def oferta_accept(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = get_settings()
    user = await get_or_create_user(session, callback.from_user)
    user.oferta_accepted_version = settings.oferta_version
    await session.commit()
    await callback.answer("Оферта принята.")
    if callback.message:
        await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
