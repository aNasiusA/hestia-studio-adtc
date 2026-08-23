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
page and it works. The **backend is unchanged** (`backend/main.py`,
`graph_json.py`, `registry.py`, trimmed straight from the original) — this
only replaces the frontend.

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

Nothing is mocked: every field rendered comes straight from a live
`TraceStep` emitted by `orchestrator/loop.py`.

## Running it

```bash
# from mako/ (the parent directory), with its venv already set up:
.venv/bin/pip install -r webui/backend/requirements.txt   # fastapi + uvicorn

# make sure llama-server is running first (see ../README.md), then:
.venv/bin/uvicorn webui.backend.main:app --port 8001
```

Open `http://localhost:8001/` — the backend serves the static frontend
directly (same origin, no CORS configuration needed for normal use).
