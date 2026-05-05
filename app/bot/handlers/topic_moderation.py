"""Инлайн-действия модератора внутри подтемы MODERATION_CHAT_ID (форум)."""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import display_db_user
from app.bot.keyboards.topic_moderation import (
    disputes_keyboard_topic,
    tickets_keyboard_topic,
    topic_fsm_cancel_keyboard,
)
from app.bot.states import TopicModStates
from app.core.config import get_settings
from app.core.constants import GAME_TITLES, MODE_TITLES, Game, MatchMode
from app.db.models import SupportTicket
from app.db.repositories import (
    add_transaction,
    close_ticket,
    get_user_by_id,
    list_open_tickets,
    resolve_user_identifier,
)
from app.services.matches import MatchError, cancel_match, get_match, list_disputes
from app.bot.staff import acts_as_moderator_callback, acts_as_moderator_message

logger = logging.getLogger(__name__)

router = Router()


def _mod_chat_id() -> int | None:
    return get_settings().moderation_chat_id_int


class InModChatTopic(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        mc = _mod_chat_id()
        return mc is not None and message.chat.id == mc and message.message_thread_id is not None


async def _answer_in_thread(message: Message, bot: Bot, text: str, *, parse_mode: str = "HTML") -> None:
    tid = message.message_thread_id
    if tid is None:
        logger.error("_answer_in_thread: message_thread_id is None")
        return
    await bot.send_message(message.chat.id, text, message_thread_id=tid, parse_mode=parse_mode)


async def _wrong_thread_hint(bot: Bot, data: dict) -> None:
    mc = _mod_chat_id()
    tid = data.get("mod_thread_id")
    if mc is None or tid is None:
        return
    try:
        await bot.send_message(
            mc,
            "⚠️ Ответь в той же подтеме, где бот запросил данные.",
            message_thread_id=int(tid),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("wrong_thread_hint")


async def _callback_answer_in_thread(
    bot: Bot,
    chat_id: int,
    thread_id: int,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    await bot.send_message(
        chat_id,
        text,
        message_thread_id=thread_id,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )


@router.callback_query(F.data == "tmod:cancel_fsm")
async def tmod_cancel_fsm(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not acts_as_moderator_callback(callback, _mod_chat_id()):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    mc = _mod_chat_id()
    if mc is None or callback.message.chat.id != mc:
        await callback.answer("Только в чате модерации.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Отменено.")
    tid = callback.message.message_thread_id
    if tid is not None:
        try:
            await bot.send_message(mc, "✅ Ввод отменён.", message_thread_id=tid)
        except Exception:
            logger.exception("tmod_cancel_fsm ack")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


@router.callback_query(
    (F.data.startswith("tmod:close:") | F.data.startswith("tmod:pick:"))
)
async def tmod_close_start(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not acts_as_moderator_callback(callback, _mod_chat_id()):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    mc = _mod_chat_id()
    if mc is None or callback.message.chat.id != mc or callback.message.message_thread_id is None:
        await callback.answer("Только в чате модерации.", show_alert=True)
        return
    try:
        ticket_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Битая кнопка.", show_alert=True)
        return

    await state.set_state(TopicModStates.waiting_close_reply)
    await state.update_data(
        ticket_id=ticket_id,
        mod_thread_id=callback.message.message_thread_id,
    )
    await callback.answer()
    await _callback_answer_in_thread(
        bot,
        mc,
        callback.message.message_thread_id,
        f"📝 Тикет <b>#{ticket_id}</b>\n\nНапиши <b>одним сообщением</b> ответ пользователю — тикет закроется.",
        parse_mode="HTML",
        reply_markup=topic_fsm_cancel_keyboard(),
    )


@router.callback_query(F.data == "tmod:disputes")
async def tmod_disputes(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not acts_as_moderator_callback(callback, _mod_chat_id()):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    mc = _mod_chat_id()
    if mc is None or callback.message.chat.id != mc or callback.message.message_thread_id is None:
        await callback.answer("Только в чате модерации.", show_alert=True)
        return

    matches = await list_disputes(session)
    if not matches:
        await callback.answer("Спорных матчей нет.", show_alert=True)
        return
    lines = ["⚖️ <b>Спорные матчи</b>", "Кого объявить победителем:"]
    for m in matches:
        names = " vs ".join(display_db_user(p.user) for p in m.participants)
        lines.append(
            f"\n{GAME_TITLES[Game(m.game)]} · {MODE_TITLES[MatchMode(m.mode)]}\n"
            f"💰 {m.stake_rub} ₽ · {names}\n📝 <i>{html.escape(m.dispute_reason or '')}</i>"
        )
    await bot.send_message(
        mc,
        "\n".join(lines),
        message_thread_id=callback.message.message_thread_id,
        reply_markup=disputes_keyboard_topic(matches),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "tmod:cancel")
async def tmod_cancel_start(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not acts_as_moderator_callback(callback, _mod_chat_id()):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    mc = _mod_chat_id()
    tid = callback.message.message_thread_id
    if mc is None or callback.message.chat.id != mc or tid is None:
        await callback.answer("Только в чате модерации.", show_alert=True)
        return
    await state.set_state(TopicModStates.waiting_cancel_match)
    await state.update_data(mod_thread_id=tid)
    await callback.answer()
    await _callback_answer_in_thread(
        bot,
        mc,
        tid,
        "🚫 Введи <b>ID матча</b> одним числом — матч отменится, ставки вернутся участникам.",
        parse_mode="HTML",
        reply_markup=topic_fsm_cancel_keyboard(),
    )


@router.callback_query(F.data.in_(("tmod:+bal", "tmod:-bal")))
async def tmod_balance_start(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not acts_as_moderator_callback(callback, _mod_chat_id()):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    mc = _mod_chat_id()
    tid = callback.message.message_thread_id
    if mc is None or callback.message.chat.id != mc or tid is None:
        await callback.answer("Только в чате модерации.", show_alert=True)
        return
    if callback.data == "tmod:+bal":
        await state.set_state(TopicModStates.balance_add_line)
        text = (
            "➕ <b>Начислить баланс</b>\n\n"
            "Одной строкой: <code>@username</code> или telegram_id, затем сумма ₽."
        )
    else:
        await state.set_state(TopicModStates.balance_sub_line)
        text = (
            "➖ <b>Списать с баланса</b>\n\n"
            "Одной строкой: <code>@username</code> или telegram_id, затем сумма ₽."
        )
    await state.update_data(mod_thread_id=tid)
    await callback.answer()
    await _callback_answer_in_thread(bot, mc, tid, text, parse_mode="HTML", reply_markup=topic_fsm_cancel_keyboard())


@router.callback_query(F.data == "tmod:tickets")
async def tmod_tickets(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not acts_as_moderator_callback(callback, _mod_chat_id()):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    mc = _mod_chat_id()
    tid = callback.message.message_thread_id
    if mc is None or callback.message.chat.id != mc or tid is None:
        await callback.answer("Только в чате модерации.", show_alert=True)
        return
    tickets_list = await list_open_tickets(session)
    if not tickets_list:
        await callback.answer("Открытых тикетов нет.", show_alert=True)
        return
    await bot.send_message(
        mc,
        "📋 <b>Открытые тикеты</b>\n\nВыбери — затем введи ответ одним сообщением.",
        message_thread_id=tid,
        reply_markup=tickets_keyboard_topic(tickets_list),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "tmod:collapse")
async def tmod_collapse(callback: CallbackQuery) -> None:
    if not acts_as_moderator_callback(callback, _mod_chat_id()):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.message.edit_text("✓")
    await callback.answer()


@router.message(StateFilter(TopicModStates.waiting_close_reply), InModChatTopic(), F.text)
async def topic_close_reply_body(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    if not acts_as_moderator_message(message, _mod_chat_id()):
        uid = message.from_user.id if message.from_user else None
        logger.warning("topic_close_reply: отклонено user_id=%s (не админ в этом чате)", uid)
        await _answer_in_thread(
            message,
            bot,
            "⚠️ Нет прав на закрытие тикета из этой группы (аккаунт не в ADMIN_IDS или не чат модерации).",
        )
        return
    data = await state.get_data()
    if message.message_thread_id != data.get("mod_thread_id"):
        logger.warning(
            "topic_close_reply: неверная подтема admin=%s got_thread=%s нужна=%s ticket_id=%s",
            message.from_user.id,
            message.message_thread_id,
            data.get("mod_thread_id"),
            data.get("ticket_id"),
        )
        await _wrong_thread_hint(bot, data)
        return
    ticket_id = int(data["ticket_id"])
    body = (message.text or "").strip()
    if not body:
        await _answer_in_thread(message, bot, "⚠️ Пустой текст.")
        return

    existing = await session.get(SupportTicket, ticket_id)
    thread_id = existing.forum_thread_id if existing else None
    ticket = await close_ticket(session, ticket_id, body)
    if ticket is None:
        await state.clear()
        await _answer_in_thread(message, bot, "❌ Тикет не найден или уже закрыт.")
        return

    user = await get_user_by_id(session, ticket.user_id)
    mod_chat = _mod_chat_id()
    if user:
        try:
            await bot.send_message(user.telegram_id, f"💬 Ответ поддержки по обращению #{ticket.id}:\n{body}")
        except Exception:
            logger.exception("Не удалось отправить ответ пользователю %s", ticket.user_id)
    if thread_id and mod_chat:
        try:
            await bot.send_message(
                mod_chat,
                f"📨 <b>Тикет закрыт</b>, ответ ушёл в бота пользователю.\n\n{html.escape(body)}",
                message_thread_id=thread_id,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Не удалось продублировать ответ в ветку")

    await state.clear()
    await _answer_in_thread(message, bot, f"✅ Тикет #{ticket.id} закрыт.")


@router.message(StateFilter(TopicModStates.waiting_cancel_match), InModChatTopic(), F.text)
async def topic_cancel_match(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    if not acts_as_moderator_message(message, _mod_chat_id()):
        return
    data = await state.get_data()
    if message.message_thread_id != data.get("mod_thread_id"):
        await _wrong_thread_hint(bot, data)
        return
    try:
        match_id = int((message.text or "").strip())
    except ValueError:
        await _answer_in_thread(message, bot, "⚠️ Нужен ID матча одним числом.")
        return
    try:
        match = await cancel_match(session, match_id)
    except MatchError as exc:
        await _answer_in_thread(message, bot, f"❌ {exc}")
        return
    full = await get_match(session, match.id)
    participants = full.participants if full else ()
    await state.clear()
    for p in participants:
        try:
            await bot.send_message(
                p.user.telegram_id,
                f"♻️ Матч отменён модератором, ставка {match.stake_rub} ₽ возвращена на баланс.",
            )
        except Exception:
            logger.exception("notify cancel match user %s", p.user_id)
    await _answer_in_thread(message, bot, f"♻️ Матч отменён, ставки возвращены.")


@router.message(StateFilter(TopicModStates.balance_add_line), InModChatTopic(), F.text)
async def topic_balance_add(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    if not acts_as_moderator_message(message, _mod_chat_id()):
        return
    data = await state.get_data()
    if message.message_thread_id != data.get("mod_thread_id"):
        await _wrong_thread_hint(bot, data)
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await _answer_in_thread(message, bot, "⚠️ Нужны: кому и сколько ₽.")
        return
    raw_user, amount_s = parts[0], parts[1].strip()
    try:
        amount = int(amount_s)
    except ValueError:
        await _answer_in_thread(message, bot, "⚠️ Сумма — целое число.")
        return
    user = await resolve_user_identifier(session, raw_user)
    if user is None:
        await _answer_in_thread(message, bot, "❌ Пользователь не найден.")
        return
    await add_transaction(session, user, amount, "admin_add", "Начисление модератором")
    await session.commit()
    await state.clear()
    try:
        await bot.send_message(
            user.telegram_id,
            f"💰 Тебе начислено <b>{amount}</b> ₽ модератором. Баланс: <b>{user.balance_rub}</b> ₽",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Не удалось уведомить пользователя о начислении")
    await _answer_in_thread(
        message,
        bot,
        f"✅ {html.escape(display_db_user(user))} — баланс <b>{user.balance_rub}</b> ₽. Пользователь уведомлён.",
    )


@router.message(StateFilter(TopicModStates.balance_sub_line), InModChatTopic(), F.text)
async def topic_balance_sub(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    if not acts_as_moderator_message(message, _mod_chat_id()):
        return
    data = await state.get_data()
    if message.message_thread_id != data.get("mod_thread_id"):
        await _wrong_thread_hint(bot, data)
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await _answer_in_thread(message, bot, "⚠️ Нужны: кому и сколько ₽.")
        return
    raw_user, amount_s = parts[0], parts[1].strip()
    try:
        amount = int(amount_s)
    except ValueError:
        await _answer_in_thread(message, bot, "⚠️ Сумма — целое число.")
        return
    user = await resolve_user_identifier(session, raw_user)
    if user is None:
        await _answer_in_thread(message, bot, "❌ Пользователь не найден.")
        return
    if user.balance_rub < amount:
        await _answer_in_thread(message, bot, "⚠️ На балансе меньше этой суммы.")
        return
    await add_transaction(session, user, -amount, "admin_sub", "Списание модератором")
    await session.commit()
    await state.clear()
    try:
        await bot.send_message(
            user.telegram_id,
            f"💸 С баланса списано <b>{amount}</b> ₽ модератором. Баланс: <b>{user.balance_rub}</b> ₽",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Не удалось уведомить пользователя о списании")
    await _answer_in_thread(
        message,
        bot,
        f"✅ {html.escape(display_db_user(user))} — баланс <b>{user.balance_rub}</b> ₽. Пользователь уведомлён.",
    )
