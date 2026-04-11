from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    github_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    github_login: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    workspaces: Mapped[list["Workspace"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("owner_user_id", "slug", name="uq_workspaces_owner_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    owner: Mapped["User"] = relationship(back_populates="workspaces")
    agent_keys: Mapped[list["AgentKey"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    threads: Mapped[list["Thread"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class AgentKey(Base):
    __tablename__ = "agent_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    agent_name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    key_prefix: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="agent_keys")


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_a: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_b: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_by_agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="threads")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        foreign_keys="Message.thread_id",
    )
    last_message: Mapped["Message | None"] = relationship(foreign_keys=[last_message_id], post_update=True)
    states: Mapped[list["ThreadAgentState"]] = relationship(back_populates="thread", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    sender_agent_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recipient_agent_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    thread: Mapped["Thread"] = relationship(back_populates="messages", foreign_keys=[thread_id])


class ThreadAgentState(Base):
    __tablename__ = "thread_agent_states"
    __table_args__ = (UniqueConstraint("thread_id", "agent_name", name="uq_thread_agent_state"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    last_read_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    thread: Mapped["Thread"] = relationship(back_populates="states")
