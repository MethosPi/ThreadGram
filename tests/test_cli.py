from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager

from agentgram.app import create_app
from agentgram.cli import run_cli_async
from agentgram.config import Settings

from tests.helpers import create_agent_key, create_workspace, login_test_user


class TTYStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
async def local_app(tmp_path: Path):
    settings = Settings(
        testing=True,
        local_mode=True,
        auto_create_schema=True,
        secret_key="local-test-secret",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'agentgram-cli-local.db'}",
        frontend_origin="http://localhost:4173",
        public_api_base_url="http://localhost:8000",
        cors_origins=["http://localhost:4173"],
        session_same_site="lax",
        session_https_only=False,
    )
    application = create_app(settings)
    async with LifespanManager(application):
        yield application


async def invoke_cli(
    argv: list[str],
    async_client: httpx.AsyncClient,
    *,
    stdin: io.StringIO | None = None,
) -> str:
    stdout = io.StringIO()
    await run_cli_async(
        argv,
        stdin=stdin or TTYStringIO(),
        stdout=stdout,
        http_client=async_client,
    )
    return stdout.getvalue()


async def local_agent_send(
    async_client: httpx.AsyncClient,
    *,
    agent: str,
    workspace: str,
    to_agent: str,
    body: str,
    thread_id: str | None = None,
    subject: str | None = None,
) -> dict:
    response = await async_client.post(
        "/api/agent/messages",
        params={"agent": agent, "workspace": workspace},
        json={
            "to_agent": to_agent,
            "body": body,
            "thread_id": thread_id,
            "subject": subject,
        },
    )
    response.raise_for_status()
    return response.json()


@pytest.mark.asyncio
async def test_chat_cli_agent_local_flow(local_app):
    transport = httpx.ASGITransport(app=local_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as async_client:
        whoami_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "whoami",
            ],
            async_client,
        )
        assert "Role: agent" in whoami_output
        assert "Agent: codex-main" in whoami_output

        workspaces_response = await async_client.get("/api/workspaces")
        workspaces_response.raise_for_status()
        workspace_id = workspaces_response.json()[0]["id"]

        human_message = await async_client.post(
            f"/api/workspaces/{workspace_id}/messages",
            json={
                "to_agent": "codex-main",
                "body": "Local human says hi.",
                "subject": "CLI local",
            },
        )
        human_message.raise_for_status()

        inbox_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "inbox",
                "--json",
            ],
            async_client,
        )
        inbox_payload = json.loads(inbox_output)
        thread_id = inbox_payload["threads"][0]["thread_id"]
        assert inbox_payload["threads"][0]["counterpart"] == "human"

        thread_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "thread",
                thread_id,
            ],
            async_client,
        )
        assert "Local human says hi." in thread_output

        reply_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "reply",
                thread_id,
            ],
            async_client,
            stdin=io.StringIO("Roger that.\n"),
        )
        assert "Sent reply" in reply_output

        mark_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "mark-read",
                thread_id,
            ],
            async_client,
        )
        assert f"Marked read: {thread_id}" in mark_output

        empty_inbox_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "inbox",
                "--json",
            ],
            async_client,
        )
        assert json.loads(empty_inbox_output)["threads"] == []


@pytest.mark.asyncio
async def test_chat_cli_agent_watch_once_shows_changes_and_empty_state(local_app):
    transport = httpx.ASGITransport(app=local_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as async_client:
        await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "whoami",
            ],
            async_client,
        )

        workspaces_response = await async_client.get("/api/workspaces")
        workspaces_response.raise_for_status()
        workspace_id = workspaces_response.json()[0]["id"]

        message_response = await async_client.post(
            f"/api/workspaces/{workspace_id}/messages",
            json={
                "to_agent": "codex-main",
                "body": "Watch this thread.",
                "subject": "watch",
            },
        )
        message_response.raise_for_status()
        thread_id = message_response.json()["thread_id"]

        watch_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "watch",
                "--once",
            ],
            async_client,
        )
        assert thread_id in watch_output
        assert "Watch this thread." in watch_output

        await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "mark-read",
                thread_id,
            ],
            async_client,
        )

        empty_watch_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000/mcp",
                "--agent",
                "codex-main",
                "--workspace",
                "local",
                "watch",
                "--once",
            ],
            async_client,
        )
        assert "No matching threads." in empty_watch_output


@pytest.mark.asyncio
async def test_chat_cli_agent_hosted_flow(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        await login_test_user(async_client)
        workspace = await create_workspace(async_client, "Hosted CLI")
        codex = await create_agent_key(async_client, workspace["id"], "codex-main")
        claude = await create_agent_key(async_client, workspace["id"], "claude-reviewer")

        send_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://testserver/mcp",
                "--api-key",
                codex["secret"],
                "send",
                "--to",
                "claude-reviewer",
                "--subject",
                "Hosted chat",
                "--body",
                "Please review this.",
            ],
            async_client,
        )
        assert "Sent message" in send_output

        inbox_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://testserver/mcp",
                "--api-key",
                claude["secret"],
                "inbox",
                "--json",
            ],
            async_client,
        )
        thread_id = json.loads(inbox_output)["threads"][0]["thread_id"]

        reply_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://testserver/mcp",
                "--api-key",
                claude["secret"],
                "reply",
                thread_id,
                "--body",
                "Reviewed and approved.",
            ],
            async_client,
        )
        assert "Sent reply" in reply_output

        thread_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://testserver/mcp",
                "--api-key",
                codex["secret"],
                "thread",
                thread_id,
            ],
            async_client,
        )
        assert "Reviewed and approved." in thread_output


@pytest.mark.asyncio
async def test_chat_cli_human_local_flow_and_guardrails(local_app, capsys):
    transport = httpx.ASGITransport(app=local_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as async_client:
        whoami_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000",
                "--as",
                "human",
                "whoami",
            ],
            async_client,
        )
        assert "Role: human" in whoami_output
        assert "Workspace: Local Control Room" in whoami_output

        human_thread = await local_agent_send(
            async_client,
            agent="codex-main",
            workspace="local",
            to_agent="human",
            body="Need a human answer.",
            subject="Human CLI",
        )
        agent_only_thread = await local_agent_send(
            async_client,
            agent="codex-main",
            workspace="local",
            to_agent="claude-reviewer",
            body="Agent-only traffic.",
            subject="Internal",
        )

        inbox_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000",
                "--as",
                "human",
                "inbox",
                "--json",
            ],
            async_client,
        )
        inbox_payload = json.loads(inbox_output)
        assert [thread["thread_id"] for thread in inbox_payload["threads"]] == [human_thread["thread_id"]]

        thread_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000",
                "--as",
                "human",
                "thread",
                human_thread["thread_id"],
            ],
            async_client,
        )
        assert "Need a human answer." in thread_output

        reply_output = await invoke_cli(
            [
                "chat",
                "--server-url",
                "http://localhost:8000",
                "--as",
                "human",
                "reply",
                human_thread["thread_id"],
            ],
            async_client,
            stdin=io.StringIO("Human acknowledged.\n"),
        )
        assert "Sent reply" in reply_output

        with pytest.raises(SystemExit):
            await invoke_cli(
                [
                    "chat",
                    "--server-url",
                    "http://localhost:8000",
                    "--as",
                    "human",
                    "reply",
                    agent_only_thread["thread_id"],
                ],
                async_client,
                stdin=io.StringIO("Should not send.\n"),
            )

        assert "only reply to threads that include the human participant" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_chat_cli_errors_are_explicit(app, local_app, capsys):
    hosted_transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=hosted_transport, base_url="http://testserver") as hosted_client:
        with pytest.raises(SystemExit):
            await invoke_cli(
                [
                    "chat",
                    "--server-url",
                    "http://testserver/mcp",
                    "--as",
                    "human",
                    "whoami",
                ],
                hosted_client,
            )
        assert "local AgentGram server on localhost" in capsys.readouterr().err

    local_transport = httpx.ASGITransport(app=local_app)
    async with httpx.AsyncClient(transport=local_transport, base_url="http://localhost:8000") as local_client:
        with pytest.raises(SystemExit):
            await invoke_cli(
                [
                    "chat",
                    "--server-url",
                    "http://localhost:8000/mcp",
                    "--agent",
                    "codex-main",
                    "--workspace",
                    "local",
                    "send",
                    "--to",
                    "claude-reviewer",
                ],
                local_client,
            )
        assert "Message body is required" in capsys.readouterr().err

        with pytest.raises(SystemExit):
            await invoke_cli(
                [
                    "chat",
                    "--server-url",
                    "http://localhost:8000/mcp",
                    "--agent",
                    "codex-main",
                    "--workspace",
                    "local",
                    "thread",
                    "missing-thread",
                ],
                local_client,
            )
        assert "Thread not found." in capsys.readouterr().err

        with pytest.raises(SystemExit):
            await invoke_cli(
                [
                    "chat",
                    "--server-url",
                    "http://localhost:8000",
                    "--as",
                    "human",
                    "--agent",
                    "codex-main",
                    "whoami",
                ],
                local_client,
            )
        assert "does not support --agent" in capsys.readouterr().err
