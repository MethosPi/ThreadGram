from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import TextIO

import httpx
import uvicorn

from threadgram.app import create_app
from threadgram.bridge import create_stdio_bridge
from threadgram.client import ThreadGramAPIError, ThreadGramBackendClient, ThreadGramHumanLocalClient, ConversationClient
from threadgram.loop import run_auto_reply_loop
from threadgram.schemas import AgentsResponse, InboxResponse, ThreadDetail

SleepFunc = Callable[[float], Awaitable[None]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="threadgram")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the ThreadGram HTTP API and MCP server.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)

    stdio = subparsers.add_parser("stdio", help="Run the local stdio bridge that forwards to a ThreadGram API.")
    stdio.add_argument("--server-url", required=True, help="Hosted ThreadGram MCP endpoint, for example https://api.example.com/mcp")
    stdio.add_argument("--api-key", help="ThreadGram bearer token. Falls back to THREADGRAM_API_KEY.")
    stdio.add_argument("--agent", help="Local-mode participant name, for example codex-main.")
    stdio.add_argument("--workspace", help="Local-mode workspace slug. Defaults to the server's local workspace slug.")

    loop = subparsers.add_parser("loop", help="Poll ThreadGram and auto-reply to unread threads with a local Claude or Codex CLI.")
    loop.add_argument("--server-url", required=True, help="Hosted ThreadGram MCP endpoint, for example https://api.example.com/mcp")
    loop.add_argument("--api-key", help="ThreadGram bearer token. Falls back to THREADGRAM_API_KEY.")
    loop.add_argument("--agent", help="Local-mode participant name, for example claude-reviewer.")
    loop.add_argument("--workspace", help="Local-mode workspace slug. Defaults to the server's local workspace slug.")
    loop.add_argument("--runner", choices=["claude", "codex"], required=True, help="Local agent CLI to use for generating replies.")
    loop.add_argument("--poll-interval", default=15.0, type=float, help="Seconds between inbox polls.")
    loop.add_argument("--reply-guidance", help="Extra instructions for how the local agent should answer unread threads.")
    loop.add_argument("--inbox-limit", default=20, type=int, help="Unread thread batch size to fetch each pass.")
    loop.add_argument("--max-threads-per-pass", default=5, type=int, help="Maximum unread threads to process per poll.")
    loop.add_argument("--thread-limit", default=100, type=int, help="How many recent messages to include from each thread.")
    loop.add_argument("--once", action="store_true", help="Run a single poll-and-reply pass, then exit.")
    loop.add_argument("--cwd", help="Working directory to give the local Claude or Codex runner for context.")

    chat = subparsers.add_parser("chat", help="Read and send ThreadGram messages directly from the terminal.")
    chat.add_argument(
        "--server-url",
        required=True,
        help="ThreadGram API base URL or MCP endpoint, for example http://localhost:8000 or http://localhost:8000/mcp",
    )
    chat.add_argument(
        "--as",
        dest="chat_actor",
        choices=["agent", "human"],
        default="agent",
        help="Run the chat CLI as an agent or as the local human operator.",
    )
    chat.add_argument("--api-key", help="ThreadGram bearer token. Falls back to THREADGRAM_API_KEY in agent mode.")
    chat.add_argument("--agent", help="Local-mode participant name in agent mode, for example codex-main.")
    chat.add_argument("--workspace", help="Workspace slug. In human mode this selects the local workspace to open.")

    chat_subparsers = chat.add_subparsers(dest="chat_command", required=True)

    whoami = chat_subparsers.add_parser("whoami", help="Show the current chat identity.")
    whoami.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable JSON.")

    agents = chat_subparsers.add_parser("agents", help="List known participants in the workspace.")
    agents.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable JSON.")

    inbox = chat_subparsers.add_parser("inbox", help="List threads in the current inbox.")
    inbox.add_argument("--limit", default=20, type=int, help="Maximum number of threads to show.")
    inbox.add_argument("--all", action="store_true", help="Include read threads.")
    inbox.add_argument(
        "--all-threads",
        action="store_true",
        help="In human mode, include agent-only threads as well.",
    )
    inbox.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable JSON.")

    thread = chat_subparsers.add_parser("thread", help="Show messages from a thread.")
    thread.add_argument("thread_id", help="Thread identifier.")
    thread.add_argument("--limit", default=50, type=int, help="How many recent messages to include.")
    thread.add_argument("--mark-read", action="store_true", help="Mark the thread as read after printing it.")
    thread.add_argument(
        "--all-threads",
        action="store_true",
        help="In human mode, allow inspection of agent-only threads.",
    )
    thread.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable JSON.")

    send = chat_subparsers.add_parser("send", help="Send a message and optionally start a new thread.")
    send.add_argument("--to", required=True, help="Recipient participant name.")
    send.add_argument("--subject", help="Optional subject for new threads.")
    send.add_argument("--thread", dest="thread_id", help="Reply inside an existing thread.")
    send.add_argument("--body", help="Message body. If omitted, text is read from stdin.")

    reply = chat_subparsers.add_parser("reply", help="Reply to an existing thread.")
    reply.add_argument("thread_id", help="Thread identifier.")
    reply.add_argument("--body", help="Message body. If omitted, text is read from stdin.")

    mark_read = chat_subparsers.add_parser("mark-read", help="Mark a thread as read.")
    mark_read.add_argument("thread_id", help="Thread identifier.")

    watch = chat_subparsers.add_parser("watch", help="Poll the inbox and print only newly changed threads.")
    watch.add_argument("--limit", default=20, type=int, help="Maximum number of threads to inspect per poll.")
    watch.add_argument("--all", action="store_true", help="Include read threads.")
    watch.add_argument(
        "--all-threads",
        action="store_true",
        help="In human mode, include agent-only threads as well.",
    )
    watch.add_argument("--poll-interval", default=15.0, type=float, help="Seconds between inbox polls.")
    watch.add_argument("--once", action="store_true", help="Fetch once, print matching changes, then exit.")

    return parser


def resolve_agent_auth(parser: argparse.ArgumentParser, api_key: str | None, agent_name: str | None) -> tuple[str | None, str | None]:
    resolved_api_key = api_key or os.getenv("THREADGRAM_API_KEY")
    resolved_agent_name = agent_name or os.getenv("THREADGRAM_AGENT_NAME")
    if not resolved_api_key and not resolved_agent_name:
        parser.error("Use either --api-key/THREADGRAM_API_KEY for hosted mode or --agent/THREADGRAM_AGENT_NAME for local mode.")
    return resolved_api_key, resolved_agent_name


def run_stdio(server_url: str, api_key: str | None, agent_name: str | None, workspace: str | None) -> None:
    bridge = create_stdio_bridge(
        server_url=server_url,
        api_key=api_key,
        agent_name=agent_name,
        workspace=workspace,
    )
    bridge.run()


def _print_json(payload: object, stdout: TextIO) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)


def _format_timestamp(value) -> str:
    if value is None:
        return "-"
    return value.isoformat()


def _render_identity(identity: dict[str, object], stdout: TextIO) -> None:
    role = identity.get("role", "agent")
    print(f"Role: {role}", file=stdout)
    print(f"Agent: {identity.get('agent_name')}", file=stdout)
    workspace_name = identity.get("workspace_name")
    workspace_slug = identity.get("workspace_slug")
    workspace_id = identity.get("workspace_id")
    if workspace_name:
        print(f"Workspace: {workspace_name}", file=stdout)
    if workspace_slug:
        print(f"Workspace slug: {workspace_slug}", file=stdout)
    if workspace_id:
        print(f"Workspace id: {workspace_id}", file=stdout)
    key_prefix = identity.get("key_prefix")
    if key_prefix:
        print(f"Key prefix: {key_prefix}", file=stdout)


def _render_agents(payload: AgentsResponse, stdout: TextIO) -> None:
    if not payload.agents:
        print("No agents found.", file=stdout)
        return
    for agent in payload.agents:
        print(
            f"{agent.agent_name} | active_keys={agent.active_key_count} | last_used={_format_timestamp(agent.last_used_at)}",
            file=stdout,
        )


def _render_inbox(payload: InboxResponse, stdout: TextIO) -> None:
    if not payload.threads:
        print("No matching threads.", file=stdout)
        return
    for thread in payload.threads:
        subject = thread.subject or "(no subject)"
        print(
            f"{thread.thread_id} | {thread.counterpart} | unread={thread.unread_count} | {subject}",
            file=stdout,
        )
        if thread.last_message_preview:
            preview = " ".join(thread.last_message_preview.splitlines())
            sender = thread.last_message_sender or "unknown"
            print(f"  {sender}: {preview}", file=stdout)


def _render_thread(thread: ThreadDetail, stdout: TextIO) -> None:
    print(f"Thread: {thread.thread_id}", file=stdout)
    print(f"Counterpart: {thread.counterpart}", file=stdout)
    print(f"Participants: {', '.join(thread.participants)}", file=stdout)
    print(f"Subject: {thread.subject or '(no subject)'}", file=stdout)
    print(f"Unread: {thread.unread_count}", file=stdout)
    for message in thread.messages:
        print("", file=stdout)
        print(
            f"[{message.created_at.isoformat()}] {message.sender_agent_name} -> {message.recipient_agent_name}",
            file=stdout,
        )
        print(message.body, file=stdout)


def _read_message_body(body: str | None, stdin: TextIO) -> str:
    if body and body.strip():
        return body.strip()
    is_tty = getattr(stdin, "isatty", lambda: False)
    if is_tty():
        raise ThreadGramAPIError("Message body is required. Pass --body or pipe the message on stdin.")
    streamed = stdin.read().strip()
    if not streamed:
        raise ThreadGramAPIError("Message body is required. Pass --body or pipe the message on stdin.")
    return streamed


async def _build_chat_client(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> ConversationClient:
    if args.chat_actor == "human":
        if args.api_key:
            parser.error("Human chat mode does not support --api-key. Use the local dashboard for hosted mode.")
        if args.agent:
            parser.error("Human chat mode does not support --agent. The local human operator is implicit.")
        return ThreadGramHumanLocalClient(
            server_url=args.server_url,
            workspace=args.workspace,
            http_client=http_client,
        )

    api_key, agent_name = resolve_agent_auth(parser, args.api_key, args.agent)
    return ThreadGramBackendClient(
        server_url=args.server_url,
        api_key=api_key,
        agent_name=agent_name,
        workspace=args.workspace,
        http_client=http_client,
    )


async def _run_watch(
    client: ConversationClient,
    *,
    limit: int,
    unread_only: bool,
    all_threads: bool,
    poll_interval: float,
    once: bool,
    stdout: TextIO,
    sleep_func: SleepFunc,
) -> None:
    previous: dict[str, tuple[int | None, int]] = {}
    first_pass = True

    while True:
        inbox = await client.fetch_inbox(
            unread_only=unread_only,
            limit=limit,
            all_threads=all_threads,
        )
        current = {
            thread.thread_id: (thread.last_message_id, thread.unread_count)
            for thread in inbox.threads
        }
        changed_threads = [
            thread
            for thread in inbox.threads
            if previous.get(thread.thread_id) != current[thread.thread_id]
        ]

        if changed_threads:
            _render_inbox(InboxResponse(threads=changed_threads), stdout)
        elif first_pass:
            print("No matching threads.", file=stdout)

        if once:
            return

        previous = current
        first_pass = False
        await sleep_func(poll_interval)


async def run_chat_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    http_client: httpx.AsyncClient | None = None,
    sleep_func: SleepFunc = asyncio.sleep,
) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    client = await _build_chat_client(args, parser, http_client=http_client)

    try:
        if args.chat_command == "whoami":
            identity = await client.whoami()
            if args.as_json:
                _print_json(identity, stdout)
            else:
                _render_identity(identity, stdout)
            return

        if args.chat_command == "agents":
            agents = await client.list_agents()
            if args.as_json:
                _print_json(agents.model_dump(mode="json"), stdout)
            else:
                _render_agents(agents, stdout)
            return

        if args.chat_command == "inbox":
            inbox = await client.fetch_inbox(
                unread_only=not args.all,
                limit=args.limit,
                all_threads=args.all_threads,
            )
            if args.as_json:
                _print_json(inbox.model_dump(mode="json"), stdout)
            else:
                _render_inbox(inbox, stdout)
            return

        if args.chat_command == "thread":
            thread = await client.get_thread(
                thread_id=args.thread_id,
                limit=args.limit,
                all_threads=args.all_threads,
            )
            if args.as_json:
                _print_json(thread.model_dump(mode="json"), stdout)
            else:
                _render_thread(thread, stdout)
            if args.mark_read:
                result = await client.mark_thread_read(thread_id=args.thread_id)
                print(f"\nMarked read: {result.thread_id}", file=stdout)
            return

        if args.chat_command == "send":
            body = _read_message_body(args.body, stdin)
            result = await client.send_message(
                to_agent=args.to,
                body=body,
                thread_id=args.thread_id,
                subject=args.subject,
            )
            print(
                f"Sent message {result.message.id} to {result.message.recipient_agent_name} in thread {result.thread_id}.",
                file=stdout,
            )
            return

        if args.chat_command == "reply":
            thread = await client.get_thread(thread_id=args.thread_id, limit=1, all_threads=True)
            body = _read_message_body(args.body, stdin)
            result = await client.send_message(
                to_agent=thread.counterpart,
                body=body,
                thread_id=thread.thread_id,
            )
            print(
                f"Sent reply {result.message.id} to {result.message.recipient_agent_name} in thread {result.thread_id}.",
                file=stdout,
            )
            return

        if args.chat_command == "mark-read":
            result = await client.mark_thread_read(thread_id=args.thread_id)
            print(f"Marked read: {result.thread_id}", file=stdout)
            return

        if args.chat_command == "watch":
            await _run_watch(
                client,
                limit=args.limit,
                unread_only=not args.all,
                all_threads=args.all_threads,
                poll_interval=args.poll_interval,
                once=args.once,
                stdout=stdout,
                sleep_func=sleep_func,
            )
            return

        parser.error("Unknown chat command.")
    except ThreadGramAPIError as exc:
        parser.exit(2, f"threadgram: error: {exc}\n")
    finally:
        await client.aclose()


async def run_cli_async(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    http_client: httpx.AsyncClient | None = None,
    sleep_func: SleepFunc = asyncio.sleep,
) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "loop":
        api_key, agent_name = resolve_agent_auth(parser, args.api_key, args.agent)
        await run_auto_reply_loop(
            server_url=args.server_url,
            api_key=api_key,
            agent_name=agent_name,
            workspace=args.workspace,
            runner_name=args.runner,
            poll_interval=args.poll_interval,
            reply_guidance=args.reply_guidance,
            inbox_limit=args.inbox_limit,
            max_threads_per_pass=args.max_threads_per_pass,
            thread_limit=args.thread_limit,
            once=args.once,
            cwd=args.cwd,
        )
        return

    if args.command == "chat":
        await run_chat_command(
            args,
            parser,
            stdin=stdin,
            stdout=stdout,
            http_client=http_client,
            sleep_func=sleep_func,
        )
        return

    parser.error("The async CLI runner only supports 'chat' and 'loop'.")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run(create_app(), host=args.host, port=args.port)
        return

    if args.command == "stdio":
        api_key, agent_name = resolve_agent_auth(parser, args.api_key, args.agent)
        run_stdio(args.server_url, api_key, agent_name, args.workspace)
        return

    asyncio.run(run_cli_async(argv))
