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
};

const storedPreference = localStorage.getItem(AUTO_REFRESH_KEY);
const state = {
  snapshot: null,
  inFlight: null,
  controller: null,
  timer: null,
  autoRefresh: storedPreference !== "false",
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

function shortId(value) {
  if (typeof value !== "string") return "unknown";
  const identifier = value.split(":").at(-1) || value;
  return identifier.slice(0, 8);
}

function providerInfo(provider) {
  if (provider === "hermes") return { label: "Hermes", live: "Active turn", mode: "Agent turn" };
  return { label: "Codex", live: "Live process", mode: "Default effort" };
}

function setConnection(status, label) {
  elements.connectionPill.dataset.state = status;
  elements.connectionLabel.textContent = label;
}

function setBusy(busy) {
  elements.refreshButton.disabled = busy;
  elements.refreshButton.setAttribute("aria-busy", String(busy));
  elements.activeList.setAttribute("aria-busy", String(busy && !state.snapshot));
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

function fact(label, value) {
  const wrapper = node("div");
  wrapper.append(node("dt", "fact-label", label), node("dd", "fact-value", value));
  return wrapper;
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
    if (result) fragment.append(node("span", `result-tag ${result === "failed" ? "failed" : ""}`, result));
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
    empty.append(node("span", "activity-dot"), node("span", "activity-copy", "No safe projected activity yet"));
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

function renderThread(thread) {
  const article = node("article", "thread-row");
  article.setAttribute("aria-labelledby", `thread-${thread.id}`);

  const head = node("div", "thread-head");
  const identity = node("div");
  const provider = providerInfo(thread.provider);
  article.dataset.provider = thread.provider || "codex";
  const live = node("span", "live-label");
  live.append(
    node("span", "status-dot"),
    node("span", `provider-badge provider-${thread.provider || "codex"}`, provider.label),
    document.createTextNode(provider.live),
  );
  const heading = node("h3", "", thread.title || "Untitled session");
  heading.id = `thread-${thread.id}`;
  const project = node("div", "thread-project");
  project.append(
    node("span", "project-name", thread.project_name || "Unknown project"),
    node("span", "separator", "/"),
    node("span", "branch-name", thread.branch || "No branch"),
  );
  identity.append(live, heading, project);
  const elapsed = node("div", "elapsed-block");
  elapsed.append(node("span", "elapsed-label", "Elapsed"), node("span", "elapsed-value", formatDuration(thread.elapsed_seconds)));
  head.append(identity, elapsed);

  const body = node("div", "thread-body");
  const overview = node("div", "thread-overview");
  overview.append(node("p", "latest-label", "Latest safe summary"), node("p", "latest-summary", thread.latest_summary || "Waiting for projected activity"));
  const facts = node("dl", "thread-facts");
  facts.append(
    fact("Model", thread.model || "Unknown model"),
    fact(thread.provider === "hermes" ? "Mode" : "Effort", thread.reasoning_effort || provider.mode),
    fact("Last activity", formatAge(thread.last_activity_age_seconds)),
  );
  const footer = node("div", "thread-footer");
  footer.append(node("span", "thread-path", thread.cwd || "Unknown cwd"), node("span", "thread-id", `${shortId(thread.id)} · pid ${thread.pid}`));
  overview.append(facts, footer);

  const timeline = node("details", "timeline-panel");
  timeline.setAttribute("aria-label", "Recent safe activity");
  const isCompactViewport = window.matchMedia("(max-width: 640px)").matches;
  timeline.open = !isCompactViewport;
  const timelineTitle = node("summary", "timeline-title");
  timelineTitle.append(
    node("span", "timeline-heading", "Recent activity"),
    node("span", "timeline-order", "Newest first"),
  );
  timeline.append(timelineTitle, renderActivity(thread.activity));
  body.append(overview, timeline);
  article.append(head, body);
  return article;
}

function renderRecent(items) {
  const fragment = document.createDocumentFragment();
  const labels = ["Source", "Project", "Task", "Branch", "Model", "Last update"];
  for (const item of items.slice(0, 8)) {
    const row = node("tr");
    const updatedAge = ageFromTimestamp(item.updated_at);
    const provider = providerInfo(item.provider);
    row.dataset.provider = item.provider || "codex";
    const cells = [
      node("td", "recent-source", provider.label),
      node("td", "recent-project", item.project_name || "Unknown project"),
      node("td", "recent-task", item.title || "Untitled session"),
      node("td", "branch-name", item.branch || "No branch"),
      node("td", "", `${item.model || "Unknown"} · ${item.reasoning_effort || "default"}`),
      node("td", "recent-time", formatAge(updatedAge)),
    ];
    cells.forEach((cell, index) => {
      cell.dataset.label = labels[index];
    });
    row.append(...cells);
    fragment.append(row);
  }
  elements.recentList.replaceChildren(fragment);
  elements.recentEmpty.hidden = items.length > 0;
}

function render(snapshot) {
  const threads = Array.isArray(snapshot.running_threads) ? snapshot.running_threads : [];
  const recent = Array.isArray(snapshot.recent_completions) ? snapshot.recent_completions : [];
  elements.activeCount.textContent = String(Number.isFinite(snapshot.running_count) ? snapshot.running_count : threads.length);
  const elapsedValues = threads.map((thread) => thread.elapsed_seconds).filter(Number.isFinite);
  elements.longestElapsed.textContent = elapsedValues.length ? formatDuration(Math.max(...elapsedValues)) : "—";
  elements.recentCount.textContent = String(Number.isFinite(snapshot.recent_count) ? snapshot.recent_count : recent.length);

  const fragment = document.createDocumentFragment();
  for (const thread of threads) fragment.append(renderThread(thread));
  elements.activeList.replaceChildren(fragment);
  elements.activeLoading.hidden = true;
  elements.activeEmpty.hidden = threads.length > 0;
  elements.recentLoading.hidden = true;
  renderRecent(recent);
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
      elements.lastRefresh.textContent = refreshed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      setConnection("connected", "Live");
      return snapshot;
    } catch (error) {
      if (error && error.name === "AbortError") return state.snapshot;
      setConnection(state.snapshot ? "stale" : "disconnected", state.snapshot ? "Stale data" : "Disconnected");
      if (!state.snapshot) {
        elements.activeLoading.querySelector("p").textContent = "Live threads are unavailable. Use Refresh to try again.";
        elements.recentLoading.textContent = "Recent sessions are unavailable. Use Refresh to try again.";
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
