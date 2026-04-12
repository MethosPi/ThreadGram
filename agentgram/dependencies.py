from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import unquote

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentgram.context import AgentIdentity
from agentgram.models import User, Workspace
from agentgram.services.core import authenticate_agent_key, authenticate_local_agent, ensure_local_user


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
    settings = request.app.state.settings
    if settings.local_mode and is_local_request(request):
        return await ensure_local_user(session, github_login=settings.local_user_login)

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
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> AgentIdentity:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        identity = await authenticate_agent_key(session, token)
        if identity is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent key.")
        return identity

    settings = request.app.state.settings
    if settings.local_mode and is_local_request(request):
        agent_name = read_local_identity_value(
            request,
            query_key=settings.local_agent_query_param,
            header_name=settings.local_agent_header_name,
        )
        workspace_slug = read_local_identity_value(
            request,
            query_key=settings.local_workspace_query_param,
            header_name=settings.local_workspace_header_name,
        ) or settings.local_workspace_slug
        if not agent_name:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    f"Local mode requires an agent identity via '?{settings.local_agent_query_param}=name' "
                    f"or the '{settings.local_agent_header_name}' header."
                ),
            )
        try:
            return await authenticate_local_agent(
                session,
                agent_name=agent_name,
                workspace_slug=workspace_slug,
                local_user_login=settings.local_user_login,
                default_workspace_slug=settings.local_workspace_slug,
                default_workspace_name=settings.local_workspace_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required.")


def is_local_request(request: Request) -> bool:
    host = request.headers.get("host", "").split(":", 1)[0].strip().lower()
    return host in {"localhost", "127.0.0.1", "::1", "[::1]"}


def read_local_identity_value(request: Request, *, query_key: str, header_name: str) -> str | None:
    query_value = request.query_params.get(query_key)
    if query_value:
        return unquote(query_value).strip()
    header_value = request.headers.get(header_name)
    if header_value:
        return header_value.strip()
    return None
