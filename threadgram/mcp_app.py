from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from threadgram.config import Settings
from threadgram.context import AgentIdentity, get_current_agent, reset_current_agent, set_current_agent
from threadgram.schemas import AgentsResponse, InboxResponse, MarkThreadReadResult, SendMessageResult, ThreadDetail, WhoAmIOut
from threadgram.services.core import (
    authenticate_agent_key,
    authenticate_local_agent,
    fetch_inbox as fetch_inbox_service,
    get_thread as get_thread_service,
    list_agents as list_agents_service,
    mark_thread_read as mark_thread_read_service,
    send_message as send_message_service,
)


def build_transport_security(settings: Settings) -> TransportSecuritySettings:
    api_url = urlparse(settings.public_api_base_url)
    frontend_url = urlparse(settings.frontend_origin)

    allowed_hosts = {
        "localhost:*",
        "127.0.0.1:*",
        "[::1]:*",
        "testserver",
    }
    if api_url.netloc:
        allowed_hosts.add(api_url.netloc)

    allowed_origins = {
        settings.frontend_origin,
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://[::1]:*",
        "https://localhost:*",
        "https://127.0.0.1:*",
        "https://[::1]:*",
    }
    if api_url.scheme and api_url.netloc:
        allowed_origins.add(f"{api_url.scheme}://{api_url.netloc}")
    if frontend_url.scheme and frontend_url.netloc:
        allowed_origins.add(f"{frontend_url.scheme}://{frontend_url.netloc}")

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(allowed_hosts),
        allowed_origins=sorted(allowed_origins),
    )


def create_mcp_server(session_factory, settings: Settings) -> FastMCP:
    mcp = FastMCP(
        settings.app_name,
        instructions=(
            "ThreadGram gives agents a shared Telegram-style inbox over MCP while human operators manage conversations from the local web portal."
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=build_transport_security(settings),
    )

    @mcp.tool()
    async def whoami() -> WhoAmIOut:
        identity = get_current_agent()
        return WhoAmIOut(
            workspace_id=identity.workspace_id,
            key_id=identity.key_id,
            key_prefix=identity.key_prefix,
            agent_name=identity.agent_name,
        )

    @mcp.tool()
    async def list_agents() -> AgentsResponse:
        identity = get_current_agent()
        async with session_factory() as session:
            agents = await list_agents_service(session, identity.workspace_id)
            return AgentsResponse(agents=agents)

    @mcp.tool()
    async def fetch_inbox(unread_only: bool = True, limit: int = 20) -> InboxResponse:
        identity = get_current_agent()
        async with session_factory() as session:
            return await fetch_inbox_service(session, identity=identity, unread_only=unread_only, limit=limit)

    @mcp.tool()
    async def get_thread(thread_id: str, limit: int = 50) -> ThreadDetail:
        identity = get_current_agent()
        async with session_factory() as session:
            return await get_thread_service(session, identity=identity, thread_id=thread_id, limit=limit)

    @mcp.tool()
    async def send_message(
        to_agent: str,
        body: str,
        thread_id: str | None = None,
        subject: str | None = None,
    ) -> SendMessageResult:
        identity = get_current_agent()
        async with session_factory() as session:
            return await send_message_service(
                session,
                identity=identity,
                to_agent=to_agent,
                body=body,
                thread_id=thread_id,
                subject=subject,
                allow_unknown_recipients=settings.local_mode,
            )

    @mcp.tool()
    async def mark_thread_read(thread_id: str) -> MarkThreadReadResult:
        identity = get_current_agent()
        async with session_factory() as session:
            return await mark_thread_read_service(session, identity=identity, thread_id=thread_id)

    return mcp


class MCPAgentAuthApp:
    def __init__(self, app: ASGIApp, session_factory):
        self.app = app
        self.session_factory = session_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        authorization = headers.get("authorization")
        settings = scope["app"].state.settings
        host = headers.get("host", "").split(":", 1)[0].strip().lower()
        is_local_host = host in {"localhost", "127.0.0.1", "::1", "[::1]"}

        identity: AgentIdentity | None = None
        if authorization and authorization.lower().startswith("bearer "):
            presented_key = authorization.split(" ", 1)[1].strip()
            async with self.session_factory() as session:
                identity = await authenticate_agent_key(session, presented_key)
            if identity is None:
                await JSONResponse({"detail": "Invalid agent key."}, status_code=401)(scope, receive, send)
                return
        elif settings.local_mode and is_local_host:
            query_params = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="ignore"))
            local_agent = query_params.get(settings.local_agent_query_param, [None])[0] or headers.get(
                settings.local_agent_header_name
            )
            local_workspace = query_params.get(settings.local_workspace_query_param, [None])[0] or headers.get(
                settings.local_workspace_header_name
            )
            if not local_agent:
                await JSONResponse(
                    {
                        "detail": (
                            f"Local mode requires '?{settings.local_agent_query_param}=name' or the "
                            f"'{settings.local_agent_header_name}' header."
                        )
                    },
                    status_code=401,
                )(scope, receive, send)
                return
            try:
                async with self.session_factory() as session:
                    identity = await authenticate_local_agent(
                        session,
                        agent_name=local_agent,
                        workspace_slug=local_workspace or settings.local_workspace_slug,
                        local_user_login=settings.local_user_login,
                        default_workspace_slug=settings.local_workspace_slug,
                        default_workspace_name=settings.local_workspace_name,
                    )
            except ValueError as exc:
                await JSONResponse({"detail": str(exc)}, status_code=400)(scope, receive, send)
                return
        else:
            await JSONResponse({"detail": "Bearer token required."}, status_code=401)(scope, receive, send)
            return

        token = set_current_agent(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_agent(token)
