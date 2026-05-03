from aiogram.fsm.state import State, StatesGroup


class ProfileStates(StatesGroup):
    waiting_tag = State()
    waiting_nickname = State()
    waiting_trophies = State()


class MatchStates(StatesGroup):
    play_menu = State()
    pick_game = State()
    pick_mode = State()
    waiting_stake = State()


class SupportStates(StatesGroup):
    waiting_message = State()


class BalanceStates(StatesGroup):
    waiting_withdraw_details = State()
    waiting_withdraw_amount = State()


class AdminStates(StatesGroup):
    balance_add_line = State()
    balance_sub_line = State()
    cancel_match_id = State()
    ticket_reply_text = State()


class TopicModStates(StatesGroup):
    """Ввод модератора в подтеме чата MODERATION_CHAT_ID."""

    waiting_close_reply = State()
    waiting_cancel_match = State()
    balance_add_line = State()
    balance_sub_line = State()

