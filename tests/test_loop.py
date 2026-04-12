from __future__ import annotations

import httpx
import pytest

from agentgram.bridge import AgentGramBackendClient
from agentgram.loop import run_reply_pass

from tests.helpers import create_agent_key, create_workspace, login_test_user, send_human_message


class DummyRunner:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def generate_reply(self, *, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


@pytest.mark.asyncio
async def test_auto_reply_loop_handles_unread_threads(app, client):
    await login_test_user(client)
    workspace = await create_workspace(client, "Loop Workspace")
    codex = await create_agent_key(client, workspace["id"], "codex-main")
    sent = await send_human_message(
        client,
        workspace["id"],
        to_agent="codex-main",
        body="Can you acknowledge this automatically?",
        subject="Auto loop",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {codex['secret']}"},
    ) as async_client:
        backend = AgentGramBackendClient(
            server_url="http://testserver/mcp",
            api_key=codex["secret"],
            http_client=async_client,
        )
        runner = DummyRunner("Acknowledged from the loop.")

        handled = await run_reply_pass(
            backend=backend,
            runner=runner,
            reply_guidance="Reply in one sentence.",
        )

        assert handled == [sent["thread_id"]]
        assert len(runner.prompts) == 1

        thread = await backend.get_thread(thread_id=sent["thread_id"], limit=50)
        assert thread.messages[-1].body == "Acknowledged from the loop."

        inbox = await backend.fetch_inbox(unread_only=True, limit=20)
        assert inbox.threads == []
