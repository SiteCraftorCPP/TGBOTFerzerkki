import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.constants import Game, MatchMode, MatchStatus
from app.db.models import Base, GameProfile, Match, MatchParticipant, User
from app.db.repositories import list_user_matches
from app.services.matches import MatchError, create_match, join_match


@pytest.fixture
async def async_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_user_matches_returns_only_participant_matches(async_session_factory) -> None:
    async with async_session_factory() as session:
        a = User(telegram_id=1, balance_rub=0)
        b = User(telegram_id=2, balance_rub=0)
        session.add_all([a, b])
        await session.commit()
        await session.refresh(a)
        await session.refresh(b)

        m1 = Match(
            game=Game.CLASH_ROYALE,
            mode=MatchMode.DUEL,
            stake_rub=10,
            status=MatchStatus.FINISHED,
            winner_user_id=a.id,
        )
        m2 = Match(
            game=Game.CLASH_ROYALE,
            mode=MatchMode.DUEL,
            stake_rub=10,
            status=MatchStatus.FINISHED,
            winner_user_id=b.id,
        )
        session.add_all([m1, m2])
        await session.commit()
        await session.refresh(m1)
        await session.refresh(m2)

        session.add_all(
            [
                MatchParticipant(match_id=m1.id, user_id=a.id, is_creator=True),
                MatchParticipant(match_id=m2.id, user_id=b.id, is_creator=True),
            ]
        )
        await session.commit()

    async with async_session_factory() as session:
        rows = await list_user_matches(session, a.id, limit=10)
        assert len(rows) == 1
        assert rows[0].id == m1.id


@pytest.mark.asyncio
async def test_only_one_opponent_can_join_open_match(async_session_factory) -> None:
    async with async_session_factory() as session:
        creator = User(telegram_id=10, balance_rub=1000)
        joiner_a = User(telegram_id=11, balance_rub=1000)
        joiner_b = User(telegram_id=12, balance_rub=1000)
        session.add_all([creator, joiner_a, joiner_b])
        await session.commit()
        await session.refresh(creator)
        await session.refresh(joiner_a)
        await session.refresh(joiner_b)

        for u in (creator, joiner_a, joiner_b):
            session.add(
                GameProfile(
                    user_id=u.id,
                    game=Game.CLASH_ROYALE,
                    game_tag=f"TAG{u.telegram_id}",
                    nickname=f"nick{u.telegram_id}",
                    trophies=5000,
                )
            )
        await session.commit()

        match = await create_match(session, creator, Game.CLASH_ROYALE, MatchMode.DUEL, 100)
        await join_match(session, match.id, joiner_a)

        with pytest.raises(MatchError):
            await join_match(session, match.id, joiner_b)
