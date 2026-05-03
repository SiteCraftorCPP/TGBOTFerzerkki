import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import display_db_user
from app.bot.keyboards.common import (
    MENU_BUTTONS,
    balance_actions_keyboard,
    flow_nav_keyboard,
    main_menu,
    subscription_keyboard,
)
from app.bot.keyboards.topic_moderation import topic_ticket_actions_keyboard
from app.bot.moderation_thread import ensure_user_moderation_thread
from app.bot.states import BalanceStates, SupportStates
from app.bot.telegram_log import telegram_error_details
from app.bot.texts_balance import balance_intro_html
from app.core.config import get_settings
from app.db.repositories import (
    WithdrawalError,
    create_support_ticket,
    create_withdrawal_request,
    get_or_create_user,
    invalidate_user_support_forum_if_mod_chat_mismatch,
    set_user_support_forum_thread,
    update_ticket_forum_thread,
)
from app.services.finance import is_subscription_active

logger = logging.getLogger(__name__)

router = Router()


async def _cancel_if_menu_pressed(message: Message, state: FSMContext) -> bool:
    if (message.text or "").strip() in MENU_BUTTONS:
        await state.clear()
        await message.answer("✅ Действие отменено.", reply_markup=main_menu())
        return True
    return False


@router.message(F.text == "💰 Баланс")
async def balance(message: Message, session: AsyncSession) -> None:
    user = await get_or_create_user(session, message.from_user)
    await message.answer(
        balance_intro_html(user.balance_rub),
        reply_markup=balance_actions_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "balance:topup")
async def balance_topup_placeholder(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "balance:withdraw")
async def balance_withdraw_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BalanceStates.waiting_withdraw_details)
    await callback.message.answer(
        "🏧 Укажи <b>реквизиты для перевода</b> (карта, СБП, кошелёк — одним сообщением).",
        reply_markup=flow_nav_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BalanceStates.waiting_withdraw_details, F.text)
async def balance_withdraw_details(message: Message, state: FSMContext) -> None:
    if await _cancel_if_menu_pressed(message, state):
        return
    details = (message.text or "").strip()
    if len(details) < 8:
        await message.answer(
            "⚠️ Слишком мало данных. Опиши реквизиты подробнее.",
            reply_markup=flow_nav_keyboard(),
        )
        return
    await state.update_data(payout_details=details)
    await state.set_state(BalanceStates.waiting_withdraw_amount)
    await message.answer("💸 Введи сумму вывода в ₽", reply_markup=flow_nav_keyboard())


@router.message(BalanceStates.waiting_withdraw_amount, F.text)
async def balance_withdraw_amount(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    if await _cancel_if_menu_pressed(message, state):
        return
    try:
        amount = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ Нужна сумма одним целым числом.", reply_markup=flow_nav_keyboard())
        return
    data = await state.get_data()
    payout_details = (data.get("payout_details") or "").strip()
    user = await get_or_create_user(session, message.from_user)
    try:
        req = await create_withdrawal_request(session, user.id, amount, payout_details)
    except WithdrawalError as exc:
        await message.answer(
            f"⚠️ {exc}",
            reply_markup=flow_nav_keyboard(),
            parse_mode="HTML",
        )
        return

    await session.refresh(user)
    settings = get_settings()
    mod_chat = settings.moderation_chat_id_int
    tid = await ensure_user_moderation_thread(bot, session, user)
    await session.refresh(user)
    label = display_db_user(user)
    details_safe = html.escape((req.payout_details or "")[:4000])
    note = (
        f"💸 <b>Новая заявка на вывод</b>\n"
        f"👤 {html.escape(label)}\n"
        f"💰 Сумма: <b>{req.amount_rub}</b> ₽\n"
        f"📊 Баланс в боте: <b>{user.balance_rub}</b> ₽\n\n"
        f"📝 <b>Реквизиты для перевода:</b>\n<code>{details_safe}</code>"
    )
    posted = False
    if mod_chat:
        try:
            kwargs: dict = {"parse_mode": "HTML"}
            if tid is not None:
                kwargs["message_thread_id"] = tid
            await bot.send_message(mod_chat, note, **kwargs)
            posted = True
        except Exception:
            logger.exception("Не удалось отправить заявку на вывод в чат модерации")
    if not posted:
        for aid in settings.admin_ids_list:
            try:
                await bot.send_message(aid, note, parse_mode="HTML")
            except Exception:
                logger.exception("Не удалось отправить заявку на вывод админу %s в ЛС", aid)

    await state.clear()
    await message.answer(
        "✅ Заявка отправлена модератору. Решение придёт в бота.\n\n" + balance_intro_html(user.balance_rub),
        reply_markup=balance_actions_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text == "⭐ Подписка")
async def subscription(message: Message, session: AsyncSession) -> None:
    user = await get_or_create_user(session, message.from_user)
    price = get_settings().subscription_price_rub
    status = "✅ активна" if is_subscription_active(user.subscription) else "❌ не активна"
    await message.answer(
        f"⭐ <b>Подписка:</b> {status}\n\n"
        f"После запуска оплаты: комиссия <b>5%</b> вместо <b>15%</b>.\n"
        f"Ориентир цены: <b>{price}</b> ₽/мес.",
        reply_markup=subscription_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text == "💬 Поддержка")
async def support_start(message: Message, state: FSMContext) -> None:
    await state.set_state(SupportStates.waiting_message)
    await message.answer(
        "💬 Опиши проблему <b>одним сообщением</b>.",
        reply_markup=flow_nav_keyboard(),
        parse_mode="HTML",
    )


@router.message(SupportStates.waiting_message)
async def support_message(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    if await _cancel_if_menu_pressed(message, state):
        return
    text = (message.text or "").strip()
    if len(text) < 5:
        await message.answer("⚠️ Слишком коротко. Опиши проблему подробнее.", reply_markup=flow_nav_keyboard())
        return
    user = await get_or_create_user(session, message.from_user)
    ticket = await create_support_ticket(session, user.id, text)
    await session.refresh(user)
    await state.clear()

    mod_chat = get_settings().moderation_chat_id_int
    label = display_db_user(user)
    logger.info(
        "support: новый тикет id=%s user_id=%s telegram_id=%s MODERATION_CHAT_ID=%s",
        ticket.id,
        user.id,
        user.telegram_id,
        mod_chat,
    )
    ticket_html = (
        f"🎫 Обращение <b>#{ticket.id}</b>\n"
        f"👤 {html.escape(label)}\n\n"
        f"{html.escape(text)}\n\n"
        f"🛠 <b>Панель модератора</b> — кнопки ниже."
    )
    mod_kb = topic_ticket_actions_keyboard(ticket.id)

    posted_to_mod_chat = False
    forum_topic_expected = False

    if mod_chat is not None:
        await session.refresh(user)
        await invalidate_user_support_forum_if_mod_chat_mismatch(session, user, mod_chat)
        await session.refresh(user)
        reused_tid = user.support_forum_thread_id
        logger.info(
            "support: тикет=%s mod_chat=%s reused_thread_id=%s moderation_chat_anchor=%s",
            ticket.id,
            mod_chat,
            reused_tid,
            user.support_moderation_chat_id,
        )
        if reused_tid is not None:
            try:
                await update_ticket_forum_thread(session, ticket.id, reused_tid)
                await bot.send_message(
                    mod_chat,
                    ticket_html,
                    message_thread_id=reused_tid,
                    reply_markup=mod_kb,
                    parse_mode="HTML",
                )
                posted_to_mod_chat = True
                logger.info(
                    "support: тикет %s отправлен в существующую подтему thread_id=%s chat=%s",
                    ticket.id,
                    reused_tid,
                    mod_chat,
                )
            except TelegramBadRequest as e:
                logger.warning(
                    "support: повторное использование подтемы не удалось — %s; сбрасываем thread для user=%s",
                    telegram_error_details(e),
                    user.id,
                )
                await set_user_support_forum_thread(session, user.id, None)
                await session.refresh(user)

        if not posted_to_mod_chat:
            topic_title = f"👤 {label}"[:128]
            logger.info(
                "support: создаём forum topic в chat=%s name=%r тикет=%s",
                mod_chat,
                topic_title,
                ticket.id,
            )
            try:
                topic = await bot.create_forum_topic(chat_id=mod_chat, name=topic_title)
                thread_id = topic.message_thread_id
                logger.info(
                    "support: create_forum_topic OK тикет=%s thread_id=%s",
                    ticket.id,
                    thread_id,
                )
                await update_ticket_forum_thread(session, ticket.id, thread_id)
                await set_user_support_forum_thread(session, user.id, thread_id, moderation_chat_id=mod_chat)
                await bot.send_message(
                    mod_chat,
                    ticket_html,
                    message_thread_id=thread_id,
                    reply_markup=mod_kb,
                    parse_mode="HTML",
                )
                posted_to_mod_chat = True
                logger.info("support: тикет %s отправлен в новую подтему thread_id=%s", ticket.id, thread_id)
            except TelegramBadRequest as e:
                err = (getattr(e, "message", None) or str(e)).lower()
                detail = telegram_error_details(e)
                if "not a forum" in err or "chat_not_forum" in err:
                    logger.info(
                        "support: чат %s не форум (%s) — шлём тикет %s без thread_id (общий поток)",
                        mod_chat,
                        detail,
                        ticket.id,
                    )
                    try:
                        await update_ticket_forum_thread(session, ticket.id, None)
                        await bot.send_message(mod_chat, ticket_html, reply_markup=mod_kb, parse_mode="HTML")
                        posted_to_mod_chat = True
                    except Exception:
                        logger.exception("support: отправка тикета %s в чат %s без подтемы", ticket.id, mod_chat)
                else:
                    forum_topic_expected = True
                    await update_ticket_forum_thread(session, ticket.id, None)
                    logger.error(
                        "support: create_forum_topic FAILED тикет=%s chat=%s: %s",
                        ticket.id,
                        mod_chat,
                        detail,
                    )
            except Exception:
                await update_ticket_forum_thread(session, ticket.id, None)
                forum_topic_expected = True
                logger.exception("support: create_forum_topic / отправка тикет=%s chat=%s", ticket.id, mod_chat)

    if not posted_to_mod_chat:
        logger.warning(
            "support: тикет %s не попал в MODERATION_CHAT (forum_topic_expected=%s) — дублируем в ЛС админам",
            ticket.id,
            forum_topic_expected,
        )
        prefix = ""
        if forum_topic_expected:
            prefix = (
                "⚠️ <b>Подтема не создана</b> — проверь, что у бота в группе есть "
                "«Управление темами», и что это действительно форум-группа "
                "(настройки группы → раздел «Темы»).\n\n"
            )
        warn = prefix + ticket_html
        for admin_id in get_settings().admin_ids_list:
            try:
                await bot.send_message(admin_id, warn, parse_mode="HTML")
            except Exception:
                logger.exception("Не удалось отправить обращение админу %s", admin_id)

    await message.answer("✅ Обращение принято.\nОтвет придёт в бота.")


@router.callback_query(F.data == "subscription:buy")
async def buy_subscription(callback: CallbackQuery) -> None:
    await callback.answer()
