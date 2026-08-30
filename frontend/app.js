"use strict";

const AUTO_REFRESH_KEY = "agent-monitor:auto-refresh";
const POLL_INTERVAL_MS = 30000;

const elements = {
  connectionPill: document.querySelector("#connection-pill"),
  connectionLabel: document.querySelector("#connection-label"),
  lastRefresh: document.querySelector("#last-refresh"),
  refreshButton: document.querySelector("#refresh-button"),
  autoRefresh: document.querySelector("#auto-refresh"),
  activeCount: document.querySelector("#active-count"),
  longestElapsed: document.querySelector("#longest-elapsed"),
  recentCount: document.querySelector("#recent-count"),
  activeList: document.querySelector("#active-list"),
  activeLoading: document.querySelector("#active-loading"),
  activeEmpty: document.querySelector("#active-empty"),
  recentList: document.querySelector("#recent-list"),
  recentLoading: document.querySelector("#recent-loading"),
  recentEmpty: document.querySelector("#recent-empty"),
  detailDialog: document.querySelector("#session-dialog"),
  detailClose: document.querySelector("#detail-close"),
  detailKicker: document.querySelector("#detail-kicker"),
  detailTitle: document.querySelector("#detail-title"),
  detailDescription: document.querySelector("#detail-description"),
  detailContent: document.querySelector("#detail-content"),
};

const storedPreference = localStorage.getItem(AUTO_REFRESH_KEY);
const state = {
  snapshot: null,
  inFlight: null,
  controller: null,
  timer: null,
  autoRefresh: storedPreference !== "false",
  selectedDetail: null,
  detailTrigger: null,
  restoreDetailFocus: true,
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function formatDuration(value) {
  if (!Number.isFinite(value) || value < 0) return "—";
  const total = Math.floor(value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function formatAge(value) {
  if (!Number.isFinite(value) || value < 0) return "unknown";
  if (value < 5) return "now";
  if (value < 60) return `${Math.floor(value)}s ago`;
  if (value < 3600) return `${Math.floor(value / 60)}m ago`;
  if (value < 86400) return `${Math.floor(value / 3600)}h ago`;
  return `${Math.floor(value / 86400)}d ago`;
}

function ageFromTimestamp(timestamp) {
  if (!timestamp) return null;
  const milliseconds = Date.parse(timestamp);
  if (!Number.isFinite(milliseconds)) return null;
  return Math.max(0, (Date.now() - milliseconds) / 1000);
}

function timestampNode(value) {
  if (!value) return node("span", "detail-missing", "—");
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return node("span", "detail-missing", "—");
  const time = node("time", "detail-time", date.toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "medium",
  }));
  time.dateTime = date.toISOString();
  return time;
}

function providerInfo(provider) {
  if (provider === "hermes") {
    return { key: "hermes", label: "Hermes", live: "Active turn", mode: "Agent turn" };
  }
  return { key: "codex", label: "Codex", live: "Live process", mode: "Default effort" };
}

function detailKey(kind, item) {
  return { kind, id: String(item.id || "unknown") };
}

function isSelected(kind, item) {
  return Boolean(
    state.selectedDetail
    && state.selectedDetail.kind === kind
    && state.selectedDetail.id === String(item.id || "unknown")
  );
}

function setConnection(status, label) {
  elements.connectionPill.dataset.state = status;
  elements.connectionLabel.textContent = label;
}

function setBusy(busy) {
  elements.refreshButton.disabled = busy;
  elements.refreshButton.setAttribute("aria-busy", String(busy));
  const firstLoad = busy && !state.snapshot;
  elements.activeList.setAttribute("aria-busy", String(firstLoad));
  elements.recentList.setAttribute("aria-busy", String(firstLoad));
}

function setAutoRefresh(enabled, persist = true) {
  state.autoRefresh = enabled;
  elements.autoRefresh.setAttribute("aria-checked", String(enabled));
  if (persist) localStorage.setItem(AUTO_REFRESH_KEY, String(enabled));
  if (!enabled && state.timer) {
    window.clearTimeout(state.timer);
    state.timer = null;
  }
}

function activityDescription(item) {
  const fragment = document.createDocumentFragment();
  if (item.type === "message") {
    fragment.append(node("span", "", item.text || "Progress update"));
    return fragment;
  }
  if (item.type === "command") {
    fragment.append(node("strong", "", item.label || "command"));
    const result = item.result || item.status;
    if (result) {
      fragment.append(node("span", `result-tag ${result === "failed" ? "failed" : ""}`, result));
    }
    return fragment;
  }
  const count = Number.isFinite(item.count) ? item.count : 0;
  fragment.append(node("strong", "", `${count} file${count === 1 ? "" : "s"}`));
  if (Array.isArray(item.files) && item.files.length) {
    fragment.append(document.createTextNode(` · ${item.files.join(", ")}`));
  }
  return fragment;
}

function renderActivity(activity) {
  const list = node("ol", "activity-list");
  const items = Array.isArray(activity) ? activity.slice(-8).reverse() : [];
  if (!items.length) {
    const empty = node("li", "activity-item");
    empty.dataset.kind = "empty";
    empty.append(
      node("span", "activity-dot"),
      node("span", "activity-copy", "No safe projected activity yet"),
    );
    list.append(empty);
    return list;
  }
  for (const item of items) {
    const row = node("li", "activity-item");
    row.dataset.kind = item.type || "unknown";
    row.dataset.status = item.status || "";
    row.dataset.result = item.result || "";
    const copy = node("span", "activity-copy");
    copy.append(activityDescription(item));
    const age = item.at ? formatAge(Math.max(0, (Date.now() / 1000) - item.at)) : "";
    row.append(node("span", "activity-dot"), copy, node("time", "activity-time", age));
    list.append(row);
  }
  return list;
}

function cardContext(kind, item) {
  if (kind === "running") return item.latest_summary || "Waiting for projected activity";
  const provider = providerInfo(item.provider);
  return `${item.model || "Unknown model"} · ${item.reasoning_effort || provider.mode}`;
}

function cardMetrics(kind, item) {
  if (kind === "running") {
    return [
      `Elapsed ${formatDuration(item.elapsed_seconds)}`,
      `Updated ${formatAge(item.last_activity_age_seconds)}`,
    ];
  }
  return [`Updated ${formatAge(ageFromTimestamp(item.updated_at))}`];
}

function renderCard(kind, item) {
  const row = node("article", "kanban-item");
  row.setAttribute("role", "listitem");
  const provider = providerInfo(item.provider);
  row.dataset.provider = provider.key;
  row.dataset.state = kind;

  const button = node("button", "kanban-card");
  button.type = "button";
  button.dataset.sessionId = String(item.id || "unknown");
  button.dataset.sessionKind = kind;

  const status = node("span", "card-status");
  status.append(
    node("span", "status-dot"),
    node("span", `provider-badge provider-${provider.key}`, provider.label),
    node("span", "state-label", kind === "running" ? provider.live : "Recent session"),
  );

  const title = node("span", "card-title", item.title || "Untitled session");
  const project = node("span", "card-project", item.project_name || "Unknown project");
  const context = node("span", "card-context", cardContext(kind, item));
  const footer = node("span", "card-footer");
  const metrics = node("span", "card-metrics");
  for (const metric of cardMetrics(kind, item)) metrics.append(node("span", "", metric));
  footer.append(metrics, node("span", "card-affordance", "View details"));
  button.append(status, title, project, context, footer);

  button.addEventListener("click", () => openDetail(kind, item, button));
  if (isSelected(kind, item)) state.detailTrigger = button;
  row.append(button);
  return row;
}

function detailFact(label, value, options = {}) {
  const wrapper = node("div", "detail-fact");
  const term = node("dt", "detail-label", label);
  const description = node("dd", options.mono ? "detail-value detail-mono" : "detail-value");
  if (options.timestamp) {
    description.append(timestampNode(value));
  } else {
    description.textContent = value === undefined || value === null || value === "" ? "—" : String(value);
  }
  wrapper.append(term, description);
  return wrapper;
}

function renderDetail(kind, item) {
  const provider = providerInfo(item.provider);
  const status = kind === "running" ? provider.live : "Recent session";
  elements.detailDialog.dataset.provider = provider.key;
  elements.detailKicker.textContent = `${provider.label} · ${status}`;
  elements.detailTitle.textContent = item.title || "Untitled session";
  elements.detailDescription.textContent = kind === "running"
    ? (item.latest_summary || "Waiting for projected activity")
    : cardContext(kind, item);

  const facts = node("dl", "detail-facts");
  facts.append(
    detailFact("Status", status),
    detailFact("Provider", provider.label),
    detailFact("Project", item.project_name || "Unknown project"),
  );

  if (kind === "running") {
    facts.append(
      detailFact("Elapsed", formatDuration(item.elapsed_seconds), { mono: true }),
      detailFact("Last activity", formatAge(item.last_activity_age_seconds), { mono: true }),
    );
  } else {
    facts.append(detailFact("Updated age", formatAge(ageFromTimestamp(item.updated_at)), { mono: true }));
  }

  facts.append(
    detailFact("Model", item.model || "Unknown model", { mono: true }),
    detailFact(item.provider === "hermes" ? "Mode" : "Reasoning effort", item.reasoning_effort || provider.mode, { mono: true }),
    detailFact("Branch", item.branch || "No branch", { mono: true }),
    detailFact("Working directory", item.cwd || "Unknown cwd", { mono: true }),
    detailFact("Session ID", item.id || "Unknown", { mono: true }),
  );

  if (kind === "running") {
    facts.append(
      detailFact("PID", item.pid, { mono: true }),
      detailFact("Started", item.started_at, { timestamp: true }),
      detailFact("Updated", item.updated_at, { timestamp: true }),
    );
  } else {
    facts.append(
      detailFact("Created", item.created_at, { timestamp: true }),
      detailFact("Updated", item.updated_at, { timestamp: true }),
    );
  }

  const content = document.createDocumentFragment();
  content.append(facts);
  if (kind === "running") {
    const activitySection = node("section", "detail-activity");
    const activityHeading = node("div", "detail-section-heading");
    activityHeading.append(
      node("h3", "", "Recent safe activity"),
      node("span", "", "Newest first · max 8"),
    );
    activitySection.append(activityHeading, renderActivity(item.activity));
    content.append(activitySection);
  }
  elements.detailContent.replaceChildren(content);
}

function openDetail(kind, item, trigger) {
  state.selectedDetail = detailKey(kind, item);
  state.detailTrigger = trigger;
  state.restoreDetailFocus = true;
  renderDetail(kind, item);
  elements.detailDialog.showModal();
}

function closeDetail() {
  if (elements.detailDialog.open) elements.detailDialog.close();
}

function findSelectedItem(threads, recent) {
  if (!state.selectedDetail) return null;
  const collection = state.selectedDetail.kind === "running" ? threads : recent;
  return collection.find((item) => String(item.id || "unknown") === state.selectedDetail.id) || null;
}

function refreshSelectedDetail(threads, recent) {
  if (!state.selectedDetail || !elements.detailDialog.open) return;
  const latest = findSelectedItem(threads, recent);
  if (latest) {
    renderDetail(state.selectedDetail.kind, latest);
    return;
  }
  state.restoreDetailFocus = false;
  closeDetail();
}

function renderRecent(items) {
  const fragment = document.createDocumentFragment();
  for (const item of items.slice(0, 8)) fragment.append(renderCard("recent", item));
  elements.recentList.replaceChildren(fragment);
  elements.recentEmpty.hidden = items.length > 0;
}

function render(snapshot) {
  const threads = Array.isArray(snapshot.running_threads) ? snapshot.running_threads : [];
  const recent = Array.isArray(snapshot.recent_completions) ? snapshot.recent_completions.slice(0, 8) : [];
  elements.activeCount.textContent = String(Number.isFinite(snapshot.running_count) ? snapshot.running_count : threads.length);
  const elapsedValues = threads.map((thread) => thread.elapsed_seconds).filter(Number.isFinite);
  elements.longestElapsed.textContent = elapsedValues.length ? formatDuration(Math.max(...elapsedValues)) : "—";
  elements.recentCount.textContent = String(Number.isFinite(snapshot.recent_count) ? snapshot.recent_count : recent.length);

  if (state.selectedDetail) state.detailTrigger = null;
  const fragment = document.createDocumentFragment();
  for (const thread of threads) fragment.append(renderCard("running", thread));
  elements.activeList.replaceChildren(fragment);
  elements.activeLoading.hidden = true;
  elements.activeEmpty.hidden = threads.length > 0;
  elements.recentLoading.hidden = true;
  renderRecent(recent);
  refreshSelectedDetail(threads, recent);
}

async function loadSnapshot() {
  if (state.inFlight) return state.inFlight;
  state.controller = new AbortController();
  setBusy(true);
  if (!state.snapshot) setConnection("connecting", "Connecting");

  const request = (async () => {
    try {
      const response = await fetch("/api/snapshot", {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: state.controller.signal,
      });
      if (!response.ok) throw new Error(`Snapshot request failed: ${response.status}`);
      const snapshot = await response.json();
      state.snapshot = snapshot;
      render(snapshot);
      const refreshed = new Date();
      elements.lastRefresh.dateTime = refreshed.toISOString();
      elements.lastRefresh.textContent = refreshed.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      setConnection("connected", "Live");
      return snapshot;
    } catch (error) {
      if (error && error.name === "AbortError") return state.snapshot;
      setConnection(state.snapshot ? "stale" : "disconnected", state.snapshot ? "Stale data" : "Disconnected");
      if (!state.snapshot) {
        elements.activeLoading.querySelector("p").textContent = "Live threads are unavailable. Use Refresh to try again.";
        elements.recentLoading.querySelector("p").textContent = "Recent sessions are unavailable. Use Refresh to try again.";
      }
      return state.snapshot;
    } finally {
      setBusy(false);
    }
  })();

  state.inFlight = request;
  try {
    return await request;
  } finally {
    if (state.inFlight === request) state.inFlight = null;
  }
}

function scheduleNext() {
  if (state.timer) window.clearTimeout(state.timer);
  state.timer = null;
  if (!state.autoRefresh || document.hidden) return;
  state.timer = window.setTimeout(async () => {
    await loadSnapshot();
    scheduleNext();
  }, POLL_INTERVAL_MS);
}

elements.detailClose.addEventListener("click", closeDetail);

elements.detailDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeDetail();
});

elements.detailDialog.addEventListener("click", (event) => {
  if (event.target === elements.detailDialog) closeDetail();
});

elements.detailDialog.addEventListener("close", () => {
  const trigger = state.detailTrigger;
  const restoreFocus = state.restoreDetailFocus;
  state.selectedDetail = null;
  state.detailTrigger = null;
  state.restoreDetailFocus = true;
  if (restoreFocus && trigger && trigger.isConnected) trigger.focus();
});

elements.refreshButton.addEventListener("click", async () => {
  await loadSnapshot();
  scheduleNext();
});

elements.autoRefresh.addEventListener("click", () => {
  setAutoRefresh(!state.autoRefresh);
  scheduleNext();
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (state.timer) window.clearTimeout(state.timer);
    state.timer = null;
    return;
  }
  loadSnapshot().finally(scheduleNext);
});

window.addEventListener("beforeunload", () => {
  if (state.controller) state.controller.abort();
});

setAutoRefresh(state.autoRefresh, false);
loadSnapshot().finally(scheduleNext);
