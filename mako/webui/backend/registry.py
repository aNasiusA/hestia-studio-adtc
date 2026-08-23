"""In-memory task registry bridging the orchestrator's synchronous `on_step`
callback (invoked from a worker thread) to the FastAPI SSE layer.

Each task run gets a thread-safe `queue.Queue` that `on_step` pushes to and
the SSE endpoint drains from. `run.steps` additionally accumulates every step
seen so far so a reconnecting client (e.g. a page refresh mid-run) can be
replayed from the start before switching to live queue reads.

Completed runs are persisted to `runs/` using the exact same
timestamp+slug naming convention as the CLI (`orchestrator/run.py`'s
`_write_outputs`), so the on-disk history and the web UI's history share one
directory and `GET /api/tasks` can list both without duplication.
"""
from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from agents.llm import LLMProvider
from kg.loader import KGData
from orchestrator.loop import run_orchestration
from orchestrator.trace import EvalLog, Trace, TraceStep

RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"


def make_task_id(task: str) -> str:
    """Mirrors orchestrator/run.py::_write_outputs's naming exactly."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = "".join(c if c.isalnum() else "-" for c in task.lower())[:40].strip("-")
    return f"{stamp}_{slug or 'run'}"


@dataclass
class TaskRun:
    task_id: str
    task: str
    status: str = "running"  # running | completed | failed
    steps: List[dict] = field(default_factory=list)
    trace: Optional[Trace] = None
    eval_log: Optional[EvalLog] = None
    ok: Optional[bool] = None
    reason: Optional[str] = None
    event_queue: "queue.Queue" = field(default_factory=queue.Queue)

    def to_summary(self) -> dict:
        return {
            "task_id": self.task_id,
            "task": self.task,
            "status": self.status,
            "final_status": self.trace.final_status if self.trace else None,
            "entry_agent": self.trace.entry_agent if self.trace else None,
        }


class TaskRegistry:
    def __init__(self, kg: KGData, provider: LLMProvider) -> None:
        self._kg = kg
        self._provider = provider
        self._runs: Dict[str, TaskRun] = {}
        self._lock = threading.Lock()

    def start(self, task: str) -> str:
        with self._lock:
            task_id = make_task_id(task)
            while task_id in self._runs:
                task_id += "-x"
            run = TaskRun(task_id=task_id, task=task)
            self._runs[task_id] = run
        threading.Thread(target=self._execute, args=(run,), daemon=True).start()
        return task_id

    def _execute(self, run: TaskRun) -> None:
        def on_step(step: TraceStep) -> None:
            payload = step.to_dict()
            run.steps.append(payload)
            run.event_queue.put(payload)

        try:
            out = run_orchestration(run.task, self._kg, provider=self._provider, on_step=on_step)
            run.trace = out.trace
            run.eval_log = out.eval_log
            run.ok = out.ok
            run.reason = out.reason
            run.status = "completed"
            self._persist(run)
        except Exception as exc:  # surfaced via the "done" SSE event, not raised
            run.status = "failed"
            run.reason = str(exc)
        finally:
            run.event_queue.put(None)  # sentinel: stream end

    def _persist(self, run: TaskRun) -> None:
        assert run.trace is not None and run.eval_log is not None
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        base = RUNS_DIR / run.task_id
        base.with_name(base.name + "_trace.json").write_text(
            json.dumps(run.trace.to_dict(), indent=2))
        base.with_name(base.name + "_eval.json").write_text(
            json.dumps(run.eval_log.to_list(), indent=2))

    def get(self, task_id: str) -> Optional[TaskRun]:
        return self._runs.get(task_id)

    def list_live(self) -> List[TaskRun]:
        return list(self._runs.values())


def list_tasks(registry: TaskRegistry) -> List[dict]:
    """Merge on-disk history (runs/*_trace.json) with in-memory live runs."""
    merged: Dict[str, dict] = {}
    if RUNS_DIR.exists():
        for f in RUNS_DIR.glob("*_trace.json"):
            task_id = f.name[: -len("_trace.json")]
            try:
                data = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            merged[task_id] = {
                "task_id": task_id,
                "task": data.get("task", ""),
                "status": "completed",
                "final_status": data.get("final_status"),
                "entry_agent": data.get("entry_agent"),
            }
    for run in registry.list_live():
        merged[run.task_id] = run.to_summary()
    return sorted(merged.values(), key=lambda r: r["task_id"], reverse=True)
