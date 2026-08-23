"""FastAPI + SSE web layer for v3-langraph.

Wraps the existing CLI orchestrator (orchestrator.loop.run_orchestration)
with a REST API and live per-hop streaming — no changes to routing/decision
logic, only a thin wrapper. See v3-langraph's own README/plan.md for what the
orchestrator itself does.

Run with `v3-langraph/` as the working directory (same convention
`python -m orchestrator.run` relies on):

    cd v3-langraph
    pip install -r webui/backend/requirements.txt
    uvicorn webui.backend.main:app --reload --port 8001

Endpoints
---------
  POST /api/tasks               -> {task} -> {task_id}, runs in the background
  GET  /api/tasks                -> history for the sidebar (disk + live merged)
  GET  /api/tasks/{id}            -> full trace/eval_log for one run
  GET  /api/tasks/{id}/stream     -> SSE: live TraceStep events as they happen
  GET  /api/kg/graph              -> full KG as Cytoscape JSON
  GET  /api/kg/route/{id}         -> task-scoped subgraph (nodes/edges touched)
  GET  /api/agents                -> agent roster (label, specialty, capabilities, tools)
  GET  /api/agents/{id}           -> full agent detail: system prompt, capabilities,
                                      tools, and named handoff edges in/out
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import AsyncIterator

# Defensive sys.path bootstrap, matching v2/viz/server.py's own convention,
# so this works whether launched as `uvicorn webui.backend.main:app` from
# v3-langraph/ or in any other way uvicorn happens to resolve the import.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

from agents.llm import make_provider  # noqa: E402
from agents.prompts import build_domain_system_prompt  # noqa: E402
from kg.loader import load_kg  # noqa: E402
from webui.backend.graph_json import kg_to_cy  # noqa: E402
from webui.backend.registry import RUNS_DIR, TaskRegistry, list_tasks  # noqa: E402

app = FastAPI(title="v3-langraph web UI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Loaded once at process start. A real LLM provider is required for
# v3-langraph (no mock path) — matching orchestrator/run.py, this fails fast
# at startup rather than surfacing per-request if no provider is configured.
_kg = load_kg()
_provider = make_provider()
_registry = TaskRegistry(_kg, _provider)
_graph_json = kg_to_cy(_kg)


class TaskRequest(BaseModel):
    task: str


@app.post("/api/tasks")
def create_task(req: TaskRequest) -> dict:
    task = req.task.strip()
    if not task:
        raise HTTPException(400, "task must not be empty")
    task_id = _registry.start(task)
    return {"task_id": task_id}


@app.get("/api/tasks")
def get_tasks() -> list:
    return list_tasks(_registry)


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    run = _registry.get(task_id)
    if run is not None:
        return {
            "task_id": run.task_id,
            "task": run.task,
            "status": run.status,
            "steps": run.steps,
            "trace": run.trace.to_dict() if run.trace else None,
            "eval_log": run.eval_log.to_list() if run.eval_log else None,
            "reason": run.reason,
        }

    trace_path = RUNS_DIR / f"{task_id}_trace.json"
    eval_path = RUNS_DIR / f"{task_id}_eval.json"
    if not trace_path.is_file():
        raise HTTPException(404, "unknown task_id")
    trace = json.loads(trace_path.read_text())
    eval_log = json.loads(eval_path.read_text()) if eval_path.is_file() else []
    return {
        "task_id": task_id,
        "task": trace.get("task", ""),
        "status": "completed",
        "steps": trace.get("steps", []),
        "trace": trace,
        "eval_log": eval_log,
        "reason": trace.get("final_status"),
    }


@app.get("/api/tasks/{task_id}/stream")
async def stream_task(task_id: str) -> StreamingResponse:
    run = _registry.get(task_id)

    async def events() -> AsyncIterator[bytes]:
        if run is None:
            # Not a live run this process started — replay from disk if it
            # exists, as a single flush (there's nothing left to stream live).
            trace_path = RUNS_DIR / f"{task_id}_trace.json"
            if not trace_path.is_file():
                yield f"event: error\ndata: {json.dumps({'error': 'unknown task_id'})}\n\n".encode()
                return
            trace = json.loads(trace_path.read_text())
            for step in trace.get("steps", []):
                yield f"data: {json.dumps(step)}\n\n".encode()
            done = {"status": "completed", "reason": trace.get("final_status")}
            yield f"event: done\ndata: {json.dumps(done)}\n\n".encode()
            return

        # Flush whatever has already happened (handles reconnects/refreshes),
        # then switch to live queue reads for anything still to come.
        for step in list(run.steps):
            yield f"data: {json.dumps(step)}\n\n".encode()
        if run.status != "running":
            done = {"status": run.status, "reason": run.reason}
            yield f"event: done\ndata: {json.dumps(done)}\n\n".encode()
            return
        while True:
            item = await run_in_threadpool(run.event_queue.get)
            if item is None:
                done = {"status": run.status, "reason": run.reason}
                yield f"event: done\ndata: {json.dumps(done)}\n\n".encode()
                return
            yield f"data: {json.dumps(item)}\n\n".encode()

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/kg/graph")
def get_kg_graph() -> dict:
    return _graph_json


@app.get("/api/agents")
def get_agents() -> list:
    """Agent roster straight off the loaded KG — agents are graph-defined,
    there is no user-editable "add agent" concept in this system."""
    agents = []
    for a in _kg.agents:
        agents.append({
            "id": a,
            "label": _kg.agent_label.get(a, a),
            "specialty": _kg.agent_specialty.get(a, "") or "General",
            "capabilities": [
                {"id": c, "label": _kg.capability_label.get(c, c)}
                for c in sorted(_kg.agent_handles.get(a, set()))
            ],
            "tools": [
                {"id": t, "label": _kg.tool_label.get(t, t)}
                for t in sorted(_kg.agent_owns.get(a, set()))
            ],
            "handoffsOut": len(_kg.out_edges.get(a, [])),
            "handoffsIn": len(_kg.in_edges.get(a, [])),
        })
    return agents


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str) -> dict:
    """Full detail for one agent, fetched on demand when a card is opened —
    the roster endpoint above stays light for grid rendering; this adds the
    computed system prompt and the named handoff edges (with the neighbor
    agent's label and the predicate's human-readable meaning) in both
    directions."""
    if agent_id not in _kg.agent_label:
        raise HTTPException(404, "unknown agent_id")
    return {
        "id": agent_id,
        "label": _kg.agent_label.get(agent_id, agent_id),
        "specialty": _kg.agent_specialty.get(agent_id, "") or "General",
        "systemPrompt": build_domain_system_prompt(_kg, agent_id),
        "capabilities": [
            {"id": c, "label": _kg.capability_label.get(c, c)}
            for c in sorted(_kg.agent_handles.get(agent_id, set()))
        ],
        "tools": [
            {"id": t, "label": _kg.tool_label.get(t, t)}
            for t in sorted(_kg.agent_owns.get(agent_id, set()))
        ],
        "handoffsOut": [
            {
                "id": dst,
                "label": _kg.agent_label.get(dst, dst),
                "predicate": pred,
                "predicateLabel": _kg.predicate_label(pred),
            }
            for dst, pred in _kg.out_edges.get(agent_id, [])
        ],
        "handoffsIn": [
            {
                "id": src,
                "label": _kg.agent_label.get(src, src),
                "predicate": pred,
                "predicateLabel": _kg.predicate_label(pred),
            }
            for src, pred in _kg.in_edges.get(agent_id, [])
        ],
    }


@app.get("/api/kg/route/{task_id}")
def get_kg_route(task_id: str) -> dict:
    run = _registry.get(task_id)
    trace_data: dict | None = None
    if run is not None and run.trace is not None:
        trace_data = run.trace.to_dict()
    else:
        trace_path = RUNS_DIR / f"{task_id}_trace.json"
        if trace_path.is_file():
            trace_data = json.loads(trace_path.read_text())
    if trace_data is None:
        raise HTTPException(404, "unknown or not-yet-complete task_id")

    nodes: list[str] = []
    edges: list[dict] = []
    seen = set()
    for step in trace_data.get("steps", []):
        agent = step["agent"]
        if agent not in seen:
            seen.add(agent)
            nodes.append(agent)
        incoming = step.get("incoming_edge")
        if incoming:
            edges.append({
                "from": incoming["from_agent"],
                "to": agent,
                "predicate": step.get("predicate_used", ""),
                "label": step.get("predicate_label", ""),
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "capabilities_required": trace_data.get("capabilities_required", []),
        "capabilities_covered": trace_data.get("capabilities_covered", []),
    }


# Pure HTML/CSS/JS frontend, served same-origin (no CORS needed, no build
# step) — mounted last so it never shadows the /api/* routes above.
app.mount(
    "/",
    StaticFiles(directory=str(Path(__file__).resolve().parents[1] / "static"), html=True),
    name="static",
)
