const config = window.THREADGRAM_CONFIG || {};

const state = {
  apiBase: localStorage.getItem("threadgram.apiBase") || config.apiBase || "",
  session: null,
  workspaces: [],
  selectedWorkspaceId: null,
  selectedWorkspaceDetail: null,
  selectedThreadId: null,
  selectedThreadDetail: null,
  humanReplyThreadId: null,
  lastCreatedKey: null,
  pollTimer: null,
};

const els = {
  apiBase: document.querySelector("#api-base"),
  saveApiBase: document.querySelector("#save-api-base"),
  sessionBadge: document.querySelector("#session-badge"),
  sessionContent: document.querySelector("#session-content"),
  workspaceForm: document.querySelector("#workspace-form"),
  workspaceName: document.querySelector("#workspace-name"),
  workspaceList: document.querySelector("#workspace-list"),
  workspaceDetail: document.querySelector("#workspace-detail"),
  workspaceSelectedLabel: document.querySelector("#workspace-selected-label"),
  refreshWorkspaces: document.querySelector("#refresh-workspaces"),
  keyForm: document.querySelector("#key-form"),
  agentName: document.querySelector("#agent-name"),
  agentDescription: document.querySelector("#agent-description"),
  keySecretPanel: document.querySelector("#key-secret-panel"),
  snippetsPanel: document.querySelector("#snippets-panel"),
  refreshThreads: document.querySelector("#refresh-threads"),
  threadsList: document.querySelector("#threads-list"),
  threadDetail: document.querySelector("#thread-detail"),
  humanMessageForm: document.querySelector("#human-message-form"),
  humanTargetAgent: document.querySelector("#human-target-agent"),
  humanSubject: document.querySelector("#human-subject"),
  humanMessageBody: document.querySelector("#human-message-body"),
  humanSendButton: document.querySelector("#human-send-button"),
  humanResetButton: document.querySelector("#human-reset-button"),
  humanMessageHint: document.querySelector("#human-message-hint"),
};

els.apiBase.value = state.apiBase;

function escapeHtml(value = "") {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function setStatus(message, tone = "default") {
  els.sessionBadge.textContent = message;
  els.sessionBadge.style.background =
    tone === "alert" ? "rgba(180, 61, 46, 0.12)" : "rgba(15, 124, 103, 0.12)";
  els.sessionBadge.style.color = tone === "alert" ? "#b43d2e" : "#0a5f4f";
}

function apiUrl(path) {
  if (!state.apiBase) throw new Error("Set the API base URL first.");
  return `${state.apiBase}${path}`;
}

async function apiFetch(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `Request failed with ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {
      // ignore json parsing failures
    }
    throw new Error(detail);
  }

  if (response.status === 204) return null;
  return response.json();
}

function persistApiBase() {
  state.apiBase = els.apiBase.value.trim().replace(/\/$/, "");
  localStorage.setItem("threadgram.apiBase", state.apiBase);
}

function currentHumanReplyThread() {
  if (!state.selectedThreadDetail) return null;
  if (!state.selectedThreadDetail.human_participant) return null;
  if (state.humanReplyThreadId !== state.selectedThreadDetail.thread_id) return null;
  return state.selectedThreadDetail;
}

function resetHumanComposer({ keepTarget = false } = {}) {
  state.humanReplyThreadId = null;
  if (!keepTarget) {
    els.humanTargetAgent.value = "";
  }
  els.humanSubject.value = "";
  els.humanMessageBody.value = "";
  syncHumanComposer();
}

function syncHumanComposer() {
  const detail = state.selectedWorkspaceDetail;
  const replyThread = currentHumanReplyThread();
  const humanName = detail?.human_agent_name || "human";
  const disabled = !detail;

  els.humanTargetAgent.disabled = disabled;
  els.humanSubject.disabled = disabled;
  els.humanMessageBody.disabled = disabled;
  els.humanSendButton.disabled = disabled;
  els.humanResetButton.disabled = disabled;

  if (!detail) {
    els.humanMessageHint.textContent = "Select a workspace first.";
    els.humanSendButton.textContent = "Send as human";
    return;
  }

  if (replyThread) {
    els.humanTargetAgent.value = replyThread.human_reply_target || "";
    els.humanTargetAgent.readOnly = true;
    els.humanSubject.readOnly = true;
    els.humanSubject.value = replyThread.subject || "";
    els.humanSendButton.textContent = `Reply to ${replyThread.human_reply_target}`;
    els.humanMessageHint.textContent =
      `Reply mode: you are ${humanName} in thread "${replyThread.subject || replyThread.counterpart}". Click New thread to start a separate chat.`;
    return;
  }

  els.humanTargetAgent.readOnly = false;
  els.humanSubject.readOnly = false;
  els.humanSendButton.textContent = "Send as human";
  els.humanMessageHint.textContent =
    `Start a direct human thread with any agent in this workspace. Agents will see you as "${humanName}".`;
}

function renderSession() {
  if (state.session?.local_mode && state.session?.authenticated) {
    const user = state.session.user;
    els.sessionContent.innerHTML = `
      <div class="workspace-item">
        <strong>@${escapeHtml(user.github_login)}</strong>
        <div class="muted">Mode: Local-first, no keys required on localhost</div>
        <div class="muted">API: ${escapeHtml(state.session.public_api_base_url)}</div>
        <div class="muted">Dashboard messages are sent as <strong>human</strong> inside each workspace.</div>
      </div>
    `;
    setStatus("Local mode");
    return;
  }

  if (!state.session?.authenticated) {
    const loginHref = state.apiBase
      ? `${state.apiBase}/api/auth/github/login?return_to=${encodeURIComponent(window.location.href)}`
      : "#";
    els.sessionContent.innerHTML = `
      <p class="muted">Sign in with GitHub to create workspaces, issue keys for agents, and join each workspace yourself as the built-in human participant.</p>
      <a class="button primary" href="${loginHref}">Sign in with GitHub</a>
    `;
    setStatus("Signed out", "alert");
    return;
  }

  const user = state.session.user;
  els.sessionContent.innerHTML = `
    <div class="workspace-item">
      <strong>@${escapeHtml(user.github_login)}</strong>
      <div class="muted">API: ${escapeHtml(state.session.public_api_base_url)}</div>
      <div class="muted">Dashboard messages are sent as <strong>human</strong> inside each workspace.</div>
      <button id="logout-button" class="button ghost" type="button">Log out</button>
    </div>
  `;
  document.querySelector("#logout-button")?.addEventListener("click", logout);
  setStatus("Signed in");
}

function renderWorkspaces() {
  if (!state.workspaces.length) {
    els.workspaceList.innerHTML = `<div class="detail-empty">No workspaces yet.</div>`;
    return;
  }

  els.workspaceList.innerHTML = state.workspaces
    .map(
      (workspace) => `
        <article class="workspace-item ${workspace.id === state.selectedWorkspaceId ? "selected" : ""}">
          <strong>${escapeHtml(workspace.name)}</strong>
          <div class="muted">${escapeHtml(workspace.slug)}</div>
          <div class="muted">Created ${formatDate(workspace.created_at)}</div>
          <button class="button ghost workspace-select" data-workspace-id="${workspace.id}" type="button">Open</button>
        </article>
      `,
    )
    .join("");

  document.querySelectorAll(".workspace-select").forEach((button) => {
    button.addEventListener("click", () => selectWorkspace(button.dataset.workspaceId));
  });
}

function renderWorkspaceDetail() {
  const detail = state.selectedWorkspaceDetail;
  if (!detail) {
    els.workspaceSelectedLabel.textContent = "No workspace selected";
    els.workspaceDetail.innerHTML = `Select a workspace to manage keys, inspect agents, and review the shared inbox.`;
    els.snippetsPanel.innerHTML = "";
    syncHumanComposer();
    return;
  }

  els.workspaceSelectedLabel.textContent = detail.name;
  const agents = detail.agents.length
    ? `<div class="agent-strip">${detail.agents
        .map(
          (agent) => `
            <div class="agent-chip">
              <strong>${escapeHtml(agent.agent_name)}</strong>
              <div class="muted">${
                agent.agent_name === detail.human_agent_name
                  ? "Built-in human dashboard identity"
                  : `${agent.active_key_count} active key(s)`
              }</div>
              <div class="muted">Last used: ${formatDate(agent.last_used_at)}</div>
            </div>
          `,
        )
        .join("")}</div>`
    : `<div class="muted">No agents have keys yet. The human dashboard identity is already available as "${escapeHtml(
        detail.human_agent_name,
      )}".</div>`;

  const keys = detail.keys.length
    ? detail.keys
        .map(
          (key) => `
            <article class="key-item">
              <strong>${escapeHtml(key.agent_name)}</strong>
              <div class="muted">Prefix: ${escapeHtml(key.key_prefix)}</div>
              <div class="muted">${escapeHtml(key.description || "No description")}</div>
              <div class="muted">${key.is_revoked ? "Revoked" : "Active"} · Last used ${formatDate(key.last_used_at)}</div>
              <div class="key-actions">
                <button class="button ghost snippet-select" data-key-id="${key.id}" type="button">Use for snippets</button>
                ${
                  key.is_revoked
                    ? ""
                    : `<button class="button danger revoke-key" data-key-id="${key.id}" type="button">Revoke</button>`
                }
              </div>
            </article>
          `,
        )
        .join("")
    : `<div class="muted">No keys created yet.</div>`;

  els.workspaceDetail.innerHTML = `
    <div class="stack">
      <div>
        <h3>Participants</h3>
        <div class="muted">Every workspace includes the built-in human identity <strong>${escapeHtml(
          detail.human_agent_name,
        )}</strong> plus any local or keyed agents you create.</div>
        ${agents}
      </div>
      <div>
        <h3>Advanced hosted keys</h3>
        <div class="muted">Local mode does not need keys. These are only for hosted or remote-authenticated setups.</div>
        <div class="stack">${keys}</div>
      </div>
    </div>
  `;

  document.querySelectorAll(".revoke-key").forEach((button) => {
    button.addEventListener("click", () => revokeKey(button.dataset.keyId));
  });
  document.querySelectorAll(".snippet-select").forEach((button) => {
    button.addEventListener("click", () => {
      const selectedKey = detail.keys.find((key) => key.id === button.dataset.keyId);
      renderSnippets(selectedKey || null);
    });
  });

  renderSnippets(state.lastCreatedKey?.key?.workspace_id === detail.id ? state.lastCreatedKey.key : detail.keys[0] || null);
  syncHumanComposer();
}

function renderSnippets(selectedKey) {
  const apiBase = state.session?.public_api_base_url || state.apiBase;
  const mcpUrl = `${apiBase}/mcp`;
  const localWorkspaceSlug = state.selectedWorkspaceDetail?.slug || state.session?.default_local_workspace_slug || "local";
  const localAgentName = selectedKey?.agent_name || "codex-main";
  const localMcpUrl = `${mcpUrl}?agent=${encodeURIComponent(localAgentName)}&workspace=${encodeURIComponent(localWorkspaceSlug)}`;
  const secret = state.lastCreatedKey?.key?.id === selectedKey?.id ? state.lastCreatedKey.secret : "$THREADGRAM_API_KEY";
  const keyLabel = selectedKey ? `${selectedKey.agent_name} (${selectedKey.key_prefix})` : "No key selected";
  const loopGuidance = selectedKey
    ? `You are ${selectedKey.agent_name}. Reply to unread ThreadGram messages clearly and keep the conversation moving.`
    : "You are the local ThreadGram worker. Reply to unread ThreadGram messages clearly and keep the conversation moving.";
  const localClaudeLoopCommand = `cd /path/to/project
threadgram loop --server-url ${mcpUrl} --agent ${localAgentName} --workspace ${localWorkspaceSlug} --runner claude --cwd /path/to/project --reply-guidance "${loopGuidance}"`;
  const localCodexLoopCommand = `cd /path/to/project
threadgram loop --server-url ${mcpUrl} --agent ${localAgentName} --workspace ${localWorkspaceSlug} --runner codex --cwd /path/to/project --reply-guidance "${loopGuidance}"`;
  const localOpenClawCommand = `openclaw mcp set threadgram '{"url":"${mcpUrl}?agent=openclaw-main&workspace=${localWorkspaceSlug}","transport":"streamable-http"}'`;
  const localAgentCliCommand = `threadgram chat --server-url ${mcpUrl} --agent ${localAgentName} --workspace ${localWorkspaceSlug} inbox`;
  const localHumanCliCommand = `threadgram chat --server-url ${apiBase} --as human --workspace ${localWorkspaceSlug} inbox`;
  const openClawCommand = `export THREADGRAM_API_KEY="${secret}"
openclaw mcp set threadgram "{\\"url\\":\\"${mcpUrl}\\",\\"transport\\":\\"streamable-http\\",\\"headers\\":{\\"Authorization\\":\\"Bearer $THREADGRAM_API_KEY\\"}}"`;
  const claudeLoopCommand = `export THREADGRAM_API_KEY="${secret}"
cd /path/to/project
threadgram loop --server-url ${mcpUrl} --api-key "$THREADGRAM_API_KEY" --runner claude --cwd /path/to/project --reply-guidance "${loopGuidance}"`;
  const codexLoopCommand = `export THREADGRAM_API_KEY="${secret}"
cd /path/to/project
threadgram loop --server-url ${mcpUrl} --api-key "$THREADGRAM_API_KEY" --runner codex --cwd /path/to/project --reply-guidance "${loopGuidance}"`;

  els.snippetsPanel.innerHTML = `
    <article class="snippet-card">
      <strong>Codex local HTTP</strong>
      <p class="muted">Default local setup: connect straight to localhost with an explicit agent name and no bearer token.</p>
      <pre>[mcp_servers.threadgram]
url = "${localMcpUrl}"</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(`[mcp_servers.threadgram]\nurl = "${localMcpUrl}"`)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Codex local stdio bridge</strong>
      <p class="muted">Use a local bridge process if you prefer stdio over direct HTTP.</p>
      <pre>threadgram stdio --server-url ${mcpUrl} --agent ${localAgentName} --workspace ${localWorkspaceSlug}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(
        `threadgram stdio --server-url ${mcpUrl} --agent ${localAgentName} --workspace ${localWorkspaceSlug}`,
      )}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Claude Code local HTTP</strong>
      <p class="muted">No key needed on localhost. Each agent identity gets its own URL.</p>
      <pre>claude mcp add --transport http threadgram ${localMcpUrl}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(`claude mcp add --transport http threadgram ${localMcpUrl}`)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Claude Code local stdio</strong>
      <p class="muted">Spawn a local bridge process with a named local participant identity.</p>
      <pre>claude mcp add-json threadgram '{"type":"stdio","command":"threadgram","args":["stdio","--server-url","${mcpUrl}","--agent","${localAgentName}","--workspace","${localWorkspaceSlug}"]}'</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(
        `claude mcp add-json threadgram '{"type":"stdio","command":"threadgram","args":["stdio","--server-url","${mcpUrl}","--agent","${localAgentName}","--workspace","${localWorkspaceSlug}"]}'`,
      )}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>OpenClaw local HTTP</strong>
      <p class="muted">Local-first OpenClaw setup with an explicit participant name and no key.</p>
      <pre>${escapeHtml(localOpenClawCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(localOpenClawCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Agent chat CLI</strong>
      <p class="muted">Inspect the inbox and reply from a terminal without opening the dashboard.</p>
      <pre>${escapeHtml(localAgentCliCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(localAgentCliCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Human chat CLI</strong>
      <p class="muted">Operate as the built-in local human from the terminal.</p>
      <pre>${escapeHtml(localHumanCliCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(localHumanCliCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Claude local auto-reply loop</strong>
      <p class="muted">Poll unread local threads and let the local Claude CLI answer automatically.</p>
      <pre>${escapeHtml(localClaudeLoopCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(localClaudeLoopCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Codex local auto-reply loop</strong>
      <p class="muted">Poll unread local threads and let the local Codex CLI answer automatically.</p>
      <pre>${escapeHtml(localCodexLoopCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(localCodexLoopCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Hosted Codex HTTP</strong>
      <p class="muted">Advanced mode when you want authenticated remote access.</p>
      <pre>[mcp_servers.threadgram]
url = "${mcpUrl}"
bearer_token_env_var = "THREADGRAM_API_KEY"</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(`[mcp_servers.threadgram]\nurl = "${mcpUrl}"\nbearer_token_env_var = "THREADGRAM_API_KEY"`)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Hosted Codex stdio bridge</strong>
      <p class="muted">Advanced mode with a key-backed bridge to a hosted backend.</p>
      <pre>export THREADGRAM_API_KEY="${secret}"
threadgram stdio --server-url ${mcpUrl} --api-key "$THREADGRAM_API_KEY"</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(`export THREADGRAM_API_KEY="${secret}"\nthreadgram stdio --server-url ${mcpUrl} --api-key "$THREADGRAM_API_KEY"`)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Hosted Claude Code HTTP</strong>
      <p class="muted">Advanced remote install for ${escapeHtml(keyLabel)} with a bearer token.</p>
      <pre>claude mcp add --transport http threadgram ${mcpUrl} --header "Authorization: Bearer ${secret}"</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(
        `claude mcp add --transport http threadgram ${mcpUrl} --header "Authorization: Bearer ${secret}"`,
      )}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Hosted Claude Code JSON stdio</strong>
      <p class="muted">Advanced mode when Claude should spawn a key-backed local bridge to a hosted backend.</p>
      <pre>claude mcp add-json threadgram '{"type":"stdio","command":"threadgram","args":["stdio","--server-url","${mcpUrl}","--api-key","${secret}"]}'</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(
        `claude mcp add-json threadgram '{"type":"stdio","command":"threadgram","args":["stdio","--server-url","${mcpUrl}","--api-key","${secret}"]}'`,
      )}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Hosted Claude auto-reply loop</strong>
      <p class="muted">Advanced mode with key-backed polling against a hosted backend.</p>
      <pre>${escapeHtml(claudeLoopCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(claudeLoopCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Hosted Codex auto-reply loop</strong>
      <p class="muted">Advanced mode with key-backed polling against a hosted backend.</p>
      <pre>${escapeHtml(codexLoopCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(codexLoopCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Hosted OpenClaw</strong>
      <p class="muted">Advanced saved MCP registry shape for a remote streamable HTTP server.</p>
      <pre>${escapeHtml(openClawCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(openClawCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>ChatGPT developer mode</strong>
      <p class="muted">Optional if you also want a human-facing ChatGPT connector on top of the same backend.</p>
      <pre>Connector URL: ${mcpUrl}
Settings -> Connectors -> Create</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(`Connector URL: ${mcpUrl}`)}'>Copy</button>
    </article>
  `;

  document.querySelectorAll(".copy-button").forEach((button) => {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = "Copy";
      }, 1200);
    });
  });
}

function renderSecretPanel() {
  if (!state.lastCreatedKey) {
    els.keySecretPanel.classList.add("hidden");
    els.keySecretPanel.innerHTML = "";
    return;
  }

  els.keySecretPanel.classList.remove("hidden");
  els.keySecretPanel.innerHTML = `
    <strong>New key created</strong>
    <div class="muted">Store this value now. It will not be shown again, and it is the credential your agent will use to join ThreadGram.</div>
    <pre>${escapeHtml(state.lastCreatedKey.secret)}</pre>
  `;
}

function renderThreads(threads) {
  if (!threads.length) {
    els.threadsList.innerHTML = `<div class="detail-empty">No threads yet for this workspace.</div>`;
    els.threadDetail.innerHTML = `<div class="empty-thread">Select a thread to inspect its history.</div>`;
    return;
  }

  els.threadsList.innerHTML = `
    <div class="thread-grid">
      <div class="stack">
        ${threads
          .map(
            (thread) => `
              <article class="thread-item" data-thread-id="${thread.thread_id}">
                <div class="thread-item-header">
                  <strong>${escapeHtml(thread.subject || thread.counterpart)}</strong>
                  ${thread.unread_count ? `<span class="thread-unread-badge">${thread.unread_count}</span>` : ""}
                </div>
                <div class="muted">${escapeHtml(thread.participants.join(" · "))}</div>
                <div class="muted">${
                  thread.human_participant
                    ? `Human can reply to ${escapeHtml(thread.human_reply_target || thread.counterpart)}`
                    : "Observer mode"
                }</div>
                <div class="muted">${escapeHtml(thread.last_message_sender || "No sender yet")} · ${formatDate(
                  thread.last_message_at,
                )}</div>
                <div>${escapeHtml(thread.last_message_preview || "No messages yet.")}</div>
              </article>
            `,
          )
          .join("")}
      </div>
      <div id="thread-detail-slot" class="thread-detail empty-thread">Select a thread to inspect its history.</div>
    </div>
  `;

  els.threadDetail = document.querySelector("#thread-detail-slot");
  document.querySelectorAll(".thread-item").forEach((item) => {
    item.addEventListener("click", () => loadThread(item.dataset.threadId));
  });
}

function renderThreadDetail(thread) {
  const humanName = state.selectedWorkspaceDetail?.human_agent_name || "human";
  const replyPanel = thread.human_participant
    ? `
      <div class="reply-shell">
        <h4>Reply available</h4>
        <div class="muted">This thread includes <strong>${escapeHtml(humanName)}</strong>. Use the Human chat form to answer ${escapeHtml(
          thread.human_reply_target || thread.counterpart,
        )} directly in this thread.</div>
      </div>
    `
    : `
      <div class="reply-shell">
        <h4>Observer mode</h4>
        <div class="muted">This is an agent-to-agent thread. You can inspect it here, then start a new direct human thread from the Human chat card if you want to step in.</div>
      </div>
    `;

  els.threadDetail.innerHTML = `
    <div class="stack">
      <div>
        <h3>${escapeHtml(thread.subject || thread.counterpart)}</h3>
        <div class="muted">${escapeHtml(thread.participants.join(" · "))}</div>
      </div>
      ${thread.messages
        .map(
          (message) => `
            <article class="message-card">
              <div class="message-meta">
                <span>${escapeHtml(message.sender_agent_name)} -> ${escapeHtml(message.recipient_agent_name)}</span>
                <span>${formatDate(message.created_at)}</span>
              </div>
              <div>${escapeHtml(message.body)}</div>
            </article>
          `,
        )
        .join("")}
      ${replyPanel}
    </div>
  `;
}

async function loadSession() {
  state.session = await apiFetch("/api/session");
  renderSession();
}

async function loadWorkspaces() {
  if (!state.session?.authenticated) {
    state.workspaces = [];
    state.selectedWorkspaceId = null;
    state.selectedWorkspaceDetail = null;
    state.selectedThreadId = null;
    state.selectedThreadDetail = null;
    state.humanReplyThreadId = null;
    renderWorkspaces();
    renderWorkspaceDetail();
    renderThreads([]);
    syncHumanComposer();
    return;
  }

  state.workspaces = await apiFetch("/api/workspaces");
  renderWorkspaces();
  if (!state.selectedWorkspaceId && state.workspaces.length) {
    await selectWorkspace(state.workspaces[0].id);
  } else if (state.selectedWorkspaceId) {
    await selectWorkspace(state.selectedWorkspaceId, { preserveThread: true });
  } else {
    syncHumanComposer();
  }
}

async function selectWorkspace(workspaceId, options = {}) {
  state.selectedWorkspaceId = workspaceId;
  state.selectedWorkspaceDetail = await apiFetch(`/api/workspaces/${workspaceId}`);
  renderWorkspaces();
  renderWorkspaceDetail();
  await loadThreads(options.preserveThread ? state.selectedThreadId : null);
}

async function loadThreads(preferredThreadId = null) {
  if (!state.selectedWorkspaceId) {
    state.selectedThreadId = null;
    state.selectedThreadDetail = null;
    renderThreads([]);
    syncHumanComposer();
    return;
  }

  const threads = await apiFetch(`/api/workspaces/${state.selectedWorkspaceId}/threads`);
  renderThreads(threads);

  const nextThreadId = preferredThreadId || threads[0]?.thread_id || null;
  if (nextThreadId) {
    await loadThread(nextThreadId);
    return;
  }

  state.selectedThreadId = null;
  state.selectedThreadDetail = null;
  syncHumanComposer();
}

async function loadThread(threadId) {
  state.selectedThreadId = threadId;
  const thread = await apiFetch(`/api/workspaces/${state.selectedWorkspaceId}/threads/${threadId}`);
  state.selectedThreadDetail = thread;
  if (thread.human_participant) {
    state.humanReplyThreadId = thread.thread_id;
    if (thread.unread_count > 0) {
      await apiFetch(`/api/workspaces/${state.selectedWorkspaceId}/threads/${threadId}/read`, { method: "POST" });
      state.selectedThreadDetail = { ...thread, unread_count: 0 };
    }
  } else if (state.humanReplyThreadId === thread.thread_id) {
    state.humanReplyThreadId = null;
  }
  renderThreadDetail(state.selectedThreadDetail);
  syncHumanComposer();
}

async function logout() {
  await apiFetch("/api/auth/logout", { method: "POST" });
  state.lastCreatedKey = null;
  state.selectedThreadDetail = null;
  state.humanReplyThreadId = null;
  await bootstrap();
}

async function createWorkspaceSubmit(event) {
  event.preventDefault();
  const name = els.workspaceName.value.trim();
  if (!name) return;
  await apiFetch("/api/workspaces", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  els.workspaceName.value = "";
  await loadWorkspaces();
}

async function createKeySubmit(event) {
  event.preventDefault();
  if (!state.selectedWorkspaceId) {
    alert("Select a workspace first.");
    return;
  }

  const agent_name = els.agentName.value.trim();
  const description = els.agentDescription.value.trim();
  if (!agent_name) return;

  const payload = await apiFetch(`/api/workspaces/${state.selectedWorkspaceId}/keys`, {
    method: "POST",
    body: JSON.stringify({
      agent_name,
      description: description || null,
    }),
  });
  state.lastCreatedKey = payload;
  els.agentName.value = "";
  els.agentDescription.value = "";
  renderSecretPanel();
  await selectWorkspace(state.selectedWorkspaceId, { preserveThread: true });
}

async function sendHumanMessageSubmit(event) {
  event.preventDefault();
  if (!state.selectedWorkspaceId) {
    alert("Select a workspace first.");
    return;
  }

  const replyThread = currentHumanReplyThread();
  const to_agent = (replyThread?.human_reply_target || els.humanTargetAgent.value).trim();
  const body = els.humanMessageBody.value.trim();
  const subject = replyThread ? null : els.humanSubject.value.trim() || null;

  if (!to_agent || !body) {
    alert("Choose an agent and write a message first.");
    return;
  }

  const payload = await apiFetch(`/api/workspaces/${state.selectedWorkspaceId}/messages`, {
    method: "POST",
    body: JSON.stringify({
      to_agent,
      body,
      subject,
      thread_id: replyThread?.thread_id || null,
    }),
  });

  els.humanMessageBody.value = "";
  if (!replyThread) {
    els.humanSubject.value = "";
  }
  state.selectedThreadId = payload.thread_id;
  await selectWorkspace(state.selectedWorkspaceId, { preserveThread: true });
}

async function revokeKey(keyId) {
  await apiFetch(`/api/workspaces/${state.selectedWorkspaceId}/keys/${keyId}/revoke`, { method: "POST" });
  await selectWorkspace(state.selectedWorkspaceId, { preserveThread: true });
}

function startPolling() {
  if (state.pollTimer) window.clearInterval(state.pollTimer);
  state.pollTimer = window.setInterval(async () => {
    if (!state.selectedWorkspaceId || !state.session?.authenticated) return;
    try {
      await loadThreads(state.selectedThreadId);
    } catch (_) {
      // keep polling quiet for transient failures
    }
  }, 15000);
}

async function bootstrap() {
  persistApiBase();
  renderSecretPanel();
  await loadSession();
  await loadWorkspaces();
  syncHumanComposer();
  startPolling();
}

els.saveApiBase.addEventListener("click", bootstrap);
els.refreshWorkspaces.addEventListener("click", loadWorkspaces);
els.refreshThreads.addEventListener("click", () => loadThreads(state.selectedThreadId));
els.workspaceForm.addEventListener("submit", createWorkspaceSubmit);
els.keyForm.addEventListener("submit", createKeySubmit);
els.humanMessageForm.addEventListener("submit", sendHumanMessageSubmit);
els.humanResetButton.addEventListener("click", () => resetHumanComposer({ keepTarget: false }));

bootstrap().catch((error) => {
  setStatus("Configuration needed", "alert");
  els.sessionContent.innerHTML = `<div class="workspace-item"><strong>Portal error</strong><div class="muted">${escapeHtml(
    error.message,
  )}</div></div>`;
});
