from __future__ import annotations

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.helpers import create_agent_key, create_workspace, login_test_user


async def call_tool(
    app,
    agent_key: str | None,
    tool_name: str,
    arguments: dict | None = None,
    *,
    mcp_url: str = "http://testserver/mcp",
    headers: dict[str, str] | None = None,
):
    transport = httpx.ASGITransport(app=app)
    request_headers = dict(headers or {})
    if agent_key:
        request_headers.setdefault("Authorization", f"Bearer {agent_key}")
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=request_headers,
    ) as async_client:
        async with streamable_http_client(mcp_url, http_client=async_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments or {})
                return result.structuredContent


@pytest.mark.asyncio
async def test_mcp_send_message_and_unread_flow(app, client):
    await login_test_user(client)
    workspace = await create_workspace(client, "Inbox Mesh")
    codex_key = await create_agent_key(client, workspace["id"], "codex-main")
    claude_key = await create_agent_key(client, workspace["id"], "claude-reviewer")

    whoami = await call_tool(app, codex_key["secret"], "whoami")
    assert whoami["agent_name"] == "codex-main"

    sent = await call_tool(
        app,
        codex_key["secret"],
        "send_message",
        {"to_agent": "claude-reviewer", "body": "Review this change", "subject": "PR review"},
    )
    assert sent["message"]["recipient_agent_name"] == "claude-reviewer"

    inbox = await call_tool(app, claude_key["secret"], "fetch_inbox", {"unread_only": True, "limit": 20})
    assert len(inbox["threads"]) == 1
    thread_id = inbox["threads"][0]["thread_id"]

    thread = await call_tool(app, claude_key["secret"], "get_thread", {"thread_id": thread_id, "limit": 50})
    assert thread["messages"][0]["body"] == "Review this change"

    marked = await call_tool(app, claude_key["secret"], "mark_thread_read", {"thread_id": thread_id})
    assert marked["thread_id"] == thread_id

    empty_inbox = await call_tool(app, claude_key["secret"], "fetch_inbox", {"unread_only": True, "limit": 20})
    assert empty_inbox["threads"] == []


@pytest.mark.asyncio
async def test_workspace_isolation_for_agent_keys(app, client):
    await login_test_user(client)
    workspace_a = await create_workspace(client, "Workspace A")
    workspace_b = await create_workspace(client, "Workspace B")

    key_a = await create_agent_key(client, workspace_a["id"], "codex-main")
    key_b_sender = await create_agent_key(client, workspace_b["id"], "claude-reviewer")
    await create_agent_key(client, workspace_b["id"], "codex-main")

    sent = await call_tool(
        app,
        key_b_sender["secret"],
        "send_message",
        {"to_agent": "codex-main", "body": "Only workspace B should see this"},
    )

    agents_a = await call_tool(app, key_a["secret"], "list_agents")
    assert [agent["agent_name"] for agent in agents_a["agents"]] == ["codex-main", "human"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {key_a['secret']}"},
    ) as async_client:
        response = await async_client.get(f"/api/agent/threads/{sent['thread_id']}", params={"limit": 50})
        assert response.status_code == 404
