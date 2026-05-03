import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import Game, MatchMode, MatchStatus, ResultChoice
from app.db.models import Match, MatchParticipant, User
from app.db.repositories import add_transaction, get_profile
from app.services.finance import calculate_payout, validate_stake

OPEN_MATCH_TTL = timedelta(minutes=3)
RESULT_TTL = timedelta(minutes=10)

_match_locks: dict[int, asyncio.Lock] = {}


def _lock_for_match(match_id: int) -> asyncio.Lock:
    lock = _match_locks.get(match_id)
    if lock is None:
        lock = asyncio.Lock()
        _match_locks[match_id] = lock
    return lock


class MatchError(ValueError):
    pass


async def create_match(
    session: AsyncSession,
    creator: User,
    game: Game,
    mode: MatchMode,
    stake_rub: int,
) -> Match:
    validate_stake(stake_rub)
    profile = await get_profile(session, creator.id, game)
    if profile is None:
        raise MatchError("Сначала заполни профиль для этой игры.")
    if creator.balance_rub < stake_rub:
        raise MatchError("Недостаточно средств на балансе.")

    await add_transaction(session, creator, -stake_rub, "stake_hold", "Блокировка ставки создателя")
    match = Match(
        game=game,
        mode=mode,
        stake_rub=stake_rub,
        status=MatchStatus.OPEN,
        expires_at=datetime.now(UTC) + OPEN_MATCH_TTL,
    )
    session.add(match)
    await session.flush()
    session.add(MatchParticipant(match_id=match.id, user_id=creator.id, is_creator=True))
    await session.commit()
    await session.refresh(match)
    return match


async def list_open_matches(session: AsyncSession, user_id: int | None = None) -> list[Match]:
    await sweep_match_deadlines(session)
    statement = (
        select(Match)
        .where(Match.status == MatchStatus.OPEN)
        .options(selectinload(Match.participants).selectinload(MatchParticipant.user))
        .order_by(Match.created_at.asc())
    )
    result = await session.execute(statement)
    matches = list(result.scalars().unique())
    if user_id is None:
        return matches
    viewer = await session.get(User, user_id)
    balance = viewer.balance_rub if viewer else 0
    eligible: list[Match] = []
    for match in matches:
        if any(participant.user_id == user_id for participant in match.participants):
            continue
        if match.stake_rub > balance:
            continue
        if await get_profile(session, user_id, match.game) is None:
            continue
        eligible.append(match)
    return eligible


async def get_match(session: AsyncSession, match_id: int) -> Match | None:
    result = await session.execute(
        select(Match)
        .where(Match.id == match_id)
        .options(
            selectinload(Match.participants).selectinload(MatchParticipant.user).selectinload(User.subscription),
        )
    )
    return result.scalar_one_or_none()


async def join_match(session: AsyncSession, match_id: int, user: User) -> Match:
    async with _lock_for_match(match_id):
        match = await get_match(session, match_id)
        if match is None or match.status != MatchStatus.OPEN:
            raise MatchError("Матч уже недоступен.")
        if len(match.participants) != 1:
            raise MatchError("Матч уже занят другим игроком.")
        if any(participant.user_id == user.id for participant in match.participants):
            raise MatchError("Нельзя присоединиться к своему матчу.")
        profile = await get_profile(session, user.id, match.game)
        if profile is None:
            raise MatchError("Сначала заполни профиль для этой игры.")
        if user.balance_rub < match.stake_rub:
            raise MatchError("Недостаточно средств на балансе.")

        await add_transaction(session, user, -match.stake_rub, "stake_hold", f"Блокировка ставки в матче #{match.id}")
        session.add(MatchParticipant(match_id=match.id, user_id=user.id, is_creator=False))
        match.status = MatchStatus.ACTIVE
        match.result_deadline_at = datetime.now(UTC) + RESULT_TTL
        await session.commit()
        refreshed = await get_match(session, match.id)
        if refreshed is None:
            raise MatchError("Матч не найден после присоединения.")
        return refreshed


async def mark_end(session: AsyncSession, match_id: int, user: User) -> Match:
    match = await get_match(session, match_id)
    participant = _find_participant(match, user.id)
    if match is None or participant is None or match.status not in {MatchStatus.ACTIVE, MatchStatus.RESULT_PENDING}:
        raise MatchError("Этот матч нельзя закрыть.")
    participant.ended = True
    if all(item.ended for item in match.participants):
        match.status = MatchStatus.RESULT_PENDING
    await session.commit()
    return match


async def submit_result(session: AsyncSession, match_id: int, user: User, result_choice: ResultChoice) -> Match:
    match = await get_match(session, match_id)
    participant = _find_participant(match, user.id)
    if match is None or participant is None or match.status not in {MatchStatus.ACTIVE, MatchStatus.RESULT_PENDING}:
        raise MatchError("Результат для этого матча уже не принимается.")
    participant.result = result_choice
    participant.ended = True

    resolution = resolve_result_reports([item.result for item in match.participants])
    if resolution == "winner":
        winner = next(item.user for item in match.participants if item.result == ResultChoice.WIN)
        await finish_with_winner(session, match, winner, "Результаты игроков совпали")
    elif resolution == "dispute":
        await move_to_dispute(session, match, "Игроки указали противоречивые результаты")
    else:
        await session.commit()
    refreshed = await get_match(session, match.id)
    if refreshed is None:
        raise MatchError("Матч не найден.")
    return refreshed


async def expire_open_match(session: AsyncSession, match_id: int) -> Match | None:
    async with _lock_for_match(match_id):
        match = await get_match(session, match_id)
        if match is None or match.status != MatchStatus.OPEN:
            return match
        creator = next((item.user for item in match.participants if item.is_creator), None)
        if creator is not None:
            await add_transaction(session, creator, match.stake_rub, "stake_refund", f"Возврат ставки матча #{match.id}")
        match.status = MatchStatus.EXPIRED
        match.finished_at = datetime.now(UTC)
        await session.commit()
        return match


async def expire_stale_open_matches(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    result = await session.execute(select(Match).where(Match.status == MatchStatus.OPEN, Match.expires_at <= now))
    for match in result.scalars():
        await expire_open_match(session, match.id)


async def sweep_match_deadlines(
    session: AsyncSession,
    *,
    on_match_auto_resolved: Callable[[int], Awaitable[None]] | None = None,
    on_match_refunded: Callable[[int], Awaitable[None]] | None = None,
) -> None:
    """Просроченные OPEN по expires_at и ACTIVE/RESULT_PENDING по result_deadline_at (в т.ч. после рестарта бота)."""
    await expire_stale_open_matches(session)
    now = datetime.now(UTC)
    result = await session.execute(
        select(Match.id).where(
            Match.status.in_((MatchStatus.ACTIVE, MatchStatus.RESULT_PENDING)),
            Match.result_deadline_at.is_not(None),
            Match.result_deadline_at <= now,
        )
    )
    for match_id in result.scalars():
        m0 = await get_match(session, match_id)
        st0 = m0.status if m0 else None
        m = await auto_resolve_timeout(session, match_id)
        if m is None or st0 not in (MatchStatus.ACTIVE, MatchStatus.RESULT_PENDING):
            continue
        if m.status in (MatchStatus.FINISHED, MatchStatus.DISPUTED) and on_match_auto_resolved:
            await on_match_auto_resolved(m.id)
        elif m.status == MatchStatus.CANCELLED and on_match_refunded:
            await on_match_refunded(m.id)


async def auto_resolve_timeout(session: AsyncSession, match_id: int) -> Match | None:
    match = await get_match(session, match_id)
    if match is None or match.status not in {MatchStatus.ACTIVE, MatchStatus.RESULT_PENDING}:
        return match
    if not match.result_deadline_at or _as_utc(match.result_deadline_at) > datetime.now(UTC):
        return match

    ready = [item for item in match.participants if item.ended or item.result is not None]
    not_ready = [item for item in match.participants if item not in ready]
    if len(ready) == 1 and len(not_ready) == 1:
        await finish_with_winner(session, match, ready[0].user, "Автопоражение соперника по таймауту")
        return await get_match(session, match.id)

    reports = [item.result for item in match.participants]
    resolution = resolve_result_reports(reports)

    if resolution == "winner":
        winner = next(item.user for item in match.participants if item.result == ResultChoice.WIN)
        await finish_with_winner(session, match, winner, "Совпадение результатов по дедлайну")
        return await get_match(session, match.id)

    if resolution == "dispute":
        await move_to_dispute(session, match, "Игроки указали противоречивые результаты")
        return await get_match(session, match.id)

    n_res = sum(1 for r in reports if r is not None)
    if n_res == 0:
        await cancel_match(session, match.id, reason="Таймаут: нет результатов от игроков")
    elif n_res == 1:
        p_done = next(p for p in match.participants if p.result is not None)
        if p_done.result == ResultChoice.WIN:
            await finish_with_winner(session, match, p_done.user, "Соперник не отправил результат в срок")
        else:
            other = next(p for p in match.participants if p.user_id != p_done.user_id)
            await finish_with_winner(session, match, other.user, "По заявленным результатам")
    else:
        await cancel_match(session, match.id, reason="Таймаут: не удалось зафиксировать исход")

    return await get_match(session, match.id)


async def finish_with_winner(session: AsyncSession, match: Match, winner: User, reason: str) -> None:
    if match.status == MatchStatus.FINISHED:
        return
    total_bank = match.stake_rub * len(match.participants)
    payout, commission = calculate_payout(total_bank, winner)
    await add_transaction(session, winner, payout, "match_win", f"{reason}. Комиссия: {commission} руб.")
    match.winner_user_id = winner.id
    match.status = MatchStatus.FINISHED
    match.finished_at = datetime.now(UTC)
    await session.commit()


async def move_to_dispute(session: AsyncSession, match: Match, reason: str) -> None:
    match.status = MatchStatus.DISPUTED
    match.dispute_reason = reason
    await session.commit()


async def admin_resolve_match(session: AsyncSession, match_id: int, winner_user_id: int) -> Match:
    match = await get_match(session, match_id)
    if match is None or match.status not in {MatchStatus.DISPUTED, MatchStatus.ACTIVE, MatchStatus.RESULT_PENDING}:
        raise MatchError("Матч нельзя закрыть в пользу игрока.")
    winner = next((item.user for item in match.participants if item.user_id == winner_user_id), None)
    if winner is None:
        raise MatchError("Победитель не является участником матча.")
    await finish_with_winner(session, match, winner, "Решение модератора")
    refreshed = await get_match(session, match.id)
    if refreshed is None:
        raise MatchError("Матч не найден.")
    return refreshed


async def cancel_match(session: AsyncSession, match_id: int, reason: str = "Отмена модератором") -> Match:
    match = await get_match(session, match_id)
    if match is None or match.status in {MatchStatus.FINISHED, MatchStatus.CANCELLED, MatchStatus.EXPIRED}:
        raise MatchError("Матч нельзя отменить.")
    for participant in match.participants:
        await add_transaction(session, participant.user, match.stake_rub, "stake_refund", f"{reason}: матч #{match.id}")
    match.status = MatchStatus.CANCELLED
    match.finished_at = datetime.now(UTC)
    await session.commit()
    return match


async def list_disputes(session: AsyncSession) -> list[Match]:
    result = await session.execute(
        select(Match)
        .where(Match.status == MatchStatus.DISPUTED)
        .options(selectinload(Match.participants).selectinload(MatchParticipant.user))
        .order_by(Match.created_at.asc())
    )
    return list(result.scalars().unique())


def _find_participant(match: Match | None, user_id: int) -> MatchParticipant | None:
    if match is None:
        return None
    return next((participant for participant in match.participants if participant.user_id == user_id), None)


def resolve_result_reports(reports: list[str | None]) -> str:
    ready_reports = [ResultChoice(report) for report in reports if report is not None]
    if len(ready_reports) < 2:
        return "waiting"
    if ready_reports.count(ResultChoice.WIN) == 1 and ready_reports.count(ResultChoice.LOSS) == 1:
        return "winner"
    return "dispute"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

