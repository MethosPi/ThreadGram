from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from agentgram.client import AgentGramBackendClient
from agentgram.schemas import AgentsResponse, InboxResponse, MarkThreadReadResult, SendMessageResult, ThreadDetail, WhoAmIOut


@dataclass
class BridgeContext:
    backend: AgentGramBackendClient


def create_stdio_bridge(
    *,
    server_url: str,
    api_key: str | None = None,
    agent_name: str | None = None,
    workspace: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[BridgeContext]:
        client = AgentGramBackendClient(
            server_url=server_url,
            api_key=api_key,
            agent_name=agent_name,
            workspace=workspace,
            http_client=http_client,
        )
        try:
            yield BridgeContext(backend=client)
        finally:
            await client.aclose()

    mcp = FastMCP(
        "AgentGram Stdio Bridge",
        instructions=(
            "A local stdio MCP bridge for AgentGram. All tool calls are forwarded to the hosted AgentGram backend."
        ),
        lifespan=lifespan,
    )

    @mcp.tool()
    async def whoami(ctx: Context[ServerSession, BridgeContext]) -> WhoAmIOut:
        return await ctx.request_context.lifespan_context.backend.whoami_model()

    @mcp.tool()
    async def list_agents(ctx: Context[ServerSession, BridgeContext]) -> AgentsResponse:
        return await ctx.request_context.lifespan_context.backend.list_agents()

    @mcp.tool()
    async def fetch_inbox(
        ctx: Context[ServerSession, BridgeContext],
        unread_only: bool = True,
        limit: int = 20,
    ) -> InboxResponse:
        return await ctx.request_context.lifespan_context.backend.fetch_inbox(
            unread_only=unread_only,
            limit=limit,
        )

    @mcp.tool()
    async def get_thread(
        ctx: Context[ServerSession, BridgeContext],
        thread_id: str,
        limit: int = 50,
    ) -> ThreadDetail:
        return await ctx.request_context.lifespan_context.backend.get_thread(thread_id=thread_id, limit=limit)

    @mcp.tool()
    async def send_message(
        ctx: Context[ServerSession, BridgeContext],
        to_agent: str,
        body: str,
        thread_id: str | None = None,
        subject: str | None = None,
    ) -> SendMessageResult:
        return await ctx.request_context.lifespan_context.backend.send_message(
            to_agent=to_agent,
            body=body,
            thread_id=thread_id,
            subject=subject,
        )

    @mcp.tool()
    async def mark_thread_read(
        ctx: Context[ServerSession, BridgeContext],
        thread_id: str,
    ) -> MarkThreadReadResult:
        return await ctx.request_context.lifespan_context.backend.mark_thread_read(thread_id=thread_id)

    return mcp
