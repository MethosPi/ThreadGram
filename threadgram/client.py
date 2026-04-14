from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from threadgram.schemas import (
    AgentsResponse,
    InboxResponse,
    InboxWaitResult,
    MarkThreadReadResult,
    MessageOut,
    SendMessageResult,
    SessionOut,
    ThreadDetail,
    ThreadSummary,
    WhoAmIOut,
    WorkspaceDetail,
    WorkspaceOut,
)


class ThreadGramAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConversationClient(Protocol):
    async def aclose(self) -> None: ...

    async def whoami(self) -> dict[str, Any]: ...

    async def list_agents(self) -> AgentsResponse: ...

    async def fetch_inbox(
        self,
        *,
        unread_only: bool = True,
        limit: int = 20,
        all_threads: bool = False,
    ) -> InboxResponse: ...

    async def get_thread(
        self,
        *,
        thread_id: str,
        limit: int = 50,
        all_threads: bool = False,
    ) -> ThreadDetail: ...

    async def send_message(
        self,
        *,
        to_agent: str,
        body: str,
        thread_id: str | None = None,
        subject: str | None = None,
    ) -> SendMessageResult: ...

    async def mark_thread_read(self, *, thread_id: str) -> MarkThreadReadResult: ...


def resolve_api_base_url(server_url: str) -> str:
    server_url = server_url.rstrip("/")
    if server_url.endswith("/mcp"):
        return server_url[:-4]
    return server_url


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()

    body = response.text.strip()
    if body:
        return body
    return f"Request failed with status {response.status_code}."


def _titleize_slug(slug: str) -> str:
    return slug.replace("-", " ").strip().title() or "Workspace"


@dataclass
class BaseAPIClient:
    server_url: str
    api_key: str | None = None
    http_client: httpx.AsyncClient | None = None

    def __post_init__(self) -> None:
        self.server_url = self.server_url.rstrip("/")
        self.api_base_url = resolve_api_base_url(self.server_url)
        self._external_client = self.http_client
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = self.http_client or httpx.AsyncClient(
            base_url=self.api_base_url,
            follow_redirects=True,
            headers=headers,
            timeout=30.0,
        )

    async def aclose(self) -> None:
        if self._external_client is None:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        response = await self._client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ThreadGramAPIError(
                _extract_error_detail(response),
                status_code=response.status_code,
            ) from exc
        if not response.content:
            return None
        return response.json()


class ThreadGramBackendClient(BaseAPIClient):
    def __init__(
        self,
        *,
        server_url: str,
        api_key: str | None = None,
        agent_name: str | None = None,
        workspace: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.agent_name = agent_name.strip() if agent_name else None
        self.workspace = workspace.strip() if workspace else None
        super().__init__(server_url=server_url, api_key=api_key, http_client=http_client)

    async def _agent_request(self, method: str, path: str, **kwargs):
        params = dict(kwargs.pop("params", {}) or {})
        headers = dict(kwargs.pop("headers", {}) or {})
        if not self.api_key:
            if not self.agent_name:
                raise ThreadGramAPIError(
                    "Agent name is required when no ThreadGram API key is provided."
                )
            params.setdefault("agent", self.agent_name)
            if self.workspace:
                params.setdefault("workspace", self.workspace)
        else:
            headers.setdefault("Authorization", f"Bearer {self.api_key}")
        return await self._request(method, path, params=params, headers=headers, **kwargs)

    async def whoami(self) -> dict[str, Any]:
        payload = await self._agent_request("GET", "/api/agent/whoami")
        identity = WhoAmIOut.model_validate(payload)
        return {
            "role": "agent",
            "agent_name": identity.agent_name,
            "workspace_id": identity.workspace_id,
            "workspace_slug": self.workspace,
            "workspace_name": None,
            "key_id": identity.key_id,
            "key_prefix": identity.key_prefix,
        }

    async def whoami_model(self) -> WhoAmIOut:
        payload = await self._agent_request("GET", "/api/agent/whoami")
        return WhoAmIOut.model_validate(payload)

    async def list_agents(self) -> AgentsResponse:
        payload = await self._agent_request("GET", "/api/agent/agents")
        return AgentsResponse.model_validate(payload)

    async def fetch_inbox(
        self,
        *,
        unread_only: bool = True,
        limit: int = 20,
        all_threads: bool = False,
    ) -> InboxResponse:
        payload = await self._agent_request(
            "GET",
            "/api/agent/inbox",
            params={"unread_only": unread_only, "limit": limit},
        )
        return InboxResponse.model_validate(payload)

    async def wait_for_inbox(
        self,
        *,
        timeout_seconds: float = 300.0,
    ) -> InboxWaitResult:
        payload = await self._agent_request(
            "GET",
            "/api/agent/inbox/wait",
            params={"timeout_seconds": timeout_seconds},
        )
        return InboxWaitResult.model_validate(payload)

    async def get_thread(
        self,
        *,
        thread_id: str,
        limit: int = 50,
        all_threads: bool = False,
    ) -> ThreadDetail:
        payload = await self._agent_request("GET", f"/api/agent/threads/{thread_id}", params={"limit": limit})
        return ThreadDetail.model_validate(payload)

    async def send_message(
        self,
        *,
        to_agent: str,
        body: str,
        thread_id: str | None = None,
        subject: str | None = None,
    ) -> SendMessageResult:
        payload = await self._agent_request(
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
        payload = await self._agent_request("POST", f"/api/agent/threads/{thread_id}/read")
        return MarkThreadReadResult.model_validate(payload)


class ThreadGramHumanLocalClient(BaseAPIClient):
    def __init__(
        self,
        *,
        server_url: str,
        workspace: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.workspace = workspace.strip() if workspace else None
        self._workspace_detail: WorkspaceDetail | None = None
        self._session: SessionOut | None = None
        super().__init__(server_url=server_url, http_client=http_client)

    async def session_status(self) -> SessionOut:
        if self._session is not None:
            return self._session
        payload = await self._request("GET", "/api/session")
        self._session = SessionOut.model_validate(payload)
        return self._session

    async def _ensure_local_session(self) -> SessionOut:
        session = await self.session_status()
        if not session.local_mode or not session.authenticated:
            raise ThreadGramAPIError(
                "Human chat mode only works against a local ThreadGram server on localhost. Use the dashboard for hosted mode."
            )
        return session

    async def _list_workspaces(self) -> list[WorkspaceOut]:
        payload = await self._request("GET", "/api/workspaces")
        return [WorkspaceOut.model_validate(item) for item in payload]

    async def _create_workspace(self, name: str, *, slug: str | None = None) -> WorkspaceDetail:
        body: dict[str, Any] = {"name": name}
        if slug is not None:
            body["slug"] = slug
        payload = await self._request("POST", "/api/workspaces", json=body)
        return WorkspaceDetail.model_validate(payload)

    async def _get_workspace(self, workspace_id: str) -> WorkspaceDetail:
        payload = await self._request("GET", f"/api/workspaces/{workspace_id}")
        return WorkspaceDetail.model_validate(payload)

    async def _resolve_workspace(self) -> WorkspaceDetail:
        if self._workspace_detail is not None:
            return self._workspace_detail

        session = await self._ensure_local_session()
        target_slug = self.workspace or session.default_local_workspace_slug or "local"
        target_name = session.default_local_workspace_name or _titleize_slug(target_slug)

        for workspace in await self._list_workspaces():
            if workspace.slug == target_slug:
                self._workspace_detail = await self._get_workspace(workspace.id)
                return self._workspace_detail

        created_name = target_name if target_slug == session.default_local_workspace_slug else _titleize_slug(target_slug)
        created = await self._create_workspace(created_name, slug=target_slug)
        self._workspace_detail = created
        return created

    async def whoami(self) -> dict[str, Any]:
        workspace = await self._resolve_workspace()
        return {
            "role": "human",
            "agent_name": workspace.human_agent_name,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "workspace_name": workspace.name,
            "key_id": f"human:{workspace.id}",
            "key_prefix": "human",
        }

    async def list_agents(self) -> AgentsResponse:
        workspace = await self._resolve_workspace()
        return AgentsResponse(agents=workspace.agents)

    async def _list_workspace_threads(self, *, limit: int) -> list[ThreadSummary]:
        workspace = await self._resolve_workspace()
        payload = await self._request("GET", f"/api/workspaces/{workspace.id}/threads", params={"limit": limit})
        return [ThreadSummary.model_validate(item) for item in payload]

    async def _get_workspace_thread(self, *, thread_id: str, limit: int) -> ThreadDetail:
        workspace = await self._resolve_workspace()
        payload = await self._request(
            "GET",
            f"/api/workspaces/{workspace.id}/threads/{thread_id}",
            params={"limit": limit},
        )
        return ThreadDetail.model_validate(payload)

    async def fetch_inbox(
        self,
        *,
        unread_only: bool = True,
        limit: int = 20,
        all_threads: bool = False,
    ) -> InboxResponse:
        fetch_limit = max(limit, 200) if (unread_only or not all_threads) else limit
        threads = await self._list_workspace_threads(limit=min(fetch_limit, 200))
        if not all_threads:
            threads = [thread for thread in threads if thread.human_participant]
        if unread_only:
            threads = [thread for thread in threads if thread.unread_count > 0]
        return InboxResponse(threads=threads[:limit])

    async def get_thread(
        self,
        *,
        thread_id: str,
        limit: int = 50,
        all_threads: bool = False,
    ) -> ThreadDetail:
        thread = await self._get_workspace_thread(thread_id=thread_id, limit=limit)
        if not all_threads and not thread.human_participant:
            raise ThreadGramAPIError(
                "Human chat mode can only open threads that include the human participant. Re-run with --all-threads to inspect agent-only threads."
            )
        return thread

    async def send_message(
        self,
        *,
        to_agent: str,
        body: str,
        thread_id: str | None = None,
        subject: str | None = None,
    ) -> SendMessageResult:
        workspace = await self._resolve_workspace()
        if thread_id:
            thread = await self._get_workspace_thread(thread_id=thread_id, limit=1)
            if not thread.human_participant:
                raise ThreadGramAPIError(
                    "Human chat mode can only reply to threads that include the human participant."
                )
        payload = await self._request(
            "POST",
            f"/api/workspaces/{workspace.id}/messages",
            json={
                "to_agent": to_agent,
                "body": body,
                "thread_id": thread_id,
                "subject": subject,
            },
        )
        return SendMessageResult.model_validate(payload)

    async def mark_thread_read(self, *, thread_id: str) -> MarkThreadReadResult:
        workspace = await self._resolve_workspace()
        thread = await self._get_workspace_thread(thread_id=thread_id, limit=1)
        if not thread.human_participant:
            raise ThreadGramAPIError(
                "Human chat mode can only mark threads as read when the human participant is part of the thread."
            )
        payload = await self._request("POST", f"/api/workspaces/{workspace.id}/threads/{thread_id}/read")
        return MarkThreadReadResult.model_validate(payload)


def thread_summary_to_dict(thread: ThreadSummary) -> dict[str, Any]:
    return thread.model_dump(mode="json")


def thread_detail_to_dict(thread: ThreadDetail) -> dict[str, Any]:
    return thread.model_dump(mode="json")


def message_to_dict(message: MessageOut) -> dict[str, Any]:
    return message.model_dump(mode="json")
