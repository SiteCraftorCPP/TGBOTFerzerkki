from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Subscription, User
from app.services.finance import calculate_payout, is_subscription_active, validate_stake


def test_stake_must_be_at_least_10_and_multiple_of_10() -> None:
    validate_stake(10)

    with pytest.raises(ValueError, match="кратна"):
        validate_stake(15)

    with pytest.raises(ValueError, match="Минимальная"):
        validate_stake(0)

    with pytest.raises(ValueError, match="Минимальная"):
        validate_stake(5)


def test_default_commission_is_15_percent() -> None:
    user = User(balance_rub=0, telegram_id=1)

    payout, commission = calculate_payout(200, user)

    assert payout == 170
    assert commission == 30


def test_active_subscription_is_detected() -> None:
    subscription = Subscription(active_until=datetime.now(UTC) + timedelta(days=1))

    assert is_subscription_active(subscription)


def test_subscriber_commission_is_lower_when_percent_overridden(monkeypatch) -> None:
    import app.services.finance as finance

    monkeypatch.setattr(finance, "commission_percent", lambda user: 5)

    payout, commission = finance.calculate_payout(200, User(balance_rub=0, telegram_id=1))

    assert commission == 10
    assert payout == 190

