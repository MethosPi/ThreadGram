"""initial schema

Revision ID: 20260411_0001
Revises:
Create Date: 2026-04-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260411_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("github_user_id", sa.String(length=64), nullable=False),
        sa.Column("github_login", sa.String(length=255), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_login"),
        sa.UniqueConstraint("github_user_id"),
    )
    op.create_index(op.f("ix_users_github_login"), "users", ["github_login"], unique=False)
    op.create_index(op.f("ix_users_github_user_id"), "users", ["github_user_id"], unique=False)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "slug", name="uq_workspaces_owner_slug"),
    )
    op.create_index(op.f("ix_workspaces_owner_user_id"), "workspaces", ["owner_user_id"], unique=False)

    op.create_table(
        "agent_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_prefix"),
    )
    op.create_index(op.f("ix_agent_keys_agent_name"), "agent_keys", ["agent_name"], unique=False)
    op.create_index(op.f("ix_agent_keys_key_prefix"), "agent_keys", ["key_prefix"], unique=False)
    op.create_index(op.f("ix_agent_keys_workspace_id"), "agent_keys", ["workspace_id"], unique=False)

    op.create_table(
        "threads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("agent_a", sa.String(length=255), nullable=False),
        sa.Column("agent_b", sa.String(length=255), nullable=False),
        sa.Column("created_by_agent_name", sa.String(length=255), nullable=False),
        sa.Column("last_message_id", sa.Integer(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_threads_agent_a"), "threads", ["agent_a"], unique=False)
    op.create_index(op.f("ix_threads_agent_b"), "threads", ["agent_b"], unique=False)
    op.create_index(op.f("ix_threads_workspace_id"), "threads", ["workspace_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("sender_agent_name", sa.String(length=255), nullable=False),
        sa.Column("recipient_agent_name", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_recipient_agent_name"), "messages", ["recipient_agent_name"], unique=False)
    op.create_index(op.f("ix_messages_sender_agent_name"), "messages", ["sender_agent_name"], unique=False)
    op.create_index(op.f("ix_messages_thread_id"), "messages", ["thread_id"], unique=False)
    op.create_index(op.f("ix_messages_workspace_id"), "messages", ["workspace_id"], unique=False)

    op.create_foreign_key("fk_threads_last_message_id", "threads", "messages", ["last_message_id"], ["id"])

    op.create_table(
        "thread_agent_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("last_read_message_id", sa.Integer(), nullable=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["last_read_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "agent_name", name="uq_thread_agent_state"),
    )
    op.create_index(op.f("ix_thread_agent_states_agent_name"), "thread_agent_states", ["agent_name"], unique=False)
    op.create_index(op.f("ix_thread_agent_states_thread_id"), "thread_agent_states", ["thread_id"], unique=False)
    op.create_index(op.f("ix_thread_agent_states_workspace_id"), "thread_agent_states", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_thread_agent_states_workspace_id"), table_name="thread_agent_states")
    op.drop_index(op.f("ix_thread_agent_states_thread_id"), table_name="thread_agent_states")
    op.drop_index(op.f("ix_thread_agent_states_agent_name"), table_name="thread_agent_states")
    op.drop_table("thread_agent_states")

    op.drop_constraint("fk_threads_last_message_id", "threads", type_="foreignkey")

    op.drop_index(op.f("ix_messages_workspace_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_thread_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_sender_agent_name"), table_name="messages")
    op.drop_index(op.f("ix_messages_recipient_agent_name"), table_name="messages")
    op.drop_table("messages")

    op.drop_index(op.f("ix_threads_workspace_id"), table_name="threads")
    op.drop_index(op.f("ix_threads_agent_b"), table_name="threads")
    op.drop_index(op.f("ix_threads_agent_a"), table_name="threads")
    op.drop_table("threads")

    op.drop_index(op.f("ix_agent_keys_workspace_id"), table_name="agent_keys")
    op.drop_index(op.f("ix_agent_keys_key_prefix"), table_name="agent_keys")
    op.drop_index(op.f("ix_agent_keys_agent_name"), table_name="agent_keys")
    op.drop_table("agent_keys")

    op.drop_index(op.f("ix_workspaces_owner_user_id"), table_name="workspaces")
    op.drop_table("workspaces")

    op.drop_index(op.f("ix_users_github_user_id"), table_name="users")
    op.drop_index(op.f("ix_users_github_login"), table_name="users")
    op.drop_table("users")
