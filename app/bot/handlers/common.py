from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.games import match_flow_back_handler
from app.bot.keyboards.common import balance_actions_keyboard, flow_nav_keyboard, main_menu
from app.bot.states import BalanceStates, ProfileStates, SupportStates
from app.bot.texts import WELCOME_HTML
from app.bot.texts_balance import balance_intro_html
from app.core.constants import GAME_TITLES, Game
from app.db.repositories import get_or_create_user

router = Router()


@router.message(CommandStart())
async def start(message: Message, session: AsyncSession) -> None:
    await get_or_create_user(session, message.from_user)
    await message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")


@router.message(lambda message: message.text == "📜 Правила")
async def rules(message: Message) -> None:
    await message.answer(
        "📜 <b>Правила ClashDuel</b>\n\n"
        "1. 🚫 Читы и подмена результатов запрещены.\n"
        "2. 📊 Кубки указывай честно, допустимое отклонение: ±300.\n"
        "3. ⏱ Не зашёл в игру вовремя или не завершил матч за 10 минут — поражение.\n"
        "4. 📉 Разница кубков больше 300 — модератор может аннулировать результат.\n"
        "5. ⚖️ При споре решает модератор.",
        reply_markup=flow_nav_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "flow:home")
async def flow_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "flow:back")
async def flow_back(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if await match_flow_back_handler(callback, state):
        await callback.answer()
        return

    st = await state.get_state()

    if st == ProfileStates.waiting_trophies:
        await state.set_state(ProfileStates.waiting_nickname)
        from app.bot.keyboards.common import flow_nav_keyboard

        await callback.message.answer("✏️ Теперь введи никнейм.", reply_markup=flow_nav_keyboard())
        await callback.answer()
        return

    if st == ProfileStates.waiting_nickname:
        await state.set_state(ProfileStates.waiting_tag)
        data = await state.get_data()
        game = Game(data["game"])
        from app.bot.keyboards.common import flow_nav_keyboard

        await callback.message.answer(
            f"⌨️ Введи игровой тег для <b>{GAME_TITLES[game]}</b>.",
            reply_markup=flow_nav_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if st == ProfileStates.waiting_tag:
        await state.clear()
        await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
        await callback.answer()
        return

    if st == SupportStates.waiting_message:
        await state.clear()
        await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
        await callback.answer()
        return

    if st == BalanceStates.waiting_withdraw_amount:
        await state.set_state(BalanceStates.waiting_withdraw_details)
        await callback.message.answer(
            "🏧 Укажи <b>реквизиты для перевода</b> (карта, СБП, кошелёк — одним сообщением).",
            reply_markup=flow_nav_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if st == BalanceStates.waiting_withdraw_details:
        await state.clear()
        user = await get_or_create_user(session, callback.from_user)
        await callback.message.answer(
            balance_intro_html(user.balance_rub),
            reply_markup=balance_actions_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if not st:
        await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
        await callback.answer()
        return

    await callback.answer()
