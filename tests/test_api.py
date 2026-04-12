from __future__ import annotations

import pytest

from tests.helpers import create_agent_key, create_workspace, login_test_user, send_human_message


@pytest.mark.asyncio
async def test_workspace_key_lifecycle_and_secret_visibility(client):
    await login_test_user(client)
    workspace = await create_workspace(client, "Studio Mesh")

    created = await create_agent_key(client, workspace["id"], "codex-main", "Primary agent")
    assert created["key"]["agent_name"] == "codex-main"
    assert created["secret"].startswith("amk_")

    detail_response = await client.get(f"/api/workspaces/{workspace['id']}")
    detail_response.raise_for_status()
    detail = detail_response.json()

    assert detail["keys"][0]["key_prefix"] in created["secret"]
    assert "secret" not in detail["keys"][0]

    revoke_response = await client.post(f"/api/workspaces/{workspace['id']}/keys/{created['key']['id']}/revoke")
    revoke_response.raise_for_status()
    revoked = revoke_response.json()
    assert revoked["is_revoked"] is True


@pytest.mark.asyncio
async def test_human_identity_can_chat_from_owner_dashboard(client):
    await login_test_user(client)
    workspace = await create_workspace(client, "Human Loop")
    codex = await create_agent_key(client, workspace["id"], "codex-main", "Primary coding agent")

    detail_response = await client.get(f"/api/workspaces/{workspace['id']}")
    detail_response.raise_for_status()
    detail = detail_response.json()

    assert detail["human_agent_name"] == "human"
    assert any(agent["agent_name"] == "human" for agent in detail["agents"])

    sent = await send_human_message(
        client,
        workspace["id"],
        to_agent="codex-main",
        body="Please review the latest plan.",
        subject="Operator check-in",
    )

    inbox_response = await client.get(
        "/api/agent/inbox",
        headers={"Authorization": f"Bearer {codex['secret']}"},
        params={"unread_only": True, "limit": 20},
    )
    inbox_response.raise_for_status()
    inbox = inbox_response.json()

    assert inbox["threads"][0]["counterpart"] == "human"
    assert inbox["threads"][0]["human_participant"] is False

    reply_response = await client.post(
        "/api/agent/messages",
        headers={"Authorization": f"Bearer {codex['secret']}"},
        json={
            "to_agent": "human",
            "body": "Review complete.",
            "thread_id": sent["thread_id"],
        },
    )
    reply_response.raise_for_status()

    owner_threads_response = await client.get(f"/api/workspaces/{workspace['id']}/threads")
    owner_threads_response.raise_for_status()
    owner_threads = owner_threads_response.json()

    assert owner_threads[0]["human_participant"] is True
    assert owner_threads[0]["human_reply_target"] == "codex-main"
    assert owner_threads[0]["unread_count"] == 1

    mark_read_response = await client.post(f"/api/workspaces/{workspace['id']}/threads/{sent['thread_id']}/read")
    mark_read_response.raise_for_status()

    owner_thread_response = await client.get(f"/api/workspaces/{workspace['id']}/threads/{sent['thread_id']}")
    owner_thread_response.raise_for_status()
    owner_thread = owner_thread_response.json()

    assert owner_thread["human_participant"] is True
    assert owner_thread["messages"][-1]["body"] == "Review complete."
