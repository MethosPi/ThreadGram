from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from threadgram.dependencies import get_db_session, is_local_request, require_agent_identity, require_user
from threadgram.models import User
from threadgram.schemas import (
    AgentKeyCreate,
    AgentKeyCreatedOut,
    AgentKeyOut,
    AgentsResponse,
    InboxResponse,
    MarkThreadReadResult,
    SendMessageRequest,
    SendMessageResult,
    SessionOut,
    TestingLoginRequest,
    ThreadDetail,
    ThreadSummary,
    UserOut,
    WhoAmIOut,
    WorkspaceCreate,
    WorkspaceDetail,
    WorkspaceOut,
)
from threadgram.services.core import (
    build_human_identity,
    build_workspace_detail,
    create_agent_key,
    create_workspace,
    ensure_local_user,
    fetch_inbox,
    get_or_create_user_from_github,
    get_thread,
    get_workspace_for_user,
    get_workspace_thread_for_owner,
    list_agents,
    list_workspace_keys,
    list_workspace_threads_for_owner,
    list_workspaces_for_user,
    mark_thread_read,
    revoke_agent_key,
    send_message,
)


def build_api_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/session", response_model=SessionOut)
    async def session_status(request: Request, user: User | None = Depends(require_user_optional)):
        public_api_base_url = request.app.state.settings.public_api_base_url
        if user is None:
            return SessionOut(
                authenticated=False,
                user=None,
                public_api_base_url=public_api_base_url,
                local_mode=request.app.state.settings.local_mode,
                default_local_workspace_slug=request.app.state.settings.local_workspace_slug,
                default_local_workspace_name=request.app.state.settings.local_workspace_name,
            )
        return SessionOut(
            authenticated=True,
            user=UserOut.model_validate(user),
            public_api_base_url=public_api_base_url,
            local_mode=request.app.state.settings.local_mode,
            default_local_workspace_slug=request.app.state.settings.local_workspace_slug,
            default_local_workspace_name=request.app.state.settings.local_workspace_name,
        )

    @router.get("/auth/github/login")
    async def github_login(request: Request, return_to: str | None = None):
        if request.app.state.settings.local_mode:
            target = return_to or request.app.state.settings.frontend_origin
            return RedirectResponse(target, status_code=status.HTTP_302_FOUND)

        oauth = request.app.state.oauth
        if oauth is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub OAuth is not configured.",
            )

        if return_to:
            request.session["post_login_redirect"] = return_to

        redirect_uri = str(request.url_for("github_oauth_callback"))
        return await oauth.github.authorize_redirect(request, redirect_uri)

    @router.get("/auth/github/callback", name="github_oauth_callback")
    async def github_callback(request: Request, session: AsyncSession = Depends(get_db_session)):
        if request.app.state.settings.local_mode:
            return RedirectResponse(request.app.state.settings.frontend_origin, status_code=status.HTTP_302_FOUND)

        oauth = request.app.state.oauth
        if oauth is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub OAuth is not configured.",
            )

        token = await oauth.github.authorize_access_token(request)
        response = await oauth.github.get("user", token=token)
        github_user = response.json()
        user = await get_or_create_user_from_github(
            session,
            github_user_id=str(github_user["id"]),
            github_login=github_user["login"],
            avatar_url=github_user.get("avatar_url"),
        )
        request.session["user_id"] = user.id

        redirect_target = request.session.pop("post_login_redirect", None) or request.app.state.settings.frontend_origin
        return RedirectResponse(redirect_target, status_code=status.HTTP_302_FOUND)

    @router.post("/auth/logout")
    async def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"ok": True}

    @router.get("/workspaces", response_model=list[WorkspaceOut])
    async def list_workspaces(
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspaces = await list_workspaces_for_user(session, user.id)
        return [WorkspaceOut.model_validate(workspace) for workspace in workspaces]

    @router.post("/workspaces", response_model=WorkspaceDetail, status_code=status.HTTP_201_CREATED)
    async def create_workspace_endpoint(
        payload: WorkspaceCreate,
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await create_workspace(session, owner_user_id=user.id, name=payload.name)
        return await build_workspace_detail(session, workspace)

    @router.get("/workspaces/{workspace_id}", response_model=WorkspaceDetail)
    async def get_workspace_endpoint(
        workspace_id: str,
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await get_workspace_for_user(session, workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        return await build_workspace_detail(session, workspace)

    @router.get("/workspaces/{workspace_id}/keys", response_model=list[AgentKeyOut])
    async def list_keys_endpoint(
        workspace_id: str,
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await get_workspace_for_user(session, workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        keys = await list_workspace_keys(session, workspace.id)
        return [AgentKeyOut.model_validate(key) for key in keys]

    @router.post("/workspaces/{workspace_id}/keys", response_model=AgentKeyCreatedOut, status_code=status.HTTP_201_CREATED)
    async def create_key_endpoint(
        workspace_id: str,
        payload: AgentKeyCreate,
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await get_workspace_for_user(session, workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        try:
            key, secret = await create_agent_key(
                session,
                workspace_id=workspace.id,
                agent_name=payload.agent_name,
                description=payload.description,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return AgentKeyCreatedOut(key=AgentKeyOut.model_validate(key), secret=secret)

    @router.post("/workspaces/{workspace_id}/keys/{key_id}/revoke", response_model=AgentKeyOut)
    async def revoke_key_endpoint(
        workspace_id: str,
        key_id: str,
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await get_workspace_for_user(session, workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        key = await revoke_agent_key(session, workspace_id=workspace.id, key_id=key_id)
        if key is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found.")
        return AgentKeyOut.model_validate(key)

    @router.get("/workspaces/{workspace_id}/threads", response_model=list[ThreadSummary])
    async def list_workspace_threads_endpoint(
        workspace_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await get_workspace_for_user(session, workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        return await list_workspace_threads_for_owner(session, workspace_id=workspace.id, limit=limit)

    @router.get("/workspaces/{workspace_id}/threads/{thread_id}", response_model=ThreadDetail)
    async def get_workspace_thread_endpoint(
        workspace_id: str,
        thread_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await get_workspace_for_user(session, workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        thread = await get_workspace_thread_for_owner(session, workspace_id=workspace.id, thread_id=thread_id, limit=limit)
        if thread is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")
        return thread

    @router.post("/workspaces/{workspace_id}/messages", response_model=SendMessageResult, status_code=status.HTTP_201_CREATED)
    async def owner_send_message(
        workspace_id: str,
        payload: SendMessageRequest,
        request: Request,
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await get_workspace_for_user(session, workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        try:
            return await send_message(
                session,
                identity=build_human_identity(workspace_id=workspace.id),
                to_agent=payload.to_agent,
                body=payload.body,
                thread_id=payload.thread_id,
                subject=payload.subject,
                allow_unknown_recipients=request.app.state.settings.local_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @router.post("/workspaces/{workspace_id}/threads/{thread_id}/read", response_model=MarkThreadReadResult)
    async def owner_mark_thread_read(
        workspace_id: str,
        thread_id: str,
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db_session),
    ):
        workspace = await get_workspace_for_user(session, workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        try:
            return await mark_thread_read(
                session,
                identity=build_human_identity(workspace_id=workspace.id),
                thread_id=thread_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.get("/agent/whoami", response_model=WhoAmIOut)
    async def agent_whoami(identity=Depends(require_agent_identity)):
        return WhoAmIOut(
            workspace_id=identity.workspace_id,
            key_id=identity.key_id,
            key_prefix=identity.key_prefix,
            agent_name=identity.agent_name,
        )

    @router.get("/agent/agents", response_model=AgentsResponse)
    async def agent_list_agents(
        identity=Depends(require_agent_identity),
        session: AsyncSession = Depends(get_db_session),
    ):
        agents = await list_agents(session, identity.workspace_id)
        return AgentsResponse(agents=agents)

    @router.get("/agent/inbox", response_model=InboxResponse)
    async def agent_fetch_inbox(
        unread_only: bool = Query(default=True),
        limit: int = Query(default=20, ge=1, le=100),
        identity=Depends(require_agent_identity),
        session: AsyncSession = Depends(get_db_session),
    ):
        return await fetch_inbox(session, identity=identity, unread_only=unread_only, limit=limit)

    @router.get("/agent/threads/{thread_id}", response_model=ThreadDetail)
    async def agent_get_thread(
        thread_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        identity=Depends(require_agent_identity),
        session: AsyncSession = Depends(get_db_session),
    ):
        try:
            return await get_thread(session, identity=identity, thread_id=thread_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.post("/agent/messages", response_model=SendMessageResult, status_code=status.HTTP_201_CREATED)
    async def agent_send_message(
        payload: SendMessageRequest,
        request: Request,
        identity=Depends(require_agent_identity),
        session: AsyncSession = Depends(get_db_session),
    ):
        try:
            return await send_message(
                session,
                identity=identity,
                to_agent=payload.to_agent,
                body=payload.body,
                thread_id=payload.thread_id,
                subject=payload.subject,
                allow_unknown_recipients=request.app.state.settings.local_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @router.post("/agent/threads/{thread_id}/read", response_model=MarkThreadReadResult)
    async def agent_mark_thread_read(
        thread_id: str,
        identity=Depends(require_agent_identity),
        session: AsyncSession = Depends(get_db_session),
    ):
        try:
            return await mark_thread_read(session, identity=identity, thread_id=thread_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.post("/testing/login", response_model=UserOut)
    async def testing_login(
        payload: TestingLoginRequest,
        request: Request,
        session: AsyncSession = Depends(get_db_session),
    ):
        if not request.app.state.settings.testing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

        github_user_id = payload.github_user_id or payload.github_login
        user = await get_or_create_user_from_github(
            session,
            github_user_id=github_user_id,
            github_login=payload.github_login,
            avatar_url=None,
        )
        request.session["user_id"] = user.id
        return UserOut.model_validate(user)

    return router


async def require_user_optional(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> User | None:
    if request.app.state.settings.local_mode and is_local_request(request):
        return await ensure_local_user(session, github_login=request.app.state.settings.local_user_login)

    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return await session.get(User, user_id)
