from datetime import UTC, datetime, timedelta

from aiogram.types import User as TelegramUser
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import Game, MatchStatus, TicketStatus, WithdrawalStatus
from app.db.models import (
    GameProfile,
    Match,
    MatchParticipant,
    Subscription,
    SupportTicket,
    Transaction,
    User,
    WithdrawalRequest,
)


async def get_or_create_user(session: AsyncSession, tg_user: TelegramUser) -> User:
    result = await session.execute(
        select(User).where(User.telegram_id == tg_user.id).options(selectinload(User.subscription))
    )
    user = result.scalar_one_or_none()
    if user:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        await session.commit()
        return user

    user = User(telegram_id=tg_user.id, username=tg_user.username, first_name=tg_user.first_name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    name = username.strip().lstrip("@")
    if not name:
        return None
    result = await session.execute(
        select(User).where(func.lower(User.username) == func.lower(name)).options(selectinload(User.subscription))
    )
    return result.scalar_one_or_none()


async def resolve_user_identifier(session: AsyncSession, raw: str) -> User | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("@"):
        return await get_user_by_username(session, raw[1:])
    try:
        return await get_user_by_tg_id(session, int(raw))
    except ValueError:
        return await get_user_by_username(session, raw)


async def get_user_by_tg_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id).options(selectinload(User.subscription))
    )
    return result.scalar_one_or_none()


def user_needs_oferta_acceptance(user: User | None, *, current_version: str) -> bool:
    want = (current_version or "").strip()
    if user is None:
        return True
    got = (user.oferta_accepted_version or "").strip()
    return got != want


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id).options(selectinload(User.subscription)))
    return result.scalar_one_or_none()


async def get_profile(session: AsyncSession, user_id: int, game: Game | str) -> GameProfile | None:
    result = await session.execute(
        select(GameProfile).where(GameProfile.user_id == user_id, GameProfile.game == str(game))
    )
    return result.scalar_one_or_none()


async def list_profiles(session: AsyncSession, user_id: int) -> list[GameProfile]:
    result = await session.execute(select(GameProfile).where(GameProfile.user_id == user_id))
    return list(result.scalars())


async def upsert_profile(
    session: AsyncSession,
    user_id: int,
    game: Game | str,
    game_tag: str,
    nickname: str,
    trophies: int,
) -> GameProfile:
    profile = await get_profile(session, user_id, game)
    if profile is None:
        profile = GameProfile(user_id=user_id, game=str(game), game_tag=game_tag, nickname=nickname, trophies=trophies)
        session.add(profile)
    else:
        profile.game_tag = game_tag
        profile.nickname = nickname
        profile.trophies = trophies
    await session.commit()
    await session.refresh(profile)
    return profile


async def add_transaction(
    session: AsyncSession,
    user: User,
    amount_rub: int,
    kind: str,
    comment: str = "",
) -> Transaction:
    user.balance_rub += amount_rub
    transaction = Transaction(user_id=user.id, amount_rub=amount_rub, kind=kind, comment=comment)
    session.add(transaction)
    await session.flush()
    return transaction


async def activate_subscription(session: AsyncSession, user: User, days: int = 30) -> Subscription:
    active_until = datetime.now(UTC) + timedelta(days=days)
    if user.subscription is None:
        subscription = Subscription(user_id=user.id, active_until=active_until)
        session.add(subscription)
        user.subscription = subscription
    else:
        user.subscription.active_until = max(user.subscription.active_until or active_until, datetime.now(UTC)) + timedelta(
            days=days
        )
    await session.commit()
    await session.refresh(user)
    return user.subscription


async def create_support_ticket(session: AsyncSession, user_id: int, message: str) -> SupportTicket:
    ticket = SupportTicket(user_id=user_id, message=message, status=TicketStatus.OPEN)
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def update_ticket_forum_thread(session: AsyncSession, ticket_id: int, thread_id: int | None) -> None:
    ticket = await session.get(SupportTicket, ticket_id)
    if ticket is None:
        return
    ticket.forum_thread_id = thread_id
    await session.commit()


async def get_open_ticket_by_forum_thread(session: AsyncSession, thread_id: int) -> SupportTicket | None:
    result = await session.execute(
        select(SupportTicket)
        .where(SupportTicket.forum_thread_id == thread_id, SupportTicket.status == TicketStatus.OPEN)
        .options(selectinload(SupportTicket.user))
        .order_by(SupportTicket.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def invalidate_user_support_forum_if_mod_chat_mismatch(
    session: AsyncSession, user: User, current_mod_chat_id: int
) -> None:
    """Если сохранённая ветка была для другого чата модерации — сбросить, чтобы создать тему заново."""
    stored = user.support_moderation_chat_id
    if stored is not None and stored != current_mod_chat_id:
        user.support_forum_thread_id = None
        user.support_moderation_chat_id = None
        await session.commit()


async def set_user_support_forum_thread(
    session: AsyncSession, user_id: int, thread_id: int | None, *, moderation_chat_id: int | None = None
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        return
    user.support_forum_thread_id = thread_id
    if thread_id is None:
        user.support_moderation_chat_id = None
    else:
        if moderation_chat_id is None:
            raise ValueError("moderation_chat_id required when thread_id is set")
        user.support_moderation_chat_id = moderation_chat_id
    await session.commit()


async def list_open_tickets(session: AsyncSession) -> list[SupportTicket]:
    result = await session.execute(
        select(SupportTicket)
        .where(SupportTicket.status == TicketStatus.OPEN)
        .options(selectinload(SupportTicket.user))
        .order_by(SupportTicket.created_at.asc())
    )
    return list(result.scalars())


async def close_ticket(session: AsyncSession, ticket_id: int, response: str) -> SupportTicket | None:
    ticket = await session.get(SupportTicket, ticket_id)
    if ticket is None:
        return None
    ticket.status = TicketStatus.CLOSED
    ticket.admin_response = response
    ticket.closed_at = datetime.now(UTC)
    await session.commit()
    return ticket


async def list_user_matches(session: AsyncSession, user_id: int, limit: int = 10) -> list[Match]:
    user_in_match = exists().where(MatchParticipant.match_id == Match.id, MatchParticipant.user_id == user_id)
    result = await session.execute(
        select(Match)
        .where(user_in_match, Match.status.in_([MatchStatus.FINISHED, MatchStatus.DISPUTED]))
        .options(selectinload(Match.participants))
        .order_by(Match.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().unique())


class WithdrawalError(ValueError):
    """Некорректная заявка на вывод."""


async def create_withdrawal_request(
    session: AsyncSession, user_id: int, amount_rub: int, payout_details: str
) -> WithdrawalRequest:
    details = (payout_details or "").strip()
    if len(details) < 8:
        raise WithdrawalError("Реквизиты слишком короткие — укажи карту / СБП / кошелёк целиком (не меньше 8 символов).")
    if amount_rub < 10:
        raise WithdrawalError("Минимальная сумма вывода — 10 ₽.")
    user = await session.get(User, user_id)
    if user is None:
        raise WithdrawalError("Пользователь не найден.")
    if user.balance_rub < amount_rub:
        raise WithdrawalError("На балансе недостаточно средств.")
    result = await session.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.user_id == user_id, WithdrawalRequest.status == WithdrawalStatus.PENDING)
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise WithdrawalError(
            f"Уже есть открытая заявка на <b>{existing.amount_rub}</b> ₽ "
            f"(в БД статус «ожидает»). Панель модератора → 💸 Заявки на вывод. "
            f"Для теста удали запись из таблицы <code>withdrawal_requests</code> или дождись решения."
        )
    req = WithdrawalRequest(
        user_id=user_id, amount_rub=amount_rub, payout_details=details, status=WithdrawalStatus.PENDING
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


async def list_pending_withdrawals(session: AsyncSession) -> list[WithdrawalRequest]:
    result = await session.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.status == WithdrawalStatus.PENDING)
        .options(selectinload(WithdrawalRequest.user))
        .order_by(WithdrawalRequest.created_at.asc())
    )
    return list(result.scalars().unique())


async def get_withdrawal_request(session: AsyncSession, request_id: int) -> WithdrawalRequest | None:
    result = await session.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.id == request_id)
        .options(selectinload(WithdrawalRequest.user))
    )
    return result.scalar_one_or_none()


async def approve_withdrawal_request(session: AsyncSession, request_id: int) -> WithdrawalRequest | None:
    req = await session.get(WithdrawalRequest, request_id)
    if req is None or req.status != WithdrawalStatus.PENDING:
        return None
    user = await session.get(User, req.user_id)
    if user is None:
        return None
    if user.balance_rub < req.amount_rub:
        req.status = WithdrawalStatus.REJECTED
        req.processed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(req)
        return req
    await add_transaction(session, user, -req.amount_rub, "withdrawal_payout", f"Вывод #{req.id}")
    req.status = WithdrawalStatus.APPROVED
    req.processed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(req)
    return req


async def reject_withdrawal_request(session: AsyncSession, request_id: int) -> WithdrawalRequest | None:
    req = await session.get(WithdrawalRequest, request_id)
    if req is None or req.status != WithdrawalStatus.PENDING:
        return None
    req.status = WithdrawalStatus.REJECTED
    req.processed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(req)
    return req

