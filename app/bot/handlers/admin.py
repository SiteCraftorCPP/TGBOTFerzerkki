import logging
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import display_db_user
from app.bot.keyboards.admin import (
    admin_back_keyboard,
    admin_main_keyboard,
    disputes_keyboard,
    tickets_keyboard,
    withdrawals_keyboard,
)
from app.bot.states import AdminStates
from app.core.config import get_settings
from app.core.constants import GAME_TITLES, MODE_TITLES, Game, MatchMode, WithdrawalStatus
from app.db.models import SupportTicket
from app.db.repositories import (
    add_transaction,
    approve_withdrawal_request,
    close_ticket,
    get_user_by_id,
    list_open_tickets,
    list_pending_withdrawals,
    reject_withdrawal_request,
    resolve_user_identifier,
)
from app.services.matches import MatchError, admin_resolve_match, cancel_match, list_disputes

logger = logging.getLogger(__name__)

router = Router()

PANEL_TEXT = "🛠 <b>Панель модератора</b>"


def is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in get_settings().admin_ids_list


async def _redraw_withdrawals_list(callback: CallbackQuery, session: AsyncSession) -> None:
    pending = await list_pending_withdrawals(session)
    if not pending:
        await callback.message.edit_text(
            "💸 <b>Заявки на вывод</b>\n\n✨ Ожидающих заявок нет.",
            reply_markup=admin_back_keyboard(),
            parse_mode="HTML",
        )
        return
    lines: list[str] = ["💸 <b>Заявки на вывод</b>\n"]
    for r in pending:
        label = html.escape(display_db_user(r.user))
        det = (getattr(r, "payout_details", None) or "").strip()
        det_prev = html.escape(det[:48] + ("…" if len(det) > 48 else "")) if det else "—"
        lines.append(f"👤 {label} — 💰 <b>{r.amount_rub}</b> ₽ — 📝 {det_prev}")
    lines.append("\n✅ одобрить · ❌ отклонить")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=withdrawals_keyboard(pending),
        parse_mode="HTML",
    )


async def _notify_user_withdrawal(
    bot: Bot,
    session: AsyncSession,
    req,
    *,
    approved: bool,
    auto_insufficient: bool = False,
) -> None:
    user = await get_user_by_id(session, req.user_id)
    if not user:
        return
    mod_chat = get_settings().moderation_chat_id_int
    tid = user.support_forum_thread_id
    details_esc = html.escape((getattr(req, "payout_details", None) or "")[:2000])
    if approved:
        pm = (
            f"✅ Модератор подтвердил перевод по твоим реквизитам.\n"
            f"💸 С баланса в боте списано <b>{req.amount_rub}</b> ₽ — проверь зачисление у себя."
        )
        thread = (
            f"✅ Вывод одобрён модератором.\n"
            f"💰 С баланса в боте списано <b>{req.amount_rub}</b> ₽.\n"
            f"📝 <b>Реквизиты:</b>\n<code>{details_esc}</code>"
        )
    elif auto_insufficient:
        pm = (
            f"⚠️ Заявка на вывод отклонена: на балансе не хватило "
            f"<b>{req.amount_rub}</b> ₽ к моменту проверки."
        )
        thread = (
            f"⚠️ Вывод снят — не хватило баланса.\n"
            f"💰 Требовалось <b>{req.amount_rub}</b> ₽."
        )
    else:
        pm = "❌ Заявка на вывод отклонена модератором. Баланс не менялся."
        thread = "❌ Вывод отклонён модератором."
    try:
        await bot.send_message(user.telegram_id, pm, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось уведомить пользователя о выводе")
    if mod_chat and tid:
        try:
            await bot.send_message(mod_chat, thread, message_thread_id=tid, parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось продублировать решение по выводу в подтему")


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer(PANEL_TEXT, reply_markup=admin_main_keyboard())


@router.callback_query(F.data == "adm:home")
async def cb_home(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(PANEL_TEXT, reply_markup=admin_main_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm:+bal")
async def cb_add_balance(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminStates.balance_add_line)
    await callback.message.edit_text(
        "➕ <b>Начислить баланс</b>\n\n"
        "Одной строкой через пробел:\n"
        "<code>@username</code> или <code>telegram_id</code>, затем сумма в ₽.",
        reply_markup=admin_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:-bal")
async def cb_sub_balance(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminStates.balance_sub_line)
    await callback.message.edit_text(
        "➖ <b>Списать с баланса</b>\n\n"
        "Одной строкой через пробел:\n"
        "<code>@username</code> или <code>telegram_id</code>, затем сумма в ₽.",
        reply_markup=admin_back_keyboard(),
    )
    await callback.answer()


@router.message(StateFilter(AdminStates.balance_add_line), F.text)
async def on_balance_add_line(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("⚠️ Нужны два значения: кому и сколько ₽.", reply_markup=admin_back_keyboard())
        return
    raw_user, amount_s = parts[0], parts[1].strip()
    try:
        amount = int(amount_s)
    except ValueError:
        await message.answer("⚠️ Сумма должна быть целым числом.", reply_markup=admin_back_keyboard())
        return
    user = await resolve_user_identifier(session, raw_user)
    if user is None:
        await message.answer("❌ Пользователь не найден — нужен /start у бота.", reply_markup=admin_back_keyboard())
        return
    await add_transaction(session, user, amount, "admin_add", "Начисление модератором")
    await session.commit()
    await state.clear()
    try:
        await bot.send_message(
            user.telegram_id,
            f"💰 Тебе начислено <b>{amount}</b> ₽ модератором. Баланс: <b>{user.balance_rub}</b> ₽",
        )
    except Exception:
        logger.exception("Не удалось уведомить пользователя о начислении")
    await message.answer(
        f"✅ {display_db_user(user)} — баланс <b>{user.balance_rub}</b> ₽ (пользователь уведомлён).",
        reply_markup=admin_main_keyboard(),
    )


@router.message(StateFilter(AdminStates.balance_sub_line), F.text)
async def on_balance_sub_line(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("⚠️ Нужны два значения: кому и сколько ₽.", reply_markup=admin_back_keyboard())
        return
    raw_user, amount_s = parts[0], parts[1].strip()
    try:
        amount = int(amount_s)
    except ValueError:
        await message.answer("⚠️ Сумма должна быть целым числом.", reply_markup=admin_back_keyboard())
        return
    user = await resolve_user_identifier(session, raw_user)
    if user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=admin_back_keyboard())
        return
    if user.balance_rub < amount:
        await message.answer("⚠️ На балансе меньше запрошенной суммы.", reply_markup=admin_back_keyboard())
        return
    await add_transaction(session, user, -amount, "admin_sub", "Списание модератором")
    await session.commit()
    await state.clear()
    try:
        await bot.send_message(
            user.telegram_id,
            f"💸 С баланса списано <b>{amount}</b> ₽ модератором. Баланс: <b>{user.balance_rub}</b> ₽",
        )
    except Exception:
        logger.exception("Не удалось уведомить пользователя о списании")
    await message.answer(
        f"✅ {display_db_user(user)} — баланс <b>{user.balance_rub}</b> ₽ (пользователь уведомлён).",
        reply_markup=admin_main_keyboard(),
    )


@router.callback_query(F.data == "adm:disputes")
async def cb_disputes(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    matches = await list_disputes(session)
    if not matches:
        await callback.message.edit_text("✨ Спорных матчей сейчас нет.", reply_markup=admin_back_keyboard())
        await callback.answer()
        return
    lines = ["⚖️ <b>Спорные матчи</b>", "Победитель или возврат ставок обоим:"]
    for m in matches:
        names = " vs ".join(display_db_user(p.user) for p in m.participants)
        lines.append(
            f"\n{GAME_TITLES[Game(m.game)]} · {MODE_TITLES[MatchMode(m.mode)]}\n"
            f"💰 {m.stake_rub} ₽ · {names}\n📝 <i>{html.escape(m.dispute_reason or '')}</i>"
        )
    await callback.message.edit_text("\n".join(lines), reply_markup=disputes_keyboard(matches))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:rv:"))
async def cb_resolve(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        _, _, mid_s, uid_s = callback.data.split(":")
        match_id, winner_pk = int(mid_s), int(uid_s)
    except ValueError:
        await callback.answer("Битая кнопка.", show_alert=True)
        return
    try:
        match = await admin_resolve_match(session, match_id, winner_pk)
    except MatchError as exc:
        await callback.answer(str(exc)[:200], show_alert=True)
        return
    winner = next((p.user for p in match.participants if p.user_id == winner_pk), None)
    for participant in match.participants:
        text = (
            "⚖️ Модератор закрыл спор в твою пользу."
            if winner and participant.user_id == winner.id
            else "⚖️ Спор решён в пользу соперника."
        )
        await bot.send_message(participant.user.telegram_id, f"Матч: {text}")
    wname = display_db_user(winner) if winner else "—"
    mod_chat = get_settings().moderation_chat_id_int
    if mod_chat is not None and callback.message.chat.id == mod_chat:
        await callback.message.edit_text(
            f"✅ Матч закрыт. Победитель: {html.escape(wname)}.",
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"✅ Матч закрыт. Победитель: {wname}.",
            reply_markup=admin_main_keyboard(),
        )
    await callback.answer("Готово.")


@router.callback_query(F.data.startswith("adm:rf:"))
async def cb_dispute_refund_all(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        match_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Битая кнопка.", show_alert=True)
        return
    try:
        match = await cancel_match(session, match_id, reason="Возврат ставок (модератор)")
    except MatchError as exc:
        await callback.answer(str(exc)[:200], show_alert=True)
        return
    for participant in match.participants:
        try:
            await bot.send_message(
                participant.user.telegram_id,
                "♻️ Модератор вернул ставки обоим участникам. Средства на балансе в боте.",
            )
        except Exception:
            logger.exception("Не удалось уведомить о возврате пользователя %s", participant.user_id)
    mod_chat = get_settings().moderation_chat_id_int
    if mod_chat is not None and callback.message.chat.id == mod_chat:
        await callback.message.edit_text("✅ Ставки возвращены участникам.", parse_mode="HTML")
    else:
        await callback.message.edit_text("✅ Ставки возвращены участникам.", reply_markup=admin_main_keyboard())
    await callback.answer("Готово.")


@router.callback_query(F.data == "adm:cancel")
async def cb_cancel_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminStates.cancel_match_id)
    await callback.message.edit_text("🚫 <b>Отменить матч</b>", reply_markup=admin_back_keyboard())
    await callback.answer()


@router.message(StateFilter(AdminStates.cancel_match_id), F.text)
async def on_cancel_match_id(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    try:
        match_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ Нужен ID матча одним числом.", reply_markup=admin_back_keyboard())
        return
    try:
        match = await cancel_match(session, match_id)
    except MatchError as exc:
        await message.answer(f"❌ {exc}", reply_markup=admin_back_keyboard())
        return
    await state.clear()
    await message.answer(
        f"♻️ Матч отменён, ставки возвращены.",
        reply_markup=admin_main_keyboard(),
    )


@router.callback_query(F.data == "adm:tickets")
async def cb_tickets(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    tickets_list = await list_open_tickets(session)
    if not tickets_list:
        await callback.message.edit_text("✨ Открытых тикетов нет.", reply_markup=admin_back_keyboard())
        await callback.answer()
        return
    await callback.message.edit_text(
        "💬 <b>Открытые тикеты</b>\n\nНажми тикет, чтобы закрыть его и отправить ответ пользователю.",
        reply_markup=tickets_keyboard(tickets_list),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:reply")
async def cb_reply_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    tickets_list = await list_open_tickets(session)
    if not tickets_list:
        await callback.message.edit_text("✨ Открытых тикетов нет.", reply_markup=admin_back_keyboard())
        await callback.answer()
        return
    await callback.message.edit_text(
        "📨 <b>Закрыть тикет с ответом</b>\n\nВыбери обращение:",
        reply_markup=tickets_keyboard(tickets_list),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:rpk:"))
async def cb_ticket_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    ticket_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.ticket_reply_text)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.edit_text(
        f"📝 Тикет <b>#{ticket_id}</b>\n\nНапиши ответ <b>одним сообщением</b> — тикет закроется и уйдёт в ЛС.",
        reply_markup=admin_back_keyboard(),
    )
    await callback.answer()


@router.message(StateFilter(AdminStates.ticket_reply_text), F.text)
async def on_ticket_reply_body(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    data = await state.get_data()
    ticket_id = int(data["ticket_id"])
    body = (message.text or "").strip()
    if not body:
        await message.answer("⚠️ Пустой текст.", reply_markup=admin_back_keyboard())
        return

    existing = await session.get(SupportTicket, ticket_id)
    thread_id = existing.forum_thread_id if existing else None

    ticket = await close_ticket(session, ticket_id, body)
    if ticket is None:
        await message.answer("❌ Тикет не найден или уже закрыт.", reply_markup=admin_back_keyboard())
        await state.clear()
        return

    user = await get_user_by_id(session, ticket.user_id)
    mod_chat = get_settings().moderation_chat_id_int
    if user:
        await bot.send_message(user.telegram_id, f"💬 Ответ поддержки по обращению #{ticket.id}:\n{body}")
    if thread_id and mod_chat:
        try:
            await bot.send_message(
                mod_chat,
                f"📨 <b>Ответ отправлен</b>, тикет закрыт.\n\n{body}",
                message_thread_id=thread_id,
            )
        except Exception:
            logger.exception("Не удалось продублировать ответ в форум")

    await state.clear()
    await message.answer(f"✅ Обращение #{ticket.id} закрыто.", reply_markup=admin_main_keyboard())


@router.callback_query(F.data == "adm:withdraw")
async def cb_withdrawals_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await _redraw_withdrawals_list(callback, session)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:wd:a:"))
async def cb_withdraw_approve(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        rid = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("⚠️ Некорректный ID заявки.", show_alert=True)
        return
    result = await approve_withdrawal_request(session, rid)
    if result is None:
        await callback.answer("Не найдена или уже обработана.", show_alert=True)
    elif result.status == WithdrawalStatus.APPROVED:
        await _notify_user_withdrawal(bot, session, result, approved=True)
        await callback.answer("✅ Одобрено")
    else:
        await _notify_user_withdrawal(bot, session, result, approved=False, auto_insufficient=True)
        await callback.answer("⚠️ Не хватило баланса — отклонено", show_alert=True)
    await _redraw_withdrawals_list(callback, session)


@router.callback_query(F.data.startswith("adm:wd:r:"))
async def cb_withdraw_reject(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        rid = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("⚠️ Некорректный ID заявки.", show_alert=True)
        return
    result = await reject_withdrawal_request(session, rid)
    if result is None:
        await callback.answer("Не найдена или уже обработана.", show_alert=True)
    else:
        await _notify_user_withdrawal(bot, session, result, approved=False)
        await callback.answer("❌ Отклонено")
    await _redraw_withdrawals_list(callback, session)
