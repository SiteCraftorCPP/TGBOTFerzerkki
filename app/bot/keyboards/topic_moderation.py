from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.formatting import display_db_user
from app.db.models import Match


def topic_fsm_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="tmod:cancel_fsm")]]
    )


def topic_ticket_actions_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Закрыть тикет с ответом", callback_data=f"tmod:close:{ticket_id}")],
            [
                InlineKeyboardButton(text="⚖️ Спорные матчи", callback_data="tmod:disputes"),
                InlineKeyboardButton(text="🚫 Отменить матч", callback_data="tmod:cancel"),
            ],
            [
                InlineKeyboardButton(text="➕ Баланс", callback_data="tmod:+bal"),
                InlineKeyboardButton(text="➖ Баланс", callback_data="tmod:-bal"),
            ],
            [InlineKeyboardButton(text="📋 Все открытые тикеты", callback_data="tmod:tickets")],
        ]
    )


def disputes_keyboard_topic(matches: list[Match]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for m in matches:
        row: list[InlineKeyboardButton] = []
        for p in m.participants:
            name = display_db_user(p.user)
            btn = f"🏆 {name}"[:64]
            cb = f"adm:rv:{m.id}:{p.user.id}"
            row.append(InlineKeyboardButton(text=btn, callback_data=cb))
        row.append(InlineKeyboardButton(text="💰 Возврат", callback_data=f"adm:rf:{m.id}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✓ Свернуть", callback_data="tmod:collapse")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tickets_keyboard_topic(tickets_list: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ticket in tickets_list:
        who = display_db_user(ticket.user)
        preview = (ticket.message[:40] + "…") if len(ticket.message) > 40 else ticket.message
        label = f"#{ticket.id} {who}: {preview}"[:64]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"tmod:pick:{ticket.id}")])
    rows.append([InlineKeyboardButton(text="✓ Свернуть", callback_data="tmod:collapse")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
