from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.core.constants import GAME_TITLES, MODE_TITLES, Game, MatchMode

MENU_BUTTONS = (
    "👤 Профиль",
    "⚔️ Играть",
    "💰 Баланс",
    "⭐ Подписка",
    "📜 Правила",
    "💬 Поддержка",
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="⚔️ Играть")],
            [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="⭐ Подписка")],
            [KeyboardButton(text="📜 Правила"), KeyboardButton(text="💬 Поддержка")],
        ],
        resize_keyboard=True,
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🛡️ Clash Royale", callback_data=f"profile:edit:{Game.CLASH_ROYALE}"),
                InlineKeyboardButton(text="🤠 Brawl Stars", callback_data=f"profile:edit:{Game.BRAWL_STARS}"),
            ],
            [InlineKeyboardButton(text="🏆 История игр", callback_data="profile:history")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="flow:back")],
        ]
    )


def games_keyboard(prefix: str = "game") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🎮 {title}", callback_data=f"{prefix}:{game}")]
            for game, title in GAME_TITLES.items()
        ]
    )


def keyboard_with_back(kb: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    rows = list(kb.inline_keyboard) + [[InlineKeyboardButton(text="◀️ Назад", callback_data="flow:back")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def brawl_modes_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⚡ {title}", callback_data=f"mode:{mode}")]
            for mode, title in MODE_TITLES.items()
        ]
    )


def play_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать матч", callback_data="play:create")],
            [InlineKeyboardButton(text="🔍 Найти матч", callback_data="play:list")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="flow:back")],
        ]
    )


def result_keyboard(match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏁 Конец", callback_data=f"match:end:{match_id}")],
            [
                InlineKeyboardButton(text="🏆 Победа", callback_data=f"match:result:{match_id}:win"),
                InlineKeyboardButton(text="💥 Поражение", callback_data=f"match:result:{match_id}:loss"),
            ],
        ]
    )


def match_join_keyboard(match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤝 Присоединиться", callback_data=f"match:join:{match_id}")]
        ]
    )


def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оформить подписку", callback_data="subscription:buy")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="flow:back")],
        ]
    )


def flow_nav_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="flow:back")]]
    )


def balance_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Пополнение", callback_data="balance:topup")],
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="balance:withdraw")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="flow:back")],
        ]
    )
