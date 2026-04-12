from __future__ import annotations

import httpx


async def login_test_user(client: httpx.AsyncClient, github_login: str = "owner") -> dict:
    response = await client.post("/api/testing/login", json={"github_login": github_login})
    response.raise_for_status()
    return response.json()


async def create_workspace(client: httpx.AsyncClient, name: str = "Primary Workspace") -> dict:
    response = await client.post("/api/workspaces", json={"name": name})
    response.raise_for_status()
    return response.json()


async def create_agent_key(client: httpx.AsyncClient, workspace_id: str, agent_name: str, description: str | None = None) -> dict:
    response = await client.post(
        f"/api/workspaces/{workspace_id}/keys",
        json={"agent_name": agent_name, "description": description},
    )
    response.raise_for_status()
    return response.json()


async def send_human_message(
    client: httpx.AsyncClient,
    workspace_id: str,
    *,
    to_agent: str,
    body: str,
    thread_id: str | None = None,
    subject: str | None = None,
) -> dict:
    response = await client.post(
        f"/api/workspaces/{workspace_id}/messages",
        json={
            "to_agent": to_agent,
            "body": body,
            "thread_id": thread_id,
            "subject": subject,
        },
    )
    response.raise_for_status()
    return response.json()
