from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager

from agentgram.app import create_app
from agentgram.config import Settings

from tests.test_mcp import call_tool


@pytest.fixture
async def local_app(tmp_path: Path):
    settings = Settings(
        testing=True,
        local_mode=True,
        auto_create_schema=True,
        secret_key="local-test-secret",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'agentgram-local.db'}",
        frontend_origin="http://localhost:4173",
        public_api_base_url="http://localhost:8000",
        cors_origins=["http://localhost:4173"],
        session_same_site="lax",
        session_https_only=False,
    )
    application = create_app(settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def local_client(local_app):
    transport = httpx.ASGITransport(app=local_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_local_session_and_workspace_routes_work_without_login(local_client):
    session_response = await local_client.get("/api/session")
    session_response.raise_for_status()
    session_payload = session_response.json()

    assert session_payload["authenticated"] is True
    assert session_payload["local_mode"] is True
    assert session_payload["default_local_workspace_slug"] == "local"
    assert session_payload["default_local_workspace_name"] == "Local Control Room"
    assert session_payload["user"]["github_login"] == "local"

    created_response = await local_client.post("/api/workspaces", json={"name": "Project Alpha"})
    created_response.raise_for_status()
    created = created_response.json()

    assert created["human_agent_name"] == "human"
    assert created["slug"] == "project-alpha"


@pytest.mark.asyncio
async def test_local_mode_agents_connect_without_keys(local_app, local_client):
    sent_response = await local_client.post(
        "/api/workspaces",
        json={"name": "Project Beta"},
    )
    sent_response.raise_for_status()
    workspace = sent_response.json()

    human_message = await local_client.post(
        f"/api/workspaces/{workspace['id']}/messages",
        json={
            "to_agent": "codex-main",
            "body": "Hello from local human.",
            "subject": "Local smoke",
        },
    )
    human_message.raise_for_status()

    inbox_response = await local_client.get(
        "/api/agent/inbox",
        params={"agent": "codex-main", "workspace": workspace["slug"], "unread_only": True, "limit": 20},
    )
    inbox_response.raise_for_status()
    inbox = inbox_response.json()

    assert inbox["threads"][0]["counterpart"] == "human"

    whoami = await call_tool(
        local_app,
        None,
        "whoami",
        mcp_url=f"http://localhost:8000/mcp?agent=claude-reviewer&workspace={workspace['slug']}",
    )
    assert whoami["agent_name"] == "claude-reviewer"
