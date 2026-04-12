from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from threadgram.context import AgentIdentity
from threadgram.models import AgentKey, Message, Thread, ThreadAgentState, User, Workspace
from threadgram.schemas import (
    AgentSummary,
    InboxResponse,
    MarkThreadReadResult,
    MessageOut,
    SendMessageResult,
    ThreadDetail,
    ThreadSummary,
)
from threadgram.security import extract_agent_key_prefix, generate_agent_key, verify_agent_key

HUMAN_AGENT_NAME = "human"
LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"
LOCAL_GITHUB_USER_ID = "local-owner"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


def titleize_slug(slug: str) -> str:
    return slug.replace("-", " ").strip().title() or "Workspace"


def is_human_agent_name(value: str) -> bool:
    return value.strip().casefold() == HUMAN_AGENT_NAME


def build_human_identity(*, workspace_id: str) -> AgentIdentity:
    return AgentIdentity(
        key_id=f"human:{workspace_id}",
        key_prefix="human",
        workspace_id=workspace_id,
        agent_name=HUMAN_AGENT_NAME,
    )


async def get_or_create_user_from_github(
    session: AsyncSession,
    *,
    github_user_id: str,
    github_login: str,
    avatar_url: str | None,
) -> User:
    statement = select(User).where(User.github_user_id == github_user_id)
    user = await session.scalar(statement)
    if user is None:
        user = User(
            id=str(uuid4()),
            github_user_id=github_user_id,
            github_login=github_login,
            avatar_url=avatar_url,
        )
        session.add(user)
    else:
        user.github_login = github_login
        user.avatar_url = avatar_url

    await session.commit()
    await session.refresh(user)
    return user


async def ensure_local_user(
    session: AsyncSession,
    *,
    github_login: str = "local",
) -> User:
    statement = select(User).where(User.github_user_id == LOCAL_GITHUB_USER_ID)
    user = await session.scalar(statement)
    if user is None:
        user = User(
            id=LOCAL_USER_ID,
            github_user_id=LOCAL_GITHUB_USER_ID,
            github_login=github_login,
            avatar_url=None,
        )
        session.add(user)
        try:
            await session.commit()
            await session.refresh(user)
            return user
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(select(User).where(User.github_user_id == LOCAL_GITHUB_USER_ID))
            if existing is not None:
                return existing
            raise

    if user.github_login != github_login:
        user.github_login = github_login
        await session.commit()
        await session.refresh(user)
    return user


async def list_workspaces_for_user(session: AsyncSession, user_id: str) -> list[Workspace]:
    statement = select(Workspace).where(Workspace.owner_user_id == user_id).order_by(Workspace.created_at.desc())
    return list(await session.scalars(statement))


async def get_workspace_for_user(session: AsyncSession, workspace_id: str, user_id: str) -> Workspace | None:
    statement = select(Workspace).where(
        Workspace.id == workspace_id,
        Workspace.owner_user_id == user_id,
    )
    return await session.scalar(statement)


async def create_workspace(session: AsyncSession, *, owner_user_id: str, name: str) -> Workspace:
    base_slug = slugify_name(name)
    slug = base_slug
    counter = 2

    while True:
        exists = await session.scalar(
            select(Workspace.id).where(
                Workspace.owner_user_id == owner_user_id,
                Workspace.slug == slug,
            )
        )
        if not exists:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    workspace = Workspace(
        id=str(uuid4()),
        owner_user_id=owner_user_id,
        name=name.strip(),
        slug=slug,
    )
    session.add(workspace)
    await session.commit()
    await session.refresh(workspace)
    return workspace


async def get_or_create_workspace_for_slug(
    session: AsyncSession,
    *,
    owner_user_id: str,
    slug: str,
    default_slug: str = "local",
    default_name: str = "Local Control Room",
) -> Workspace:
    normalized_slug = slugify_name(slug)
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.owner_user_id == owner_user_id,
            Workspace.slug == normalized_slug,
        )
    )
    if workspace is not None:
        return workspace

    workspace = Workspace(
        id=str(uuid4()),
        owner_user_id=owner_user_id,
        slug=normalized_slug,
        name=default_name if normalized_slug == slugify_name(default_slug) else titleize_slug(normalized_slug),
    )
    session.add(workspace)
    await session.commit()
    await session.refresh(workspace)
    return workspace


async def create_agent_key(
    session: AsyncSession,
    *,
    workspace_id: str,
    agent_name: str,
    description: str | None,
) -> tuple[AgentKey, str]:
    normalized_agent_name = agent_name.strip()
    if is_human_agent_name(normalized_agent_name):
        raise ValueError(f"'{HUMAN_AGENT_NAME}' is reserved for the workspace's human operator.")

    prefix, key_hash, full_key = generate_agent_key()
    key = AgentKey(
        id=str(uuid4()),
        workspace_id=workspace_id,
        agent_name=normalized_agent_name,
        description=description.strip() if description else None,
        key_prefix=prefix,
        key_hash=key_hash,
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key, full_key


async def list_workspace_keys(session: AsyncSession, workspace_id: str) -> list[AgentKey]:
    statement = (
        select(AgentKey)
        .where(AgentKey.workspace_id == workspace_id)
        .order_by(AgentKey.is_revoked.asc(), AgentKey.created_at.desc())
    )
    return list(await session.scalars(statement))


async def revoke_agent_key(session: AsyncSession, *, workspace_id: str, key_id: str) -> AgentKey | None:
    statement = select(AgentKey).where(AgentKey.workspace_id == workspace_id, AgentKey.id == key_id)
    key = await session.scalar(statement)
    if key is None:
        return None

    key.is_revoked = True
    key.revoked_at = utcnow()
    await session.commit()
    await session.refresh(key)
    return key


async def list_agents(session: AsyncSession, workspace_id: str) -> list[AgentSummary]:
    statement = (
        select(
            AgentKey.agent_name,
            func.count(AgentKey.id),
            func.max(AgentKey.last_used_at),
        )
        .where(AgentKey.workspace_id == workspace_id, AgentKey.is_revoked.is_(False))
        .group_by(AgentKey.agent_name)
        .order_by(AgentKey.agent_name.asc())
    )
    rows = (await session.execute(statement)).all()
    agents = [
        AgentSummary(agent_name=agent_name, active_key_count=active_key_count, last_used_at=last_used_at)
        for agent_name, active_key_count, last_used_at in rows
    ]
    known_names = {agent.agent_name for agent in agents}
    participant_names = set(
        (
            await session.execute(
                select(Thread.agent_a, Thread.agent_b).where(Thread.workspace_id == workspace_id)
            )
        ).all()
    )
    for agent_a, agent_b in participant_names:
        for participant in (agent_a, agent_b):
            if participant not in known_names:
                agents.append(AgentSummary(agent_name=participant, active_key_count=0, last_used_at=None))
                known_names.add(participant)

    state_names = list(
        await session.scalars(
            select(ThreadAgentState.agent_name)
            .where(ThreadAgentState.workspace_id == workspace_id)
            .distinct()
        )
    )
    for participant in state_names:
        if participant not in known_names:
            agents.append(AgentSummary(agent_name=participant, active_key_count=0, last_used_at=None))
            known_names.add(participant)

    if not any(is_human_agent_name(agent.agent_name) for agent in agents):
        agents.append(AgentSummary(agent_name=HUMAN_AGENT_NAME, active_key_count=0, last_used_at=None))
    return sorted(agents, key=lambda agent: agent.agent_name)


async def authenticate_agent_key(session: AsyncSession, presented_key: str) -> AgentIdentity | None:
    prefix = extract_agent_key_prefix(presented_key)
    if prefix is None:
        return None

    key = await session.scalar(
        select(AgentKey).where(
            AgentKey.key_prefix == prefix,
            AgentKey.is_revoked.is_(False),
        )
    )
    if key is None or not verify_agent_key(presented_key, key.key_hash):
        return None

    key.last_used_at = utcnow()
    await session.commit()
    return AgentIdentity(
        key_id=key.id,
        key_prefix=key.key_prefix,
        workspace_id=key.workspace_id,
        agent_name=key.agent_name,
    )


async def build_workspace_detail(session: AsyncSession, workspace: Workspace):
    from threadgram.schemas import WorkspaceDetail

    keys = await list_workspace_keys(session, workspace.id)
    agents = await list_agents(session, workspace.id)
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        created_at=workspace.created_at,
        human_agent_name=HUMAN_AGENT_NAME,
        agents=agents,
        keys=keys,
    )


async def participant_exists(session: AsyncSession, workspace_id: str, agent_name: str) -> bool:
    if is_human_agent_name(agent_name):
        return True

    statement = select(AgentKey.id).where(
        AgentKey.workspace_id == workspace_id,
        AgentKey.agent_name == agent_name,
        AgentKey.is_revoked.is_(False),
    )
    return await session.scalar(statement) is not None


async def authenticate_local_agent(
    session: AsyncSession,
    *,
    agent_name: str,
    workspace_slug: str,
    local_user_login: str,
    default_workspace_slug: str,
    default_workspace_name: str,
) -> AgentIdentity:
    normalized_agent_name = agent_name.strip()
    if not normalized_agent_name:
        raise ValueError("Agent identity is required.")
    if is_human_agent_name(normalized_agent_name):
        raise ValueError(f"'{HUMAN_AGENT_NAME}' is reserved for the dashboard operator.")

    local_user = await ensure_local_user(session, github_login=local_user_login)
    workspace = await get_or_create_workspace_for_slug(
        session,
        owner_user_id=local_user.id,
        slug=workspace_slug,
        default_slug=default_workspace_slug,
        default_name=default_workspace_name,
    )
    return AgentIdentity(
        key_id=f"local:{workspace.id}:{normalized_agent_name}",
        key_prefix="local",
        workspace_id=workspace.id,
        agent_name=normalized_agent_name,
    )


def thread_includes_agent(thread: Thread, agent_name: str) -> bool:
    return thread.agent_a == agent_name or thread.agent_b == agent_name


def thread_counterpart(thread: Thread, agent_name: str) -> str:
    return thread.agent_b if thread.agent_a == agent_name else thread.agent_a


async def get_or_create_thread_state(
    session: AsyncSession,
    *,
    thread_id: str,
    workspace_id: str,
    agent_name: str,
) -> ThreadAgentState:
    statement = select(ThreadAgentState).where(
        ThreadAgentState.thread_id == thread_id,
        ThreadAgentState.agent_name == agent_name,
    )
    state = await session.scalar(statement)
    if state is None:
        state = ThreadAgentState(
            id=str(uuid4()),
            thread_id=thread_id,
            workspace_id=workspace_id,
            agent_name=agent_name,
        )
        session.add(state)
        await session.flush()
    return state


async def create_thread(
    session: AsyncSession,
    *,
    workspace_id: str,
    sender_agent_name: str,
    recipient_agent_name: str,
    subject: str | None,
) -> Thread:
    ordered = sorted([sender_agent_name, recipient_agent_name])
    thread = Thread(
        id=str(uuid4()),
        workspace_id=workspace_id,
        subject=subject.strip() if subject else None,
        agent_a=ordered[0],
        agent_b=ordered[1],
        created_by_agent_name=sender_agent_name,
    )
    session.add(thread)
    await session.flush()
    return thread


async def get_thread_for_agent_model(
    session: AsyncSession,
    *,
    workspace_id: str,
    agent_name: str,
    thread_id: str,
) -> Thread | None:
    statement = (
        select(Thread)
        .where(Thread.id == thread_id, Thread.workspace_id == workspace_id)
        .options(selectinload(Thread.last_message))
    )
    thread = await session.scalar(statement)
    if thread is None or not thread_includes_agent(thread, agent_name):
        return None
    return thread


async def send_message(
    session: AsyncSession,
    *,
    identity: AgentIdentity,
    to_agent: str,
    body: str,
    thread_id: str | None = None,
    subject: str | None = None,
    allow_unknown_recipients: bool = False,
) -> SendMessageResult:
    recipient = to_agent.strip()
    if recipient == identity.agent_name:
        raise ValueError("Agents cannot send messages to themselves in the MVP.")
    if not allow_unknown_recipients and not await participant_exists(session, identity.workspace_id, recipient):
        raise ValueError(f"Unknown recipient participant '{recipient}'.")

    thread: Thread | None = None
    if thread_id:
        thread = await get_thread_for_agent_model(
            session,
            workspace_id=identity.workspace_id,
            agent_name=identity.agent_name,
            thread_id=thread_id,
        )
        if thread is None:
            raise ValueError("Thread not found.")
        if not thread_includes_agent(thread, recipient):
            raise ValueError("The selected thread does not belong to the requested recipient.")
    else:
        thread = await create_thread(
            session,
            workspace_id=identity.workspace_id,
            sender_agent_name=identity.agent_name,
            recipient_agent_name=recipient,
            subject=subject,
        )

    message = Message(
        thread_id=thread.id,
        workspace_id=identity.workspace_id,
        sender_agent_name=identity.agent_name,
        recipient_agent_name=recipient,
        body=body.strip(),
    )
    session.add(message)
    await session.flush()

    thread.last_message_id = message.id
    thread.last_message_at = message.created_at

    sender_state = await get_or_create_thread_state(
        session,
        thread_id=thread.id,
        workspace_id=identity.workspace_id,
        agent_name=identity.agent_name,
    )
    sender_state.last_read_message_id = message.id
    sender_state.last_read_at = message.created_at

    await get_or_create_thread_state(
        session,
        thread_id=thread.id,
        workspace_id=identity.workspace_id,
        agent_name=recipient,
    )

    await session.commit()
    return SendMessageResult(
        thread_id=thread.id,
        message=MessageOut(
            id=message.id,
            sender_agent_name=message.sender_agent_name,
            recipient_agent_name=message.recipient_agent_name,
            body=message.body,
            created_at=message.created_at,
        ),
    )


async def count_unread_messages(
    session: AsyncSession,
    *,
    thread: Thread,
    agent_name: str,
    state: ThreadAgentState | None,
) -> int:
    statement: Select[tuple[int]] = select(func.count(Message.id)).where(
        Message.thread_id == thread.id,
        Message.sender_agent_name != agent_name,
    )
    if state and state.last_read_message_id:
        statement = statement.where(Message.id > state.last_read_message_id)
    return int(await session.scalar(statement) or 0)


async def build_thread_summary(
    session: AsyncSession,
    *,
    thread: Thread,
    agent_name: str,
) -> ThreadSummary:
    state = await session.scalar(
        select(ThreadAgentState).where(
            ThreadAgentState.thread_id == thread.id,
            ThreadAgentState.agent_name == agent_name,
        )
    )

    last_message = thread.last_message
    if last_message is None and thread.last_message_id is not None:
        last_message = await session.scalar(select(Message).where(Message.id == thread.last_message_id))

    unread_count = await count_unread_messages(session, thread=thread, agent_name=agent_name, state=state)
    counterpart = thread_counterpart(thread, agent_name)
    return ThreadSummary(
        thread_id=thread.id,
        workspace_id=thread.workspace_id,
        subject=thread.subject,
        participants=[thread.agent_a, thread.agent_b],
        counterpart=counterpart,
        last_message_id=last_message.id if last_message else None,
        last_message_at=last_message.created_at if last_message else thread.last_message_at,
        last_message_preview=(last_message.body[:140] if last_message else None),
        last_message_sender=(last_message.sender_agent_name if last_message else None),
        unread_count=unread_count,
    )


async def fetch_inbox(
    session: AsyncSession,
    *,
    identity: AgentIdentity,
    unread_only: bool = True,
    limit: int = 20,
) -> InboxResponse:
    statement = (
        select(Thread)
        .where(
            Thread.workspace_id == identity.workspace_id,
            or_(Thread.agent_a == identity.agent_name, Thread.agent_b == identity.agent_name),
        )
        .options(selectinload(Thread.last_message))
        .order_by(Thread.last_message_at.desc().nullslast(), Thread.created_at.desc())
    )
    threads = list(await session.scalars(statement))

    summaries: list[ThreadSummary] = []
    for thread in threads:
        summary = await build_thread_summary(session, thread=thread, agent_name=identity.agent_name)
        if unread_only and summary.unread_count == 0:
            continue
        summaries.append(summary)
        if len(summaries) >= limit:
            break

    return InboxResponse(threads=summaries)


async def get_thread(
    session: AsyncSession,
    *,
    identity: AgentIdentity,
    thread_id: str,
    limit: int = 50,
) -> ThreadDetail:
    thread = await get_thread_for_agent_model(
        session,
        workspace_id=identity.workspace_id,
        agent_name=identity.agent_name,
        thread_id=thread_id,
    )
    if thread is None:
        raise ValueError("Thread not found.")

    summary = await build_thread_summary(session, thread=thread, agent_name=identity.agent_name)
    messages_statement = (
        select(Message)
        .where(Message.thread_id == thread.id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    messages = list(await session.scalars(messages_statement))
    messages.reverse()

    return ThreadDetail(
        **summary.model_dump(),
        messages=[
            MessageOut(
                id=message.id,
                sender_agent_name=message.sender_agent_name,
                recipient_agent_name=message.recipient_agent_name,
                body=message.body,
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


async def mark_thread_read(
    session: AsyncSession,
    *,
    identity: AgentIdentity,
    thread_id: str,
) -> MarkThreadReadResult:
    thread = await get_thread_for_agent_model(
        session,
        workspace_id=identity.workspace_id,
        agent_name=identity.agent_name,
        thread_id=thread_id,
    )
    if thread is None:
        raise ValueError("Thread not found.")

    state = await get_or_create_thread_state(
        session,
        thread_id=thread.id,
        workspace_id=identity.workspace_id,
        agent_name=identity.agent_name,
    )
    state.last_read_message_id = thread.last_message_id
    state.last_read_at = utcnow()
    await session.commit()
    return MarkThreadReadResult(
        thread_id=thread.id,
        last_read_message_id=thread.last_message_id,
        read_at=state.last_read_at,
    )


async def list_workspace_threads_for_owner(
    session: AsyncSession,
    *,
    workspace_id: str,
    limit: int = 50,
) -> list[ThreadSummary]:
    statement = (
        select(Thread)
        .where(Thread.workspace_id == workspace_id)
        .options(selectinload(Thread.last_message))
        .order_by(Thread.last_message_at.desc().nullslast(), Thread.created_at.desc())
        .limit(limit)
    )
    threads = list(await session.scalars(statement))
    return [await build_owner_thread_summary(session, thread=thread) for thread in threads]


async def get_workspace_thread_for_owner(
    session: AsyncSession,
    *,
    workspace_id: str,
    thread_id: str,
    limit: int = 50,
) -> ThreadDetail | None:
    thread = await session.scalar(
        select(Thread)
        .where(Thread.id == thread_id, Thread.workspace_id == workspace_id)
        .options(selectinload(Thread.last_message))
    )
    if thread is None:
        return None

    summary = await build_owner_thread_summary(session, thread=thread)

    messages = list(
        await session.scalars(
            select(Message).where(Message.thread_id == thread.id).order_by(Message.id.desc()).limit(limit)
        )
    )
    messages.reverse()
    return ThreadDetail(
        **summary.model_dump(),
        messages=[
            MessageOut(
                id=message.id,
                sender_agent_name=message.sender_agent_name,
                recipient_agent_name=message.recipient_agent_name,
                body=message.body,
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


async def build_owner_thread_summary(
    session: AsyncSession,
    *,
    thread: Thread,
) -> ThreadSummary:
    if thread_includes_agent(thread, HUMAN_AGENT_NAME):
        summary = await build_thread_summary(session, thread=thread, agent_name=HUMAN_AGENT_NAME)
        return summary.model_copy(
            update={
                "human_participant": True,
                "human_reply_target": summary.counterpart,
            }
        )

    last_message = thread.last_message
    if last_message is None and thread.last_message_id is not None:
        last_message = await session.scalar(select(Message).where(Message.id == thread.last_message_id))

    return ThreadSummary(
        thread_id=thread.id,
        workspace_id=thread.workspace_id,
        subject=thread.subject,
        participants=[thread.agent_a, thread.agent_b],
        counterpart=f"{thread.agent_a} <-> {thread.agent_b}",
        human_participant=False,
        human_reply_target=None,
        last_message_id=last_message.id if last_message else None,
        last_message_at=last_message.created_at if last_message else thread.last_message_at,
        last_message_preview=(last_message.body[:140] if last_message else None),
        last_message_sender=(last_message.sender_agent_name if last_message else None),
        unread_count=0,
    )


def trim_threads(threads: Iterable[ThreadSummary], limit: int) -> list[ThreadSummary]:
    return list(threads)[:limit]
