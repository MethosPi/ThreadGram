from __future__ import annotations

import pytest

from tests.helpers import create_agent_key, create_workspace, login_test_user


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
