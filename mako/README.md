# MAKO (trimmed) — vendored orchestrator for this submission

This is a trimmed, self-contained copy of MAKO's `v3-langraph` orchestrator —
the ReAct-style, hop-by-hop autonomous routing engine described in the main
[`REPORT.md`](../REPORT.md) — vendored into this submission so it's a real,
runnable artifact instead of a description of one.

MAKO's actual development repository (a separate final-year engineering
project) has five parallel research versions (`v1`, `v1.1`, `v2`, `v3`,
`v3-langraph`) plus exploratory scripts, a web UI, old run logs, and per-version
virtual environments — several hundred MB of research-ablation history that
has nothing to do with this submission. This folder is **only** the code
needed to actually run one `v3-langraph` orchestration session:

```
agents/        LLM provider abstraction + per-agent role prompts
config.py      env-driven embedding/vector-backend config
embeddings/    embedding providers + vector index (local hashing embedder — no model)
envfile.py     minimal .env loader
kg/            healthcare knowledge graph (RDF/Turtle) + loader/query layer
logutil.py     structured logging
orchestrator/  the LangGraph StateGraph hop-decision loop + trace/eval records
pipeline/      task-type recall (embedding-based) + entry-agent selection
requirements.txt
webui/         clinical routing console (rebuilt — see below)
```

Left out on purpose: `.venv/` (166MB, rebuild your own — see below),
`runs/` and `logs/` (old run artifacts from unrelated sessions), and the
design/planning docs (`plan.md`, `goal_check.md`) that document the
*research* rather than the running system.

MAKO's original `webui/` was a React + TypeScript + Vite + Tailwind +
Cytoscape.js graph explorer (217MB with `node_modules`, no build step
included) — a developer-facing knowledge-graph browser, not something a
clinician would use. **It was not carried over.** `webui/` here is a
from-scratch replacement: a single-page, dependency-free HTML/CSS/JS
console styled like real clinical software (dense, calm, high-contrast, no
framework chrome), reusing MAKO's existing FastAPI backend (trimmed from the
same original `webui/backend/`) unchanged. See [`webui/README.md`](webui/README.md).

## Running it

```bash
# from this directory (mako/)
python3 -m venv .venv   # or: uv venv --python 3.11 .venv
.venv/bin/pip install -r requirements.txt

# start the local model server first, from the repo root:
#   llama-server -m ../model/qwen2.5-3b-instruct-q4_k_m.gguf --port 8811 -t 4 -c 4096

.venv/bin/python -m orchestrator.run \
  "A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement" \
  --json-only
```

`.env` in this directory is already pointed at `http://localhost:8811/v1`
(llama.cpp's OpenAI-compatible server) with `KG_EMBED_PROVIDER=local`, so
the whole run is offline end to end — no API keys needed.

This was verified working from this exact trimmed folder, with a fresh venv,
producing a real multi-hop clinical routing decision in ~7 seconds. See
[`../mako-integration/README.md`](../mako-integration/README.md) for the
unedited log and full trace JSON from that run.
