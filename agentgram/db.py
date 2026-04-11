from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from agentgram.models import Base


def create_engine(database_url: str) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite+aiosqlite"):
        connect_args["check_same_thread"] = False

    return create_async_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
