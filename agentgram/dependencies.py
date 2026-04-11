from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentgram.context import AgentIdentity
from agentgram.models import User, Workspace
from agentgram.services.core import authenticate_agent_key


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


async def get_db_session(
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return await session.scalar(select(User).where(User.id == user_id))


async def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


async def get_workspace_or_404(
    workspace_id: str,
    session: AsyncSession,
    user: User,
) -> Workspace:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_user_id == user.id,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return workspace


async def require_agent_identity(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> AgentIdentity:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required.")

    token = authorization.split(" ", 1)[1].strip()
    identity = await authenticate_agent_key(session, token)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent key.")
    return identity
