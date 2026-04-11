from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentgram.config import Settings
from agentgram.context import AgentIdentity, get_current_agent, reset_current_agent, set_current_agent
from agentgram.schemas import AgentsResponse, InboxResponse, MarkThreadReadResult, SendMessageResult, ThreadDetail, WhoAmIOut
from agentgram.services.core import (
    authenticate_agent_key,
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
            "AgentGram gives agents a shared Telegram-style inbox over MCP while human operators manage workspaces and keys from the web portal."
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
        if not authorization or not authorization.lower().startswith("bearer "):
            await JSONResponse({"detail": "Bearer token required."}, status_code=401)(scope, receive, send)
            return

        presented_key = authorization.split(" ", 1)[1].strip()
        async with self.session_factory() as session:
            identity: AgentIdentity | None = await authenticate_agent_key(session, presented_key)
        if identity is None:
            await JSONResponse({"detail": "Invalid agent key."}, status_code=401)(scope, receive, send)
            return

        token = set_current_agent(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_agent(token)
