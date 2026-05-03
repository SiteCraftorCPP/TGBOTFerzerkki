import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import display_db_user
from app.bot.keyboards.common import (
    MENU_BUTTONS,
    brawl_modes_keyboard,
    flow_nav_keyboard,
    games_keyboard,
    keyboard_with_back,
    main_menu,
    play_keyboard,
    result_keyboard,
)
from app.bot.keyboards.topic_moderation import disputes_keyboard_topic
from app.bot.states import MatchStates
from app.bot.texts import WELCOME_HTML
from app.core.config import get_settings
from app.core.constants import GAME_TITLES, MODE_TITLES, Game, MatchMode, MatchStatus, ResultChoice
from app.db.models import Match
from app.db.repositories import get_or_create_user, get_profile
from app.db.session import SessionLocal
from app.services.finance import MIN_STAKE_RUB
from app.services.matches import (
    MatchError,
    auto_resolve_timeout,
    create_match,
    expire_open_match,
    get_match,
    join_match,
    list_open_matches,
    mark_end,
    submit_result,
    sweep_match_deadlines,
)

router = Router()

logger = logging.getLogger(__name__)

MATCH_LIST_PAGE_SIZE = 8

_STAKE_PROMPT = f"💰 Введи ставку в ₽. Минимум {MIN_STAKE_RUB} ₽"


def _dispute_moderation_html(match: Match) -> str:
    lines: list[str] = []
    for p in match.participants:
        label = html.escape(display_db_user(p.user))
        if p.result == ResultChoice.WIN:
            rtxt = "🏆 заявил победу"
        elif p.result == ResultChoice.LOSS:
            rtxt = "💥 заявил поражение"
        else:
            rtxt = "— нет заявки"
        lines.append(f"• {label}: {rtxt}")
    reason = html.escape(match.dispute_reason or "")
    return (
        f"⚖️ <b>Спорный матч</b> · id <code>{match.id}</code>\n"
        f"{GAME_TITLES[Game(match.game)]} · {MODE_TITLES[MatchMode(match.mode)]}\n"
        f"💰 {match.stake_rub} ₽\n\n"
        + "\n".join(lines)
        + f"\n\n📝 <i>{reason}</i>\n\n<b>Действия:</b> победитель или возврат ставок."
    )


async def _post_dispute_mod_alert(bot: Bot, text: str, kb: InlineKeyboardMarkup, *, topic_title: str) -> None:
    settings = get_settings()
    mod_chat = settings.moderation_chat_id_int

    if mod_chat is None:
        for admin_id in settings.admin_ids_list:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                logger.exception("Спор: не удалось отправить админу %s в ЛС", admin_id)
        return

    posted = False
    fixed_tid = settings.moderation_disputes_thread_id_int
    if fixed_tid is not None:
        try:
            await bot.send_message(
                mod_chat,
                text,
                message_thread_id=fixed_tid,
                reply_markup=kb,
                parse_mode="HTML",
            )
            posted = True
        except Exception:
            logger.exception("Спор: отправка в закреплённую подтему %s", fixed_tid)

    if posted:
        return

    try:
        topic = await bot.create_forum_topic(chat_id=mod_chat, name=topic_title[:128])
        tid = topic.message_thread_id
        await bot.send_message(mod_chat, text, message_thread_id=tid, reply_markup=kb, parse_mode="HTML")
        posted = True
        logger.info("Спор → подтема thread_id=%s", tid)
    except TelegramBadRequest as e:
        err = (getattr(e, "message", None) or str(e)).lower()
        if "not a forum" in err or "chat_not_forum" in err:
            try:
                await bot.send_message(mod_chat, text, reply_markup=kb, parse_mode="HTML")
                posted = True
            except Exception:
                logger.exception("Спор: отправка в общий чат %s", mod_chat)
        else:
            logger.error("Спор: create_forum_topic / отправка: %s", e)
    except Exception:
        logger.exception("Спор: создать подтему в %s", mod_chat)

    if not posted:
        for admin_id in settings.admin_ids_list:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                logger.exception("Спор: запасной DM админу %s", admin_id)


async def notify_moderation_dispute(bot: Bot, match_id: int) -> None:
    async with SessionLocal() as session:
        match = await get_match(session, match_id)
        if match is None or match.status != MatchStatus.DISPUTED:
            return
        text = _dispute_moderation_html(match)
        kb = disputes_keyboard_topic([match])
        topic_title = f"⚖️ Спор · {GAME_TITLES[Game(match.game)]} · {match.stake_rub}₽"
    await _post_dispute_mod_alert(bot, text, kb, topic_title=topic_title)


async def match_flow_back_handler(callback: CallbackQuery, state: FSMContext) -> bool:
    st = await state.get_state()
    if st is None or not str(st).startswith("MatchStates"):
        return False

    if st == MatchStates.play_menu:
        await state.clear()
        await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
        return True

    if st == MatchStates.pick_game:
        await state.set_state(MatchStates.play_menu)
        await state.update_data(game=None, mode=None, match_nav_stack=[])
        await callback.message.answer("⚔️ Что делаем?", reply_markup=play_keyboard())
        return True

    if st == MatchStates.pick_mode:
        await state.set_state(MatchStates.pick_game)
        await state.update_data(mode=None, match_nav_stack=[])
        await callback.message.answer(
            "🎮 Выбери игру для матча.",
            reply_markup=keyboard_with_back(games_keyboard(prefix="create_game")),
        )
        return True

    if st == MatchStates.waiting_stake:
        data = await state.get_data()
        mstack: list = list(data.get("match_nav_stack") or [])
        if not mstack:
            await state.clear()
            await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
            return True
        top = mstack[-1]
        if top == "mode":
            await state.set_state(MatchStates.pick_mode)
            await state.update_data(mode=None, match_nav_stack=[])
            await callback.message.answer(
                "🤝 Выбери режим.",
                reply_markup=keyboard_with_back(brawl_modes_keyboard()),
            )
            return True
        if top == "games":
            await state.set_state(MatchStates.pick_game)
            await state.update_data(game=None, mode=None, match_nav_stack=[])
            await callback.message.answer(
                "🎮 Выбери игру для матча.",
                reply_markup=keyboard_with_back(games_keyboard(prefix="create_game")),
            )
            return True
        await state.clear()
        await callback.message.answer(WELCOME_HTML, reply_markup=main_menu(), parse_mode="HTML")
        return True

    return False


async def _cancel_if_menu_pressed(message: Message, state: FSMContext) -> bool:
    if (message.text or "").strip() in MENU_BUTTONS:
        await state.clear()
        await message.answer("✅ Действие отменено.", reply_markup=main_menu())
        return True
    return False


def _build_open_matches_list(matches: list, page: int) -> tuple[str, InlineKeyboardMarkup]:
    per_page = MATCH_LIST_PAGE_SIZE
    total = len(matches)
    max_page = (total - 1) // per_page if total else 0
    page = max(0, min(page, max_page))
    start = page * per_page
    chunk = matches[start : start + per_page]
    lines = ["🔍 <b>Открытые матчи</b>", ""]
    for i, m in enumerate(chunk):
        creator = next(p.user for p in m.participants if p.is_creator)
        author = html.escape(display_db_user(creator))
        n = start + i + 1
        lines.append(
            f"{n}. {GAME_TITLES[Game(m.game)]} · {MODE_TITLES[MatchMode(m.mode)]} · {m.stake_rub} ₽ · {author}"
        )
    lines.append("")
    lines.append(f"<i>Страница {page + 1} из {max_page + 1}</i>")
    text = "\n".join(lines)
    rows: list[list[InlineKeyboardButton]] = []
    for m in chunk:
        label = f"🤝 {m.stake_rub} ₽ · {GAME_TITLES[Game(m.game)]}"[:64]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"match:join:{m.id}")])
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Стр.", callback_data=f"play:list:p:{page - 1}"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton(text="Стр. ➡️", callback_data=f"play:list:p:{page + 1}"))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="flow:back")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "⚔️ Играть")
async def play(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    await _sweep_matches_db(bot, session)
    await state.set_state(MatchStates.play_menu)
    await state.update_data(match_nav_stack=[], game=None, mode=None)
    await message.answer("⚔️ Что делаем?", reply_markup=play_keyboard())


@router.callback_query(F.data == "play:create")
async def create_match_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MatchStates.pick_game)
    await state.update_data(match_nav_stack=[], game=None, mode=None)
    await callback.message.answer(
        "🎮 Выбери игру для матча.",
        reply_markup=keyboard_with_back(games_keyboard(prefix="create_game")),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("create_game:"))
async def create_match_game(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user = await get_or_create_user(session, callback.from_user)
    game = Game(callback.data.split(":")[-1])
    if await get_profile(session, user.id, game) is None:
        await callback.message.answer(
            "⚠️ Для этой игры профиль не заполнен.\nЗайди в 👤 Профиль и добавь тег, ник и кубки."
        )
        await callback.answer()
        return
    await state.update_data(game=game)
    if game == Game.BRAWL_STARS:
        await state.update_data(match_nav_stack=[])
        await state.set_state(MatchStates.pick_mode)
        await callback.message.answer(
            "🤝 Выбери режим.",
            reply_markup=keyboard_with_back(brawl_modes_keyboard()),
        )
    else:
        await state.update_data(mode=MatchMode.DUEL, match_nav_stack=["games"])
        await state.set_state(MatchStates.waiting_stake)
        await callback.message.answer(
            _STAKE_PROMPT,
            reply_markup=flow_nav_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("mode:"))
async def create_match_mode(callback: CallbackQuery, state: FSMContext) -> None:
    mode = MatchMode(callback.data.split(":")[-1])
    await state.update_data(mode=mode, match_nav_stack=["games", "mode"])
    await state.set_state(MatchStates.waiting_stake)
    await callback.message.answer(
        _STAKE_PROMPT,
        reply_markup=flow_nav_keyboard(),
    )
    await callback.answer()


@router.message(MatchStates.waiting_stake)
async def create_match_stake(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    if await _cancel_if_menu_pressed(message, state):
        return
    await _sweep_matches_db(bot, session)
    try:
        stake = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ Ставка должна быть числом.", reply_markup=flow_nav_keyboard())
        return

    data = await state.get_data()
    user = await get_or_create_user(session, message.from_user)
    try:
        match = await create_match(session, user, Game(data["game"]), MatchMode(data["mode"]), stake)
    except MatchError as exc:
        await message.answer(str(exc), reply_markup=flow_nav_keyboard())
        return
    except (ValueError, KeyError) as exc:
        await message.answer(
            str(exc) if isinstance(exc, ValueError) else "⚠️ Сначала выбери игру и режим: ⚔️ Играть.",
            reply_markup=flow_nav_keyboard(),
        )
        return

    await state.clear()
    asyncio.create_task(expire_match_later(bot, match.id))
    await message.answer(
        f"✅ <b>Матч создан</b> на 3 минуты.\n"
        f"🎮 {GAME_TITLES[Game(match.game)]}\n"
        f"⚡ {MODE_TITLES[MatchMode(match.mode)]}\n"
        f"💰 Ставка: {match.stake_rub} ₽",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data.startswith("play:list"))
async def list_matches(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    await _sweep_matches_db(bot, session)
    if await state.get_state() != MatchStates.play_menu:
        await state.set_state(MatchStates.play_menu)
        await state.update_data(match_nav_stack=[], game=None, mode=None)
    user = await get_or_create_user(session, callback.from_user)
    matches = await list_open_matches(session, user.id)
    page = 0
    if callback.data.startswith("play:list:p:"):
        try:
            page = int(callback.data.split(":")[-1])
        except ValueError:
            page = 0
    if not matches:
        await callback.message.answer(
            "🔍 Нет открытых матчей",
            reply_markup=flow_nav_keyboard(),
        )
        await callback.answer()
        return
    caption, kb = _build_open_matches_list(matches, page)
    if callback.data == "play:list":
        await callback.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    else:
        try:
            await callback.message.edit_text(caption, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest:
            await callback.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("match:join:"))
async def join_match_handler(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    await _sweep_matches_db(bot, session)
    match_id = int(callback.data.split(":")[-1])
    user = await get_or_create_user(session, callback.from_user)
    try:
        match = await join_match(session, match_id, user)
    except MatchError as exc:
        await callback.message.answer(str(exc))
        await callback.answer()
        return

    asyncio.create_task(result_timeout_later(bot, match.id))
    await notify_match_started(bot, match.id)
    await callback.answer("🤝 Ты в матче!")


@router.callback_query(F.data.startswith("match:end:"))
async def end_match_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    match_id = int(callback.data.split(":")[-1])
    user = await get_or_create_user(session, callback.from_user)
    try:
        match = await mark_end(session, match_id, user)
    except MatchError as exc:
        await callback.message.answer(str(exc))
        await callback.answer()
        return
    await callback.message.answer(
        "🏁 Ок, матч отмечен как сыгранный.\nТеперь жми 🏆 Победа или 💥 Поражение.",
        reply_markup=result_keyboard(match.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("match:result:"))
async def result_handler(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    _, _, raw_match_id, raw_result = callback.data.split(":")
    user = await get_or_create_user(session, callback.from_user)
    try:
        match = await submit_result(session, int(raw_match_id), user, ResultChoice(raw_result))
    except MatchError as exc:
        await callback.message.answer(str(exc))
        await callback.answer()
        return

    await notify_match_status(bot, match.id)
    await callback.answer("✅ Результат принят.")


async def expire_match_later(bot: Bot, match_id: int) -> None:
    await asyncio.sleep(180)
    async with SessionLocal() as session:
        match = await expire_open_match(session, match_id)
        if (
            match
            and match.status == MatchStatus.EXPIRED
            and match.participants
        ):
            creator = next((item.user for item in match.participants if item.is_creator), None)
            if creator:
                await bot.send_message(creator.telegram_id, f"⏰ Матч истёк без соперника. 💸 Ставка возвращена.")


async def result_timeout_later(bot: Bot, match_id: int) -> None:
    await asyncio.sleep(600)
    async with SessionLocal() as session:
        match = await auto_resolve_timeout(session, match_id)
        if match:
            await notify_match_status(bot, match.id)


async def notify_match_started(bot: Bot, match_id: int) -> None:
    async with SessionLocal() as session:
        match = await get_match(session, match_id)
        if match is None:
            logger.warning("notify_match_started: матч %s не найден", match_id)
            return
        if len(match.participants) < 2:
            logger.warning(
                "notify_match_started: у матча %s участников %s (ожидалось 2)",
                match_id,
                len(match.participants),
            )
            return
        profiles = {
            participant.user_id: await get_profile(session, participant.user_id, match.game)
            for participant in match.participants
        }
        for participant in match.participants:
            opponents = [item for item in match.participants if item.user_id != participant.user_id]
            if not opponents:
                continue
            opponent = opponents[0]
            opponent_profile = profiles.get(opponent.user_id)
            if opponent_profile is None:
                logger.warning("notify_match_started: нет профиля соперника user_id=%s", opponent.user_id)
                continue
            text = (
                f"🎯 <b>Матч собран!</b>\n"
                f"🥊 Соперник: <b>{opponent_profile.nickname}</b>\n"
                f"🏷 Тег: <code>{opponent_profile.game_tag}</code>\n"
                f"🏆 Кубки: {opponent_profile.trophies}\n\n"
                "После игры жми 🏁 <b>Конец</b> и выбери исход.\n⏱ На результат — <b>10 минут</b>."
            )
            await bot.send_message(participant.user.telegram_id, text, reply_markup=result_keyboard(match.id))


async def notify_match_status(bot: Bot, match_id: int, *, only_terminal: bool = False) -> None:
    async with SessionLocal() as session:
        match = await get_match(session, match_id)
        if match is None:
            return
        if match.status == MatchStatus.FINISHED:
            for participant in match.participants:
                if match.winner_user_id == participant.user_id:
                    await bot.send_message(participant.user.telegram_id, f"🏆 Матч закрыт. <b>Ты победил!</b>")
                else:
                    await bot.send_message(participant.user.telegram_id, f"💥 Матч закрыт. Победа соперника.")
        elif match.status == MatchStatus.DISPUTED:
            for participant in match.participants:
                await bot.send_message(
                    participant.user.telegram_id,
                    f"⚖️ Матч в <b>споре</b>.\n📝 Причина: {match.dispute_reason}\nОжидай решения по спору.",
                )
            await notify_moderation_dispute(bot, match.id)
        elif only_terminal:
            return
        else:
            for participant in match.participants:
                await bot.send_message(
                    participant.user.telegram_id,
                    f"⏳ Ждём второго игрока.\nНажми 🏁 <b>Конец</b> и укажи 🏆/💥.",
                )


async def notify_match_refunded(bot: Bot, match_id: int) -> None:
    async with SessionLocal() as session:
        match = await get_match(session, match_id)
        if match is None or match.status != MatchStatus.CANCELLED:
            return
        for participant in match.participants:
            try:
                await bot.send_message(
                    participant.user.telegram_id,
                    "♻️ Матч отменён: ставка возвращена на баланс в боте (таймаут или автозавершение).",
                )
            except Exception:
                logger.exception("Не удалось уведомить о возврате пользователя %s", participant.user_id)


async def _sweep_matches_db(bot: Bot, session: AsyncSession) -> None:
    async def _notify(mid: int) -> None:
        await notify_match_status(bot, mid, only_terminal=True)

    async def _refund(mid: int) -> None:
        await notify_match_refunded(bot, mid)

    await sweep_match_deadlines(
        session,
        on_match_auto_resolved=_notify,
        on_match_refunded=_refund,
    )
