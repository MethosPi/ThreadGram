from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from agentgram.schemas import AgentsResponse, InboxResponse, MarkThreadReadResult, SendMessageResult, ThreadDetail, WhoAmIOut


class AgentGramBackendClient:
    def __init__(
        self,
        *,
        server_url: str,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.api_base_url = self.server_url[:-4] if self.server_url.endswith("/mcp") else self.server_url
        self.api_key = api_key
        self._external_client = http_client
        self._client = http_client or httpx.AsyncClient(
            base_url=self.api_base_url,
            follow_redirects=True,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

    async def aclose(self) -> None:
        if self._external_client is None:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        response = await self._client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def whoami(self) -> WhoAmIOut:
        payload = await self._request("GET", "/api/agent/whoami")
        return WhoAmIOut.model_validate(payload)

    async def list_agents(self) -> AgentsResponse:
        payload = await self._request("GET", "/api/agent/agents")
        return AgentsResponse.model_validate(payload)

    async def fetch_inbox(self, *, unread_only: bool = True, limit: int = 20) -> InboxResponse:
        payload = await self._request(
            "GET",
            "/api/agent/inbox",
            params={"unread_only": unread_only, "limit": limit},
        )
        return InboxResponse.model_validate(payload)

    async def get_thread(self, *, thread_id: str, limit: int = 50) -> ThreadDetail:
        payload = await self._request("GET", f"/api/agent/threads/{thread_id}", params={"limit": limit})
        return ThreadDetail.model_validate(payload)

    async def send_message(
        self,
        *,
        to_agent: str,
        body: str,
        thread_id: str | None = None,
        subject: str | None = None,
    ) -> SendMessageResult:
        payload = await self._request(
            "POST",
            "/api/agent/messages",
            json={
                "to_agent": to_agent,
                "body": body,
                "thread_id": thread_id,
                "subject": subject,
            },
        )
        return SendMessageResult.model_validate(payload)

    async def mark_thread_read(self, *, thread_id: str) -> MarkThreadReadResult:
        payload = await self._request("POST", f"/api/agent/threads/{thread_id}/read")
        return MarkThreadReadResult.model_validate(payload)


@dataclass
class BridgeContext:
    backend: AgentGramBackendClient


def create_stdio_bridge(
    *,
    server_url: str,
    api_key: str,
    http_client: httpx.AsyncClient | None = None,
) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[BridgeContext]:
        client = AgentGramBackendClient(server_url=server_url, api_key=api_key, http_client=http_client)
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
        return await ctx.request_context.lifespan_context.backend.whoami()

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
