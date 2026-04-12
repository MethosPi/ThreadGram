from __future__ import annotations

import httpx
import pytest

from threadgram.bridge import ThreadGramBackendClient

from tests.helpers import create_agent_key, create_workspace, login_test_user
from tests.test_mcp import call_tool


@pytest.mark.asyncio
async def test_bridge_client_reads_same_thread_history_as_remote_mcp(app, client):
    await login_test_user(client)
    workspace = await create_workspace(client, "Bridge Workspace")
    codex_key = await create_agent_key(client, workspace["id"], "codex-main")
    claude_key = await create_agent_key(client, workspace["id"], "claude-reviewer")

    sent = await call_tool(
        app,
        codex_key["secret"],
        "send_message",
        {"to_agent": "claude-reviewer", "body": "Shared through one backend"},
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {claude_key['secret']}"},
    ) as async_client:
        bridge_client = ThreadGramBackendClient(
            server_url="http://testserver/mcp",
            api_key=claude_key["secret"],
            http_client=async_client,
        )
        inbox = await bridge_client.fetch_inbox(unread_only=True, limit=20)
        assert inbox.threads[0].thread_id == sent["thread_id"]

        thread = await bridge_client.get_thread(thread_id=sent["thread_id"], limit=50)
        assert thread.messages[0].body == "Shared through one backend"
