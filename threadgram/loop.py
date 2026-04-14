from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from threadgram.client import ThreadGramAPIError, ThreadGramBackendClient
from threadgram.schemas import ThreadDetail, WhoAmIOut

DEFAULT_REPLY_GUIDANCE = (
    "Reply helpfully and concisely. Use the thread context plus the local working directory if needed. "
    "Return only the message body you want to send back through ThreadGram."
)


class ReplyRunner(Protocol):
    async def generate_reply(self, *, prompt: str) -> str: ...


@dataclass
class CommandReplyRunner:
    runner: str
    cwd: str | None = None

    async def generate_reply(self, *, prompt: str) -> str:
        if self.runner == "claude":
            return await self._run_claude(prompt)
        if self.runner == "codex":
            return await self._run_codex(prompt)
        raise ValueError(f"Unsupported runner '{self.runner}'.")

    async def _run_claude(self, prompt: str) -> str:
        process = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            "--dangerously-skip-permissions",
            "--permission-mode",
            "bypassPermissions",
            prompt,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "Claude runner failed.")
        return stdout.decode("utf-8", errors="replace")

    async def _run_codex(self, prompt: str) -> str:
        with tempfile.NamedTemporaryFile(prefix="threadgram-codex-", suffix=".txt", delete=False) as output_file:
            output_path = output_file.name

        try:
            process = await asyncio.create_subprocess_exec(
                "codex",
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-o",
                output_path,
                prompt,
                cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "Codex runner failed.")

            reply = Path(output_path).read_text(encoding="utf-8").strip()
            if reply:
                return reply
            return stdout.decode("utf-8", errors="replace")
        finally:
            try:
                os.unlink(output_path)
            except FileNotFoundError:
                pass


def build_reply_prompt(
    *,
    identity: WhoAmIOut,
    thread: ThreadDetail,
    reply_guidance: str | None = None,
) -> str:
    transcript = "\n".join(
        f"[{message.created_at.isoformat()}] {message.sender_agent_name} -> {message.recipient_agent_name}: {message.body}"
        for message in thread.messages
    )
    guidance = reply_guidance.strip() if reply_guidance else DEFAULT_REPLY_GUIDANCE
    subject = thread.subject or "(no subject)"
    return (
        f"You are {identity.agent_name}, a ThreadGram participant in workspace {identity.workspace_id}.\n"
        f"Thread subject: {subject}\n"
        f"Counterpart: {thread.counterpart}\n"
        f"Participants: {', '.join(thread.participants)}\n"
        f"Unread messages in this thread: {thread.unread_count}\n\n"
        f"Instructions:\n{guidance}\n\n"
        f"Conversation so far:\n{transcript}\n\n"
        "Write only the next message body to send back through ThreadGram. Do not include markdown fences or extra commentary."
    )


def normalize_reply_text(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = "\n".join(cleaned.splitlines()[1:-1]).strip()
    return cleaned


async def run_reply_pass(
    *,
    backend: ThreadGramBackendClient,
    runner: ReplyRunner,
    reply_guidance: str | None = None,
    inbox_limit: int = 20,
    max_threads_per_pass: int = 5,
    thread_limit: int = 100,
) -> list[str]:
    identity = await backend.whoami_model()
    inbox = await backend.fetch_inbox(unread_only=True, limit=inbox_limit)

    handled_threads: list[str] = []
    for thread_summary in inbox.threads[:max_threads_per_pass]:
        thread = await backend.get_thread(thread_id=thread_summary.thread_id, limit=thread_limit)
        prompt = build_reply_prompt(identity=identity, thread=thread, reply_guidance=reply_guidance)
        reply = normalize_reply_text(await runner.generate_reply(prompt=prompt))
        if not reply:
            continue
        await backend.send_message(
            to_agent=thread.counterpart,
            body=reply,
            thread_id=thread.thread_id,
        )
        await backend.mark_thread_read(thread_id=thread.thread_id)
        handled_threads.append(thread.thread_id)
    return handled_threads


async def run_auto_reply_loop(
    *,
    server_url: str,
    api_key: str | None,
    agent_name: str | None,
    workspace: str | None,
    runner_name: str,
    poll_interval: float,
    wait_mode: Literal["auto", "wait", "poll"] = "auto",
    wait_timeout: float = 300.0,
    reply_guidance: str | None = None,
    inbox_limit: int = 20,
    max_threads_per_pass: int = 5,
    thread_limit: int = 100,
    once: bool = False,
    cwd: str | None = None,
) -> None:
    runner = CommandReplyRunner(runner=runner_name, cwd=cwd)
    backend = ThreadGramBackendClient(
        server_url=server_url,
        api_key=api_key,
        agent_name=agent_name,
        workspace=workspace,
    )
    try:
        use_wait_api = wait_mode in {"auto", "wait"}
        while True:
            handled = await run_reply_pass(
                backend=backend,
                runner=runner,
                reply_guidance=reply_guidance,
                inbox_limit=inbox_limit,
                max_threads_per_pass=max_threads_per_pass,
                thread_limit=thread_limit,
            )
            if handled:
                print(f"Handled {len(handled)} thread(s): {', '.join(handled)}")
            elif once or not use_wait_api:
                print("No unread ThreadGram threads.")
            if once:
                return
            if use_wait_api:
                try:
                    await backend.wait_for_inbox(timeout_seconds=wait_timeout)
                    continue
                except ThreadGramAPIError as exc:
                    if wait_mode == "auto" and exc.status_code in {404, 405, 501}:
                        use_wait_api = False
                        print("Inbox wait API unavailable; falling back to polling.")
                    else:
                        raise
            await asyncio.sleep(poll_interval)
    finally:
        await backend.aclose()
