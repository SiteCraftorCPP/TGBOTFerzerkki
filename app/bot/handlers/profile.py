from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import display_db_user
from app.bot.keyboards.common import (
    MENU_BUTTONS,
    flow_nav_keyboard,
    main_menu,
    profile_keyboard,
)
from app.bot.states import ProfileStates
from app.core.constants import GAME_TITLES, Game, MatchStatus
from app.db.repositories import get_or_create_user, list_profiles, list_user_matches, upsert_profile
from app.services.finance import is_subscription_active

router = Router()


async def _cancel_if_menu_pressed(message: Message, state: FSMContext) -> bool:
    if (message.text or "").strip() in MENU_BUTTONS:
        await state.clear()
        await message.answer("✅ Действие отменено.", reply_markup=main_menu())
        return True
    return False


@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message, session: AsyncSession) -> None:
    user = await get_or_create_user(session, message.from_user)
    profiles = {profile.game: profile for profile in await list_profiles(session, user.id)}
    who = display_db_user(user)
    sub = "✅ активна" if is_subscription_active(user.subscription) else "❌ нет"
    lines = [
        f"👤 <b>Профиль</b> — {who}",
        f"💰 <b>Баланс:</b> {user.balance_rub} ₽",
        f"⭐ <b>Подписка:</b> {sub}",
        "",
    ]
    for game, title in GAME_TITLES.items():
        profile = profiles.get(game)
        if profile is None:
            lines.append(f"🎮 <b>{title}</b>: не заполнено")
        else:
            lines.append(
                f"🎮 <b>{title}</b>: {profile.nickname}, тег {profile.game_tag}, 🏆 {profile.trophies}"
            )
    await message.answer("\n".join(lines), reply_markup=profile_keyboard(), parse_mode="HTML")


@router.callback_query(F.data.startswith("profile:edit:"))
async def edit_profile(callback: CallbackQuery, state: FSMContext) -> None:
    game = Game(callback.data.split(":")[-1])
    await state.update_data(game=game)
    await state.set_state(ProfileStates.waiting_tag)
    await callback.message.answer(
        f"⌨️ Введи игровой тег для <b>{GAME_TITLES[game]}</b>.",
        reply_markup=flow_nav_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ProfileStates.waiting_tag)
async def profile_tag(message: Message, state: FSMContext) -> None:
    if await _cancel_if_menu_pressed(message, state):
        return
    tag = (message.text or "").strip()
    if len(tag) < 2:
        await message.answer("⚠️ Тег слишком короткий. Введи нормальный игровой тег.", reply_markup=flow_nav_keyboard())
        return
    await state.update_data(game_tag=tag)
    await state.set_state(ProfileStates.waiting_nickname)
    await message.answer("✏️ Теперь введи никнейм.", reply_markup=flow_nav_keyboard())


@router.message(ProfileStates.waiting_nickname)
async def profile_nickname(message: Message, state: FSMContext) -> None:
    if await _cancel_if_menu_pressed(message, state):
        return
    nickname = (message.text or "").strip()
    if len(nickname) < 2:
        await message.answer("⚠️ Ник слишком короткий.", reply_markup=flow_nav_keyboard())
        return
    await state.update_data(nickname=nickname)
    await state.set_state(ProfileStates.waiting_trophies)
    await message.answer("🏆 Введи количество кубков числом.", reply_markup=flow_nav_keyboard())


@router.message(ProfileStates.waiting_trophies)
async def profile_trophies(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if await _cancel_if_menu_pressed(message, state):
        return
    try:
        trophies = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ Кубки должны быть числом.", reply_markup=flow_nav_keyboard())
        return
    if trophies < 0:
        await message.answer("⚠️ Кубки не могут быть отрицательными.", reply_markup=flow_nav_keyboard())
        return

    data = await state.get_data()
    user = await get_or_create_user(session, message.from_user)
    game = Game(data["game"])
    await upsert_profile(session, user.id, game, data["game_tag"], data["nickname"], trophies)
    await state.clear()
    await message.answer(f"✅ Профиль <b>{GAME_TITLES[game]}</b> обновлён.", reply_markup=profile_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "profile:history")
async def profile_history(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_or_create_user(session, callback.from_user)
    matches = await list_user_matches(session, user.id)
    if not matches:
        await callback.message.answer("📭 История игр пока пустая.", reply_markup=flow_nav_keyboard())
        await callback.answer()
        return
    lines = ["🏆 <b>Последние игры:</b>"]
    for match in matches:
        if match.status == MatchStatus.DISPUTED or match.winner_user_id is None:
            result = "⚖️ спор"
        elif match.winner_user_id == user.id:
            result = "🏆 победа"
        else:
            result = "💥 поражение"
        lines.append(f"• {GAME_TITLES[Game(match.game)]}, 💰 {match.stake_rub} ₽ — {result}")
    await callback.message.answer("\n".join(lines), reply_markup=flow_nav_keyboard(), parse_mode="HTML")
    await callback.answer()

