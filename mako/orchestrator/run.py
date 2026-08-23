"""v3 demo entry point — the full ReAct KG-grounded orchestrator loop.

Runs one task end-to-end (plan.md §9): recall -> entry selection -> the
hop-by-hop orchestrator loop with real KG-grounded tool calls, the Brief Agent,
the Trace and the separate EvalLog. Prints a readable summary and writes both
streams to JSON.

Usage::

    cd v3
    python -m orchestrator.run "patient with chest pain, needs a cardiac workup"
    python -m orchestrator.run --json-only "..."          # machine-readable only
    python -m orchestrator.run --out-dir runs "..."       # choose output dir

Backends/providers are env-selected. A real LLM provider is REQUIRED — there is
no mock/offline execution path; a missing or failing provider raises:
    KG_LLM_PROVIDER   anthropic|openai|gemini|ollama|local  (auto-detect; errors if none)
    KG_QUERY_BACKEND  rdflib|sparql|cypher                  (default rdflib)
    KG_AGENT_CONTEXT  last-output-only|full-trace          (default last)
    KG_SESSION_RETRY_CAP / KG_MAX_HOP_COUNT                 (loop safety §8)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from kg.loader import load_kg
from logutil import get_logger
from orchestrator.loop import RunOutput, run_orchestration

log = get_logger("run")

_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "runs"


def _print_summary(out: RunOutput) -> None:
    t = out.trace
    print()
    print("=" * 72)
    print(f"TASK          : {t.task}")
    print(f"PROCESS (τ)   : {t.task_type}")
    print(f"ENTRY AGENT   : {t.entry_agent}")
    print(f"FINAL STATUS  : {t.final_status}")
    req, cov = set(t.capabilities_required), set(t.capabilities_covered)
    print(f"COVERAGE      : {len(cov)}/{len(req)} required capabilities"
          + ("" if req.issubset(cov) else f"  (missing: {', '.join(sorted(req - cov))})"))
    print("-" * 72)
    print("PATH:")
    for s in t.steps:
        edge = ""
        if s.incoming_edge is not None:
            edge = f"  <-[{s.predicate_used}]- {s.incoming_edge.from_agent}"
        cov_txt = f"  covers: {s.capability_covered}" if s.capability_covered else ""
        term = ""
        if s.termination.is_terminal:
            term = f"   *TERMINAL: {s.termination.reason}*"
        print(f"  [{s.step_index}] {s.agent}{edge}{cov_txt}"
              + (f"   (attempts={s.attempt_count})" if s.attempt_count else "")
              + term)
    print("-" * 72)
    print(f"EVAL RECORDS  : {len(out.eval_log.records)} validate_decision call(s)")
    invalid = [r for r in out.eval_log.records if not r.is_valid_transition]
    if invalid:
        print(f"  rejected     : {len(invalid)}")
    print("=" * 72)


def _write_outputs(out: RunOutput, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = "".join(c if c.isalnum() else "-" for c in out.trace.task.lower())[:40].strip("-")
    base = out_dir / f"{stamp}_{slug or 'run'}"
    trace_path = base.with_name(base.name + "_trace.json")
    eval_path = base.with_name(base.name + "_eval.json")
    trace_path.write_text(json.dumps(out.trace.to_dict(), indent=2))
    eval_path.write_text(json.dumps(out.eval_log.to_list(), indent=2))
    return base


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run the v3 KG-grounded orchestrator.")
    ap.add_argument("task", nargs="*", help="natural-language task description")
    ap.add_argument("--json-only", action="store_true",
                    help="print only the trace JSON to stdout")
    ap.add_argument("--no-write", action="store_true",
                    help="do not write trace/eval JSON files")
    ap.add_argument("--out-dir", default=str(_DEFAULT_OUT),
                    help=f"directory for JSON outputs (default: {_DEFAULT_OUT})")
    args = ap.parse_args(argv)

    task = " ".join(args.task).strip()
    if not task:
        ap.error('provide a task, e.g. python -m orchestrator.run "chest pain workup"')

    kg = load_kg()
    out = run_orchestration(task, kg)

    if args.json_only:
        print(json.dumps(out.trace.to_dict(), indent=2))
    else:
        _print_summary(out)

    if not args.no_write:
        base = _write_outputs(out, Path(args.out_dir))
        if not args.json_only:
            print(f"\nwrote: {base.name}_trace.json  +  {base.name}_eval.json")

    return 0 if out.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
