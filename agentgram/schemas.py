from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    github_login: str
    avatar_url: str | None = None


class SessionOut(BaseModel):
    authenticated: bool
    user: UserOut | None = None
    public_api_base_url: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    created_at: datetime


class AgentSummary(BaseModel):
    agent_name: str
    active_key_count: int
    last_used_at: datetime | None = None


class AgentKeyCreate(BaseModel):
    agent_name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


class AgentKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    agent_name: str
    description: str | None = None
    key_prefix: str
    is_revoked: bool
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class AgentKeyCreatedOut(BaseModel):
    key: AgentKeyOut
    secret: str


class MessageOut(BaseModel):
    id: int
    sender_agent_name: str
    recipient_agent_name: str
    body: str
    created_at: datetime


class ThreadSummary(BaseModel):
    thread_id: str
    workspace_id: str
    subject: str | None = None
    participants: list[str]
    counterpart: str
    last_message_id: int | None = None
    last_message_at: datetime | None = None
    last_message_preview: str | None = None
    last_message_sender: str | None = None
    unread_count: int = 0


class ThreadDetail(ThreadSummary):
    messages: list[MessageOut]


class WorkspaceDetail(WorkspaceOut):
    agents: list[AgentSummary]
    keys: list[AgentKeyOut]


class SendMessageRequest(BaseModel):
    to_agent: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    thread_id: str | None = None
    subject: str | None = Field(default=None, max_length=255)


class SendMessageResult(BaseModel):
    thread_id: str
    message: MessageOut


class MarkThreadReadResult(BaseModel):
    thread_id: str
    last_read_message_id: int | None
    read_at: datetime


class WhoAmIOut(BaseModel):
    workspace_id: str
    key_id: str
    key_prefix: str
    agent_name: str


class AgentsResponse(BaseModel):
    agents: list[AgentSummary]


class InboxResponse(BaseModel):
    threads: list[ThreadSummary]


class TestingLoginRequest(BaseModel):
    github_login: str = Field(min_length=1, max_length=255)
    github_user_id: str | None = None
