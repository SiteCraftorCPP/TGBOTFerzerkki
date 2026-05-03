from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.models import Subscription, User


MIN_STAKE_RUB = 10
STAKE_STEP_RUB = 10


def validate_stake(amount_rub: int) -> None:
    if amount_rub < MIN_STAKE_RUB:
        raise ValueError(f"Минимальная ставка — {MIN_STAKE_RUB} ₽.")
    if amount_rub % STAKE_STEP_RUB != 0:
        raise ValueError(f"Ставка должна быть кратна {STAKE_STEP_RUB} ₽.")


def is_subscription_active(subscription: Subscription | None, now: datetime | None = None) -> bool:
    if not subscription or not subscription.active_until:
        return False
    current = now or datetime.now(UTC)
    active_until = subscription.active_until
    if active_until.tzinfo is None:
        active_until = active_until.replace(tzinfo=UTC)
    return active_until > current


def commission_percent(user: User) -> int:
    settings = get_settings()
    if is_subscription_active(user.subscription):
        return settings.subscriber_commission_percent
    return settings.default_commission_percent


def calculate_payout(total_bank_rub: int, winner: User) -> tuple[int, int]:
    percent = commission_percent(winner)
    commission = total_bank_rub * percent // 100
    return total_bank_rub - commission, commission

