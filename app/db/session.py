from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def _ensure_support_ticket_forum_column(connection) -> None:
    rows = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='support_tickets'").fetchall()
    if not rows:
        return
    info = connection.exec_driver_sql("PRAGMA table_info(support_tickets)").fetchall()
    columns = {row[1] for row in info}
    if "forum_thread_id" not in columns:
        connection.execute(text("ALTER TABLE support_tickets ADD COLUMN forum_thread_id INTEGER"))


def _ensure_withdrawal_payout_details_column(connection) -> None:
    rows = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='withdrawal_requests'"
    ).fetchall()
    if not rows:
        return
    info = connection.exec_driver_sql("PRAGMA table_info(withdrawal_requests)").fetchall()
    columns = {row[1] for row in info}
    if "payout_details" not in columns:
        connection.execute(text("ALTER TABLE withdrawal_requests ADD COLUMN payout_details TEXT DEFAULT ''"))


def _ensure_user_support_thread_column(connection) -> None:
    rows = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchall()
    if not rows:
        return
    info = connection.exec_driver_sql("PRAGMA table_info(users)").fetchall()
    columns = {row[1] for row in info}
    if "support_forum_thread_id" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN support_forum_thread_id INTEGER"))
    if "support_moderation_chat_id" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN support_moderation_chat_id INTEGER"))
    if "oferta_accepted_version" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN oferta_accepted_version VARCHAR(32)"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_support_ticket_forum_column)
        await conn.run_sync(_ensure_user_support_thread_column)
        await conn.run_sync(_ensure_withdrawal_payout_details_column)


    if settings.reset_support_tickets_on_startup and engine.dialect.name == "sqlite":
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM support_tickets"))
            await conn.execute(text("DELETE FROM sqlite_sequence WHERE name='support_tickets'"))


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

