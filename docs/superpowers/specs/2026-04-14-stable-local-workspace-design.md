# Stable local workspace for human CLI

## Context

The human-mode CLI (`threadgram chat --as human`) creates a new workspace every invocation. After 11 uses a freshly installed ThreadGram had 11 workspaces: `local-control-room`, `local-control-room-2`, …, `local-control-room-11`. Users lose track of where messages actually live, and even explicitly passing `--workspace local` creates *another* orphan room. This breaks the "one local hub" mental model the README promises.

### Root cause

`_resolve_workspace` in `threadgram/client.py:269` targets slug `"local"` (from server settings `local_workspace_slug`). When no workspace with that slug exists, it calls `POST /api/workspaces` with **only a name** (`"Local Control Room"`). The server's `create_workspace` (in `threadgram/services/core.py:129`) slugifies the name → `"local-control-room"`, not `"local"`. Next invocation: target slug `"local"` still missing → creates yet another `local-control-room-N`.

## Goal

Make workspace resolution **idempotent** for the human CLI so repeated invocations converge on a single workspace with the expected slug. Clean up existing orphans left by the bug without losing the real Codex conversation.

## Design

### Server — accept optional explicit slug

- `threadgram/schemas.py` — extend `WorkspaceCreate` with `slug: str | None = None`.
- `threadgram/api/router.py:136` `create_workspace_endpoint` — when the payload contains `slug`, delegate to the existing `get_or_create_workspace_for_slug` helper (`threadgram/services/core.py:158`) which is already idempotent. When `slug` is omitted (dashboard "Create workspace" flow), keep the current `create_workspace` behavior that slugifies the name and appends `-N` on collision.

### Client — always pass the desired slug

- `threadgram/client.py:261` — `_create_workspace` accepts an optional `slug` and forwards it in the POST body.
- `threadgram/client.py:282` — pass `target_slug` (already computed on line 274) when creating. This guarantees the created workspace has the slug the client will look up on the next run.

### Cleanup (one-shot)

Executed once after the fix, via `docker compose exec db psql`:
1. Find the workspace that currently holds the Codex↔human thread (`local-control-room-2` with workspace id `46077f2a-…`). Update its slug to `"local"` (and optionally its name to `"Local Control Room"` for consistency). Uniqueness is enforced per `(owner_user_id, slug)` so this is safe because no other workspace currently has slug `"local"`.
2. Delete the remaining 10 orphan workspaces (`local-control-room`, `local-control-room-3` … `-11`). All of them have zero threads and zero messages — confirmed by `SELECT COUNT(*) FROM threads/messages WHERE workspace_id = …`. Cascade on `threads`/`messages`/`thread_agent_states`/`agent_keys` makes deletion safe either way.

No production data loss: the only real message thread is preserved and moved to the canonical slug.

### Tests

Add a focused test in `tests/test_api.py`:
- `POST /api/workspaces {"name":"Local Control Room","slug":"local"}` → 201 with slug `"local"`
- `POST /api/workspaces {"name":"Local Control Room","slug":"local"}` again → same workspace `id`, no new row
- `POST /api/workspaces {"name":"Other"}` (no slug) → keeps legacy behavior, slug derived from name

## Files touched

- `threadgram/schemas.py`
- `threadgram/api/router.py`
- `threadgram/client.py`
- `tests/test_api.py`
- (one-shot SQL in the terminal, not committed)

## Verification

1. `docker compose up -d` + dashboard on :4173
2. `SELECT count(*) FROM workspaces;` → 1 after cleanup
3. Run `threadgram chat --as human agents` three times in a row → DB count stays at 1
4. `threadgram chat --as human --workspace local inbox` shows the preserved Codex thread
5. `pytest tests/test_api.py -k workspace` passes
