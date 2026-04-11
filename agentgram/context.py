from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentIdentity:
    key_id: str
    key_prefix: str
    workspace_id: str
    agent_name: str


_current_agent: ContextVar[AgentIdentity | None] = ContextVar("agentgram_current_agent", default=None)


def set_current_agent(identity: AgentIdentity):
    return _current_agent.set(identity)


def reset_current_agent(token) -> None:
    _current_agent.reset(token)


def get_current_agent() -> AgentIdentity:
    identity = _current_agent.get()
    if identity is None:
        raise RuntimeError("No authenticated agent is bound to the current request.")
    return identity
