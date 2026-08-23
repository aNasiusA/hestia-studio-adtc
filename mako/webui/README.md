# HestiaHealth clinical routing console

A single-page, dependency-free HTML/CSS/JS front end for MAKO's `v3-langraph`
orchestrator, styled to look like something a clinical-ops team could
actually run — not a developer graph-debugging tool.

## What changed from the original `webui/`

MAKO's original web UI (`v3-langraph/webui/` in the full development repo)
was a React + TypeScript + Vite + Tailwind + Cytoscape.js single-page app: a
knowledge-graph explorer with force-directed layout, playback controls, and
a chat-style run panel — built for inspecting the graph during development,
not for a clinical setting. It also carried ~217MB of `node_modules` and a
build toolchain.

`static/` here is a full rewrite: plain `index.html` + `style.css` +
`app.js`, no framework, no `npm install`, no build step — open the served
page and it works. The backend (`backend/main.py`, `graph_json.py`,
`registry.py`) started as a trim of the original, unchanged; it has since
grown one real capability the original never had — resumable runs — see
below.

## What it does

- **New case** — free-text patient case description, submitted to
  `POST /api/tasks`, which starts MAKO's real orchestrator in a background
  thread against whichever model `KG_BASE_URL` points at (the local
  `llama-server` for this submission).
- **Live routing timeline** — subscribes to `GET /api/tasks/{id}/stream`
  (server-sent events) and renders each hop as it happens: which agent
  acted, which capability it covered, the handoff edge used, how many
  proposals the graph validator rejected before accepting one, and the
  agent's own reasoning text.
- **Coverage bar** — required vs. covered capabilities for the case,
  finalized once the run completes (the total isn't known mid-run — the
  UI shows an honest "routing…" indeterminate state rather than a
  misleading fraction).
- **Recent cases** — merges on-disk history (`../runs/*_trace.json`) with
  whatever's currently running, so refreshing the page never loses state.
- **Termination banner** — every run ends with an explicit reason (complete,
  voluntarily stopped pending more input, or max-hop-count exceeded) shown
  plainly, not hidden in a log.
- **Continue this case** — a pause isn't a dead end. When a run stops because
  the model wants more information, or because it hit the hop limit while
  mid-decision, the console shows a form to type additional context and
  resume the *same* case rather than starting over. See below.

Nothing is mocked: every field rendered comes straight from a live
`TraceStep` emitted by `orchestrator/loop.py`.

## Resumable runs

The original orchestrator (`orchestrator/loop.py`) was a single Python
function: `run_orchestration()` ran its hop loop start to finish and
returned. Whether it paused because the model voluntarily stopped
(`voluntary_early_stop`) or because it hit the hop budget mid-decision
(`max_hop_exceeded`), every bit of loop state — which agent was up next,
what had been covered, the conversation history — was thrown away the
moment the function returned. There was no way to give it more information
and pick back up; a paused case was just stuck.

`orchestrator/loop.py` now captures that state as a `LoopState` snapshot
(`RunOutput.resume_state`) whenever a run pauses for one of those two
reasons, and `continue_orchestration(state, additional_info)` resumes from
it with a fresh hop budget. Where the extra context lands depends on *why*
it paused:

- **Voluntarily stopped** — the current agent already ran; what's missing is
  a decision for what comes next. The additional info is folded into
  `last_brief`, which feeds straight into the hop-decision session's system
  prompt, and the model re-decides with it in hand.
- **Hop limit hit** — the next agent was already decided but never executed.
  The additional info is folded into the tail of `raw_history` (not appended
  as a new entry — the default context provider only shows the *most
  recent* entry, so appending separately would silently drop it) and the
  loop continues by executing that agent.

The webui's `TaskRegistry` (`webui/backend/registry.py`) holds the
`LoopState` in memory against a task_id while a run is paused, and
`POST /api/tasks/{id}/continue` resumes it in a background thread — the
same way a fresh case is started. This is intentionally **not** persisted
to disk: `LoopState` holds live Python objects (the loaded KG, the LLM
provider), and resumability only needs to survive for the lifetime of one
browser session's back-and-forth on a case, not across a server restart.

Verified end-to-end against the real local model, not just at the API
level: submitted a case through the console, watched it pause, typed
follow-up context into the continue form, and watched a genuinely new
domain-agent execution stream in — with no duplicate cards in the
timeline, which took a real bug fix along the way (the orchestrator was
re-emitting the same already-shown step on every re-decision, and
separately the SSE stream always replays every accumulated step on a
fresh connection — both needed de-duplication, one on each side).

## Running it

```bash
# from mako/ (the parent directory), with its venv already set up:
.venv/bin/pip install -r webui/backend/requirements.txt   # fastapi + uvicorn

# make sure llama-server is running first (see ../README.md), then:
.venv/bin/uvicorn webui.backend.main:app --port 8001
```

Open `http://localhost:8001/` — the backend serves the static frontend
directly (same origin, no CORS configuration needed for normal use).
