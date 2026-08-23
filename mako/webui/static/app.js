// HestiaHealth Clinical Routing Console — vanilla JS, no build step.
// Talks to the FastAPI backend (webui/backend/main.py) which wraps MAKO's
// real orchestrator. Nothing here is mocked — every step rendered is a
// live TraceStep streamed straight from python -m orchestrator.run.

const el = (sel) => document.querySelector(sel);

const caseInput = el("#case-input");
const submitBtn = el("#submit-case");
const submitHint = el("#submit-hint");
const caseList = el("#case-list");
const emptyState = el("#empty-state");
const caseView = el("#case-view");
const caseTitle = el("#case-title");
const caseStatus = el("#case-status");
const coverageFill = el("#coverage-fill");
const coverageCount = el("#coverage-count");
const timelineEl = el("#timeline");
const modelMeta = el("#model-meta");
const modelStatus = el("#model-status");

let agentMeta = {};       // agent id -> {label, specialty}
let currentTaskId = null;
let currentEventSource = null;
let requiredCount = 0;
let coveredSet = new Set();

async function loadAgentMeta() {
  try {
    const agents = await fetch("/api/agents").then((r) => r.json());
    agents.forEach((a) => { agentMeta[a.id] = { label: a.label, specialty: a.specialty }; });
  } catch (e) {
    console.warn("agent roster unavailable", e);
  }
}

function specialtyOf(agentId) {
  return (agentMeta[agentId] && agentMeta[agentId].specialty) || agentId.split("_")[0];
}
function labelOf(agentId) {
  return (agentMeta[agentId] && agentMeta[agentId].label) || agentId.replace(/_/g, " ");
}

function setStatus(pillEl, kind, text) {
  pillEl.className = "status-pill " + (
    { running: "status-running", input: "status-input", complete: "status-ok", error: "status-error" }[kind] || ""
  );
  pillEl.textContent = text;
}

function renderStep(step, isTerminal) {
  const li = document.createElement("li");
  li.className = "step" + (isTerminal ? " terminal" : "");

  const dot = document.createElement("div");
  dot.className = "step-dot";
  li.appendChild(dot);

  const card = document.createElement("div");
  card.className = "step-card";

  const head = document.createElement("div");
  head.className = "step-card-head";
  const nameWrap = document.createElement("div");
  nameWrap.innerHTML =
    `<span class="agent-name">${labelOf(step.agent)}</span>` +
    `<span class="specialty-badge">${specialtyOf(step.agent)}</span>`;
  head.appendChild(nameWrap);
  const ts = document.createElement("span");
  ts.className = "step-timestamp";
  ts.textContent = new Date(step.timestamp).toLocaleTimeString();
  head.appendChild(ts);
  card.appendChild(head);

  if (step.incoming_edge) {
    const h = document.createElement("div");
    h.className = "handoff-line";
    h.innerHTML = `${labelOf(step.incoming_edge.from_agent)} <span class="arrow">&#8594;</span> ${labelOf(step.agent)}` +
      (step.predicate_label ? ` &nbsp;·&nbsp; ${step.predicate_label}` : "");
    card.appendChild(h);
  }

  const cap = document.createElement("div");
  cap.className = "capability-line";
  cap.innerHTML = `Covers <b>${(step.capability_covered || "").replace(/^cap_/, "")}</b>`;
  card.appendChild(cap);

  if (step.brief) {
    const brief = document.createElement("div");
    brief.className = "step-brief";
    brief.textContent = step.brief;
    card.appendChild(brief);
  }

  if (step.attempt_count > 1) {
    const note = document.createElement("div");
    note.className = "attempt-note";
    note.textContent = `Accepted on attempt ${step.attempt_count} — ${step.attempt_count - 1} prior proposal(s) rejected by the graph validator.`;
    card.appendChild(note);
  }

  li.appendChild(card);
  return li;
}

function updateCoverage(covered, required) {
  if (!required.length) {
    // Required-capability count isn't known until the run completes (it's
    // a Trace-level field, not per-step) — show an indeterminate running
    // count instead of a misleading "n / 0".
    coverageFill.style.width = "8%";
    coverageFill.classList.add("indeterminate");
    coverageCount.textContent = covered.length
      ? `${covered.length} covered so far — total pending completion`
      : "Routing…";
    return;
  }
  coverageFill.classList.remove("indeterminate");
  const pct = Math.round((covered.length / required.length) * 100);
  coverageFill.style.width = pct + "%";
  coverageCount.textContent = `${covered.length} / ${required.length}`;
}

function resetTimeline(task) {
  timelineEl.innerHTML = "";
  caseTitle.textContent = task;
  emptyState.classList.add("hidden");
  caseView.classList.remove("hidden");
  requiredCount = 0;
  coveredSet = new Set();
  updateCoverage([], []);
}

function appendTerminationBanner(reason, complete) {
  const li = document.createElement("li");
  li.className = "step terminal";
  const dot = document.createElement("div");
  dot.className = "step-dot";
  li.appendChild(dot);
  const banner = document.createElement("div");
  banner.className = "termination-banner" + (complete ? " complete" : "");
  banner.textContent = complete
    ? "All required capabilities covered — case handoff chain complete."
    : `Orchestrator stopped: ${reason || "awaiting further input"}.`;
  li.appendChild(banner);
  timelineEl.appendChild(li);
}

function watchTask(taskId, task, requiredCaps) {
  currentTaskId = taskId;
  if (currentEventSource) currentEventSource.close();
  resetTimeline(task);
  requiredCount = (requiredCaps || []).length;
  setStatus(caseStatus, "running", "Routing…");

  const es = new EventSource(`/api/tasks/${taskId}/stream`);
  currentEventSource = es;

  es.onmessage = (evt) => {
    const step = JSON.parse(evt.data);
    coveredSet.add(step.capability_covered);
    updateCoverage([...coveredSet], requiredCaps || [...coveredSet]);
    timelineEl.appendChild(renderStep(step, false));
    timelineEl.scrollTop = timelineEl.scrollHeight;
  };

  es.addEventListener("done", async (evt) => {
    const data = JSON.parse(evt.data);
    // Required-capability count only becomes known once the Trace is
    // finalized — fetch it now for an accurate final coverage bar.
    let required = requiredCaps || [];
    try {
      const full = await fetch(`/api/tasks/${taskId}`).then((r) => r.json());
      required = (full.trace && full.trace.capabilities_required) || required;
      const covered = (full.trace && full.trace.capabilities_covered) || [...coveredSet];
      updateCoverage(covered, required);
    } catch (e) { /* keep the running-state count if this fails */ }
    const complete = required.length > 0 && coveredSet.size >= required.length;
    setStatus(caseStatus, complete ? "complete" : "input", complete ? "Complete" : "Needs input");
    appendTerminationBanner(data.reason, complete);
    es.close();
    refreshCaseList();
  });

  es.addEventListener("error", () => {
    setStatus(caseStatus, "error", "Connection lost");
    es.close();
  });
}

async function loadTask(taskId) {
  const data = await fetch(`/api/tasks/${taskId}`).then((r) => r.json());
  resetTimeline(data.task);
  const required = (data.trace && data.trace.capabilities_required) || [];
  const covered = (data.trace && data.trace.capabilities_covered) || [];
  requiredCount = required.length;
  coveredSet = new Set(covered);
  updateCoverage(covered, required);
  (data.steps || []).forEach((step) => timelineEl.appendChild(renderStep(step, false)));
  const complete = required.length > 0 && covered.length >= required.length;
  if (data.status === "running") {
    setStatus(caseStatus, "running", "Routing…");
    watchTask(taskId, data.task, required);
  } else {
    setStatus(caseStatus, complete ? "complete" : "input", complete ? "Complete" : "Needs input");
    appendTerminationBanner(data.reason, complete);
  }
  highlightActiveCase(taskId);
}

function highlightActiveCase(taskId) {
  [...caseList.children].forEach((li) => {
    li.classList.toggle("active", li.dataset.taskId === taskId);
  });
}

async function refreshCaseList() {
  const tasks = await fetch("/api/tasks").then((r) => r.json());
  caseList.innerHTML = "";
  if (!tasks.length) {
    caseList.innerHTML = '<li class="case-list-empty">No cases yet</li>';
    return;
  }
  tasks.forEach((t) => {
    const li = document.createElement("li");
    li.className = "case-item";
    li.dataset.taskId = t.task_id;
    li.innerHTML =
      `<div class="case-item-task">${t.task}</div>` +
      `<div class="case-item-meta">${t.entry_agent ? labelOf(t.entry_agent) : "…"} · ${t.final_status || t.status}</div>`;
    li.addEventListener("click", () => loadTask(t.task_id));
    caseList.appendChild(li);
  });
  highlightActiveCase(currentTaskId);
}

async function submitCase() {
  const task = caseInput.value.trim();
  if (!task) return;
  submitBtn.disabled = true;
  submitHint.textContent = "Submitting to the orchestrator…";
  try {
    const { task_id } = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task }),
    }).then((r) => r.json());
    caseInput.value = "";
    watchTask(task_id, task, []);
    refreshCaseList();
  } catch (e) {
    submitHint.textContent = "Could not reach the local orchestrator — is the backend running?";
  } finally {
    submitBtn.disabled = false;
    submitHint.textContent = "Routes through MAKO's knowledge-graph orchestrator, running entirely offline.";
  }
}

submitBtn.addEventListener("click", submitCase);
caseInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitCase();
});

(async function init() {
  await loadAgentMeta();
  await refreshCaseList();
})();
