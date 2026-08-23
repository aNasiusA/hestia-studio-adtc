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
// The SSE stream always replays every accumulated step from the start on a
// fresh connection (correct for "load a page that's rendered nothing yet",
// wrong for "just resumed via continue, timeline already has these
// rendered") — dedupe by step_index rather than trying to make the backend
// track per-client replay state.
let renderedStepIndices = new Set();

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

// Internal knowledge-graph capability ids arrive smash-cased with a "cap_"
// prefix (e.g. "cap_PlanCardiacTreatment") — not something to show a
// clinician as-is. Strip the prefix and space out the words.
function humanizeCapability(capId) {
  if (!capId) return "";
  const bare = capId.replace(/^cap_/, "");
  return bare
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .trim();
}

// The graph's handoff predicates are a fixed, small vocabulary — map them to
// plain verbs instead of showing the internal predicate name or its full
// technical description (which includes bracketed engineering tags like
// "(stage_complete)").
const PREDICATE_VERBS = {
  delegatesTo: "delegated to",
  consults: "consulted",
  escalatesTo: "escalated to",
  refersTo: "referred to",
  returnsTo: "returned the case to",
};
function friendlyPredicate(predicateId) {
  return PREDICATE_VERBS[predicateId] || "handed off to";
}

// Termination reasons come back as internal status codes — translate to
// something a clinical user would actually read.
function friendlyReason(reason) {
  const map = {
    voluntary_early_stop: "Routing paused — additional information is needed before the next step can be determined.",
    llm_voluntary: "Routing paused — additional information is needed before the next step can be determined.",
    max_hop_exceeded: "Routing incomplete — this case reached the handoff limit and should be reviewed manually.",
  };
  if (map[reason]) return map[reason];
  if (!reason) return "Routing paused — awaiting further input.";
  return "Routing stopped — " + reason.replace(/_/g, " ") + ".";
}

// Short status word for the sidebar case list (not a full sentence).
function shortStatus(status, finalStatus) {
  if (status === "running") return "In progress";
  if (status === "paused") return finalStatus === "max_hop_exceeded" ? "Needs review" : "Needs input";
  if (status === "failed" || finalStatus === "session_retry_exceeded") return "Stopped";
  return "Completed";
}

function setStatus(pillEl, kind, text) {
  pillEl.className = "status-pill " + (
    { running: "status-running", input: "status-input", complete: "status-ok", error: "status-error" }[kind] || ""
  );
  pillEl.textContent = text;
}

// --- Minimal markdown rendering for agent reasoning text -------------------
// Agent briefs are free-text LLM output, not markup — always escape first,
// then only introduce HTML we generate ourselves from known-safe patterns.
// This is intentionally small (bold/italic/code/bullets + labeled-field
// detection), not a full markdown parser.

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function mdInline(s) {
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>");
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  return s;
}

const titleCase = (s) => s.replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());

// Model output for a step brief tends to arrive as labeled fields —
// "Accomplished: ...", "Current status: ...", "Next step: ..." — but not
// always cleanly newline-separated; sometimes all three land in one run-on
// line. Bold the label wherever one starts (line start, or after a
// sentence boundary) rather than only at the very start of a line, so
// mid-line labels still get picked up.
function boldLabels(line) {
  return line.replace(/(^|\.\s+)([A-Za-z][A-Za-z /]{2,30}):\s+/g, (_, pre, label) => `${pre}<strong>${titleCase(label)}:</strong> `);
}

function renderBrief(raw) {
  if (!raw) return "";
  const lines = escapeHtml(raw).split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  return lines.map((line) => {
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) return `<p class="brief-line">&#8226; ${mdInline(boldLabels(bullet[1]))}</p>`;
    return `<p class="brief-line">${mdInline(boldLabels(line))}</p>`;
  }).join("");
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
    h.innerHTML = `${labelOf(step.incoming_edge.from_agent)} ${friendlyPredicate(step.predicate_used)} <b>${labelOf(step.agent)}</b>`;
    card.appendChild(h);
  }

  const cap = document.createElement("div");
  cap.className = "capability-line";
  cap.innerHTML = `Step completed: <b>${humanizeCapability(step.capability_covered)}</b>`;
  card.appendChild(cap);

  if (step.brief) {
    const brief = document.createElement("div");
    brief.className = "step-brief";
    brief.innerHTML = renderBrief(step.brief);
    card.appendChild(brief);
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
  coverageCount.textContent = `${covered.length} of ${required.length} clinical steps completed`;
}

function resetTimeline(task) {
  timelineEl.innerHTML = "";
  caseTitle.textContent = task;
  emptyState.classList.add("hidden");
  caseView.classList.remove("hidden");
  requiredCount = 0;
  coveredSet = new Set();
  renderedStepIndices = new Set();
  updateCoverage([], []);
}

// A pause banner + (if resumable) a "continue this case" form, as one
// removable unit so resuming can cleanly clear it before new steps stream in.
function appendTerminationBanner(taskId, reason, complete, resumable) {
  const li = document.createElement("li");
  li.className = "step terminal";
  const dot = document.createElement("div");
  dot.className = "step-dot";
  li.appendChild(dot);

  const banner = document.createElement("div");
  banner.className = "termination-banner" + (complete ? " complete" : "");
  banner.textContent = complete
    ? "All required clinical steps for this case are complete."
    : friendlyReason(reason);
  li.appendChild(banner);

  if (resumable && !complete) {
    const panel = document.createElement("div");
    panel.className = "continue-panel";
    panel.innerHTML = `
      <label class="continue-label">Provide additional information to continue this case</label>
      <textarea class="continue-input" rows="3" placeholder="e.g. lab results just came back, a specialist is unavailable, clarify the patient's history…"></textarea>
      <button class="btn-secondary continue-btn">Continue routing</button>
      <p class="continue-hint"></p>
    `;
    const textarea = panel.querySelector(".continue-input");
    const btn = panel.querySelector(".continue-btn");
    const hint = panel.querySelector(".continue-hint");
    btn.addEventListener("click", async () => {
      const info = textarea.value.trim();
      if (!info) return;
      btn.disabled = true;
      hint.textContent = "Resuming…";
      try {
        const res = await fetch(`/api/tasks/${taskId}/continue`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ additional_info: info }),
        });
        if (!res.ok) throw new Error("continue failed");
        li.remove(); // clear this banner+panel; new steps stream in below
        setStatus(caseStatus, "running", "Routing…");
        subscribeStream(taskId);
      } catch (e) {
        hint.textContent = "Could not resume this case — please check the routing service is running.";
        btn.disabled = false;
      }
    });
    li.appendChild(panel);
  }

  timelineEl.appendChild(li);
}

// Subscribes (or re-subscribes, after a continue) to a task's SSE stream.
// Never resets the timeline itself — callers decide when a fresh case
// starts vs. an existing one resuming.
function subscribeStream(taskId) {
  if (currentEventSource) currentEventSource.close();
  const es = new EventSource(`/api/tasks/${taskId}/stream`);
  currentEventSource = es;

  es.onmessage = (evt) => {
    const step = JSON.parse(evt.data);
    if (renderedStepIndices.has(step.step_index)) return; // already on screen
    renderedStepIndices.add(step.step_index);
    coveredSet.add(step.capability_covered);
    updateCoverage([...coveredSet], [...coveredSet]); // refined below on "done"
    timelineEl.appendChild(renderStep(step, false));
    timelineEl.scrollTop = timelineEl.scrollHeight;
  };

  es.addEventListener("done", async (evt) => {
    const data = JSON.parse(evt.data);
    let required = [];
    try {
      const full = await fetch(`/api/tasks/${taskId}`).then((r) => r.json());
      required = (full.trace && full.trace.capabilities_required) || [];
      const covered = (full.trace && full.trace.capabilities_covered) || [...coveredSet];
      updateCoverage(covered, required);
    } catch (e) { /* keep the running-state count if this fails */ }
    const complete = required.length > 0 && coveredSet.size >= required.length;
    setStatus(
      caseStatus,
      complete ? "complete" : (data.resumable ? "input" : "error"),
      complete ? "Complete" : (data.resumable ? "Needs input" : "Stopped"),
    );
    appendTerminationBanner(taskId, data.reason, complete, !!data.resumable);
    es.close();
    refreshCaseList();
  });

  es.addEventListener("error", () => {
    setStatus(caseStatus, "error", "Connection lost");
    es.close();
  });
}

function watchTask(taskId, task, requiredCaps) {
  currentTaskId = taskId;
  resetTimeline(task);
  requiredCount = (requiredCaps || []).length;
  setStatus(caseStatus, "running", "Routing…");
  subscribeStream(taskId);
}

async function loadTask(taskId) {
  const data = await fetch(`/api/tasks/${taskId}`).then((r) => r.json());
  resetTimeline(data.task);
  const required = (data.trace && data.trace.capabilities_required) || [];
  const covered = (data.trace && data.trace.capabilities_covered) || [];
  requiredCount = required.length;
  coveredSet = new Set(covered);
  updateCoverage(covered, required);
  (data.steps || []).forEach((step) => {
    renderedStepIndices.add(step.step_index);
    timelineEl.appendChild(renderStep(step, false));
  });
  const complete = required.length > 0 && covered.length >= required.length;
  if (data.status === "running") {
    setStatus(caseStatus, "running", "Routing…");
    subscribeStream(taskId);
  } else {
    setStatus(
      caseStatus,
      complete ? "complete" : (data.resumable ? "input" : "error"),
      complete ? "Complete" : (data.resumable ? "Needs input" : "Stopped"),
    );
    appendTerminationBanner(taskId, data.reason, complete, !!data.resumable);
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
      `<div class="case-item-meta">${t.entry_agent ? labelOf(t.entry_agent) : "…"} · ${shortStatus(t.status, t.final_status)}</div>`;
    li.addEventListener("click", () => loadTask(t.task_id));
    caseList.appendChild(li);
  });
  highlightActiveCase(currentTaskId);
}

async function submitCase() {
  const task = caseInput.value.trim();
  if (!task) return;
  submitBtn.disabled = true;
  submitHint.textContent = "Submitting case…";
  try {
    const { task_id } = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task }),
    }).then((r) => r.json());
    caseInput.value = "";
    watchTask(task_id, task, []);
    refreshCaseList();
    submitHint.textContent = "Routes through the clinical decision engine, entirely offline.";
  } catch (e) {
    submitHint.textContent = "Could not reach the routing service — please check it's running.";
  } finally {
    submitBtn.disabled = false;
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
