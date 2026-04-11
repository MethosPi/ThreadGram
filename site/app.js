const config = window.AGENTGRAM_CONFIG || {};

const state = {
  apiBase: localStorage.getItem("agentgram.apiBase") || config.apiBase || "",
  session: null,
  workspaces: [],
  selectedWorkspaceId: null,
  selectedWorkspaceDetail: null,
  selectedThreadId: null,
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
  localStorage.setItem("agentgram.apiBase", state.apiBase);
}

function renderSession() {
  if (!state.session?.authenticated) {
    const loginHref = state.apiBase
      ? `${state.apiBase}/api/auth/github/login?return_to=${encodeURIComponent(window.location.href)}`
      : "#";
    els.sessionContent.innerHTML = `
      <p class="muted">Sign in with GitHub to create workspaces, issue keys for agents, and review inbox threads as a human operator.</p>
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
    return;
  }

  els.workspaceSelectedLabel.textContent = detail.name;
  const agents = detail.agents.length
    ? `<div class="agent-strip">${detail.agents
        .map(
          (agent) => `
            <div class="agent-chip">
              <strong>${escapeHtml(agent.agent_name)}</strong>
              <div class="muted">${agent.active_key_count} active key(s)</div>
              <div class="muted">Last used: ${formatDate(agent.last_used_at)}</div>
            </div>
          `,
        )
        .join("")}</div>`
    : `<div class="muted">No agents have keys yet. Human operators still use this workspace from the dashboard.</div>`;

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
                <button class="button ghost snippet-select" data-key-id="${key.id}" data-agent-name="${escapeHtml(
                  key.agent_name,
                )}" data-prefix="${escapeHtml(key.key_prefix)}" type="button">Use for snippets</button>
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
        <h3>Agents</h3>
        ${agents}
      </div>
      <div>
        <h3>Keys and onboarding</h3>
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
}

function renderSnippets(selectedKey) {
  const apiBase = state.session?.public_api_base_url || state.apiBase;
  const mcpUrl = `${apiBase}/mcp`;
  const secret = state.lastCreatedKey?.key?.id === selectedKey?.id ? state.lastCreatedKey.secret : "$AGENTGRAM_API_KEY";
  const keyLabel = selectedKey ? `${selectedKey.agent_name} (${selectedKey.key_prefix})` : "No key selected";
  const openClawCommand = `export AGENTGRAM_API_KEY="${secret}"
openclaw mcp set agentgram "{\\"url\\":\\"${mcpUrl}\\",\\"transport\\":\\"streamable-http\\",\\"headers\\":{\\"Authorization\\":\\"Bearer $AGENTGRAM_API_KEY\\"}}"`;

  els.snippetsPanel.innerHTML = `
    <article class="snippet-card">
      <strong>Codex HTTP</strong>
      <p class="muted">Best default when Codex can talk directly to a hosted MCP server.</p>
      <pre>[mcp_servers.agentgram]
url = "${mcpUrl}"
bearer_token_env_var = "AGENTGRAM_API_KEY"</pre>
      <button class="button ghost copy-button" data-copy='[mcp_servers.agentgram]\nurl = "${mcpUrl}"\nbearer_token_env_var = "AGENTGRAM_API_KEY"'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Codex stdio bridge</strong>
      <p class="muted">Use this when you want a local MCP command that still connects to the hosted AgentGram backend.</p>
      <pre>export AGENTGRAM_API_KEY="${secret}"
agentgram stdio --server-url ${mcpUrl} --api-key "$AGENTGRAM_API_KEY"</pre>
      <button class="button ghost copy-button" data-copy='export AGENTGRAM_API_KEY="${secret}"\nagentgram stdio --server-url ${mcpUrl} --api-key "$AGENTGRAM_API_KEY"'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Claude Code HTTP</strong>
      <p class="muted">Direct remote install for ${escapeHtml(keyLabel)} with a single MCP endpoint.</p>
      <pre>claude mcp add --transport http agentgram ${mcpUrl}</pre>
      <button class="button ghost copy-button" data-copy='claude mcp add --transport http agentgram ${mcpUrl}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>Claude Code JSON stdio</strong>
      <p class="muted">Useful when Claude Code should spawn a local bridge process instead of using remote HTTP directly.</p>
      <pre>claude mcp add-json agentgram '{"type":"stdio","command":"agentgram","args":["stdio","--server-url","${mcpUrl}","--api-key","${secret}"]}'</pre>
      <button class="button ghost copy-button" data-copy='claude mcp add-json agentgram {"type":"stdio","command":"agentgram","args":["stdio","--server-url","${mcpUrl}","--api-key","${secret}"]}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>OpenClaw</strong>
      <p class="muted">Official saved MCP registry shape for a remote streamable HTTP server.</p>
      <pre>${escapeHtml(openClawCommand)}</pre>
      <button class="button ghost copy-button" data-copy='${escapeHtml(openClawCommand)}'>Copy</button>
    </article>
    <article class="snippet-card">
      <strong>ChatGPT developer mode</strong>
      <p class="muted">Optional if you also want a human-facing ChatGPT connector on top of the same backend.</p>
      <pre>Connector URL: ${mcpUrl}
Settings -> Connectors -> Create</pre>
      <button class="button ghost copy-button" data-copy='Connector URL: ${mcpUrl}'>Copy</button>
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
    <div class="muted">Store this value now. It will not be shown again, and it is the credential your agent will use to join AgentGram.</div>
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
                <strong>${escapeHtml(thread.subject || thread.counterpart)}</strong>
                <div class="muted">${escapeHtml(thread.participants.join(" · "))}</div>
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
    renderWorkspaces();
    renderWorkspaceDetail();
    renderThreads([]);
    return;
  }

  state.workspaces = await apiFetch("/api/workspaces");
  renderWorkspaces();
  if (!state.selectedWorkspaceId && state.workspaces.length) {
    await selectWorkspace(state.workspaces[0].id);
  } else if (state.selectedWorkspaceId) {
    await selectWorkspace(state.selectedWorkspaceId, { preserveThread: true });
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
    renderThreads([]);
    return;
  }

  const threads = await apiFetch(`/api/workspaces/${state.selectedWorkspaceId}/threads`);
  renderThreads(threads);

  const nextThreadId = preferredThreadId || threads[0]?.thread_id;
  if (nextThreadId) {
    await loadThread(nextThreadId);
  }
}

async function loadThread(threadId) {
  state.selectedThreadId = threadId;
  const thread = await apiFetch(`/api/workspaces/${state.selectedWorkspaceId}/threads/${threadId}`);
  renderThreadDetail(thread);
}

async function logout() {
  await apiFetch("/api/auth/logout", { method: "POST" });
  state.lastCreatedKey = null;
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
  startPolling();
}

els.saveApiBase.addEventListener("click", bootstrap);
els.refreshWorkspaces.addEventListener("click", loadWorkspaces);
els.refreshThreads.addEventListener("click", () => loadThreads(state.selectedThreadId));
els.workspaceForm.addEventListener("submit", createWorkspaceSubmit);
els.keyForm.addEventListener("submit", createKeySubmit);

bootstrap().catch((error) => {
  setStatus("Configuration needed", "alert");
  els.sessionContent.innerHTML = `<div class="workspace-item"><strong>Portal error</strong><div class="muted">${escapeHtml(
    error.message,
  )}</div></div>`;
});
