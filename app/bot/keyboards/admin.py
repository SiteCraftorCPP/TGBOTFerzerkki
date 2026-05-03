from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.formatting import display_db_user
from app.db.models import Match, WithdrawalRequest


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Начислить баланс", callback_data="adm:+bal"),
                InlineKeyboardButton(text="➖ Списать с баланса", callback_data="adm:-bal"),
            ],
            [
                InlineKeyboardButton(text="⚖️ Спорные матчи", callback_data="adm:disputes"),
                InlineKeyboardButton(text="💬 Открытые тикеты", callback_data="adm:tickets"),
            ],
            [
                InlineKeyboardButton(text="🚫 Отменить матч (возврат ставок)", callback_data="adm:cancel"),
                InlineKeyboardButton(text="📨 Закрыть тикет + ответ", callback_data="adm:reply"),
            ],
            [InlineKeyboardButton(text="💸 Заявки на вывод", callback_data="adm:withdraw")],
        ]
    )


def admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ В панель модератора", callback_data="adm:home")]]
    )


def disputes_keyboard(matches: list[Match]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for m in matches:
        row: list[InlineKeyboardButton] = []
        for p in m.participants:
            name = display_db_user(p.user)
            btn = f"🏆 {name}"[:64]
            cb = f"adm:rv:{m.id}:{p.user.id}"
            row.append(InlineKeyboardButton(text=btn, callback_data=cb))
        row.append(InlineKeyboardButton(text="💰 Возврат всем", callback_data=f"adm:rf:{m.id}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ В панель модератора", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tickets_keyboard(tickets_list: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ticket in tickets_list:
        who = display_db_user(ticket.user)
        preview = (ticket.message[:40] + "…") if len(ticket.message) > 40 else ticket.message
        label = f"#{ticket.id} {who}: {preview}"[:64]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm:rpk:{ticket.id}")])
    rows.append([InlineKeyboardButton(text="◀️ В панель модератора", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def withdrawals_keyboard(requests: list[WithdrawalRequest]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for r in requests:
        rows.append(
            [
                InlineKeyboardButton(text=f"✅ #{r.id}", callback_data=f"adm:wd:a:{r.id}"),
                InlineKeyboardButton(text=f"❌ #{r.id}", callback_data=f"adm:wd:r:{r.id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ В панель модератора", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
