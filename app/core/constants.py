from enum import StrEnum


class Game(StrEnum):
    CLASH_ROYALE = "clash_royale"
    BRAWL_STARS = "brawl_stars"


class MatchMode(StrEnum):
    DUEL = "1v1"
    TWO_VS_TWO = "2v2"


class MatchStatus(StrEnum):
    OPEN = "open"
    ACTIVE = "active"
    RESULT_PENDING = "result_pending"
    DISPUTED = "disputed"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ResultChoice(StrEnum):
    WIN = "win"
    LOSS = "loss"


class TicketStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class WithdrawalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


GAME_TITLES = {
    Game.CLASH_ROYALE: "Clash Royale",
    Game.BRAWL_STARS: "Brawl Stars",
}

MODE_TITLES = {
    MatchMode.DUEL: "1 на 1",
    MatchMode.TWO_VS_TWO: "2 на 2",
}

