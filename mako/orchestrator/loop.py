"""End-to-end orchestration loop (plan.md §9), with termination (§7) and loop
safety (§8) wired in.

    entry_agent <- recall -> select_process -> pooled nodeBonus argmax   [§1]
    loop (bounded by MAX_HOP_COUNT):
        raw_output <- execute(current_agent)          [domain agent, §12]
        brief      <- BriefAgent(raw_output)           [§5]
        trace.append(...)                              [§6]
        if coverage complete: halt (coverage_satisfied)   [§7 safety net]
        session <- new hop-decision session            [§4]
        decision <- session.run(...)                    [validate->commit gate]
        if TERMINATE: halt (voluntary_early_stop)      [§7 llm-voluntary]
        if session hard-fail: halt (session_retry_exceeded)  [§8]
        current_agent <- decision.agent

Both termination triggers are live simultaneously: the coverage-complete safety
net can stop the run even if the orchestrator would continue, and the
orchestrator may voluntarily TERMINATE early (recorded distinctly).
"""
from __future__ import annotations

import uuid
from typing import Callable, List, Optional

from agents.brief import BriefAgent
from agents.context import AgentContextProvider
from agents.domain import DomainAgentExecutor
from agents.llm import LLMProvider, make_provider
from config import EmbeddingConfig
from embeddings import EmbeddingService
from kg.loader import KGData, load_kg
from kg.query import KGQueryBackend, make_query_backend
from logutil import get_logger
from orchestrator.constants import MAX_HOP_COUNT
from orchestrator.entry_run import get_index
from orchestrator.session import (OUT_COMMIT, OUT_FAILED, OUT_TERMINATE,
                                  HopDecisionSession)
from orchestrator.trace import (EvalLog, IncomingEdge, Termination, Trace,
                                TraceStep)
from pipeline.entry import select_entry_agent
from pipeline.recall import recall_candidates

log = get_logger("loop")


class RunOutput:
    """Bundle returned by :func:`run_orchestration`."""

    def __init__(self, trace: Trace, eval_log: EvalLog, ok: bool, reason: str) -> None:
        self.trace = trace
        self.eval_log = eval_log
        self.ok = ok
        self.reason = reason


def _covered_required(kg: KGData, agent: str, required: set, already: set) -> List[str]:
    """Required capabilities this agent newly covers."""
    handled = kg.agent_handles.get(agent, set())
    return sorted((handled & required) - already)


def run_orchestration(
    task: str,
    kg: Optional[KGData] = None,
    *,
    provider: Optional[LLMProvider] = None,
    service: Optional[EmbeddingService] = None,
    cfg: Optional[EmbeddingConfig] = None,
    query_backend: Optional[KGQueryBackend] = None,
    context_provider: Optional[AgentContextProvider] = None,
    k: int = 10,
    on_step: Optional[Callable[[TraceStep], None]] = None,
) -> RunOutput:
    kg = kg or load_kg()
    provider = provider if provider is not None else make_provider()
    service = service or get_index(kg, cfg)
    query = query_backend or make_query_backend(kg)

    # ---- §1: entry selection ------------------------------------------------
    recall = recall_candidates(task, service, k=k)
    entry = select_entry_agent(recall, kg)
    if not entry.ok or not entry.entry_agent or not entry.process:
        trace = Trace(task=task, task_type=entry.process or "", final_status="voluntary_early_stop")
        log.warning("entry selection failed: %s", entry.reason)
        return RunOutput(trace, EvalLog(), ok=False, reason=entry.reason)

    required = set(entry.required)
    task_type_label = entry.process_label or entry.process
    log.info("task=%r", task)
    log.success("process=%s  entry=%s  required=%s",
                entry.process, entry.entry_agent, ", ".join(entry.required))

    trace = Trace(
        task=task, task_type=entry.process, entry_agent=entry.entry_agent,
        capabilities_required=sorted(required),
    )
    eval_log = EvalLog()

    domain = DomainAgentExecutor(kg, provider=provider, context_provider=context_provider)
    brief_agent = BriefAgent(kg, provider=provider)
    # The orchestrator is a LangGraph StateGraph driven by the real LLM via native
    # function-calling (bind_tools). There is no heuristic/offline stand-in — a
    # failing LLM surfaces as an error.
    log.info("orchestrator: langgraph state-graph, model=%s (%s)",
             getattr(provider, "model", "?"), getattr(provider, "name", "?"))

    covered: set = set()
    raw_history: List[str] = []
    trace_summary: List[str] = []
    incoming: Optional[IncomingEdge] = None
    pending_edge = ("", "")   # (predicate, label) of the edge into the NEXT agent
    current_agent = entry.entry_agent
    final_status = "max_hop_exceeded"

    for hop in range(MAX_HOP_COUNT):
        # ---- execute the domain agent + brief (§5, §12) --------------------
        raw_output = domain.run(current_agent, task, raw_history)
        brief = brief_agent.summarize(current_agent, raw_output)
        raw_history.append(raw_output)

        newly = _covered_required(kg, current_agent, required, covered)
        covered.update(newly)
        trace_summary.append(current_agent)

        pred_used, pred_label = ("", "")
        if incoming is not None:
            pred_used, pred_label = pending_edge

        step = TraceStep(
            step_index=hop,
            agent=current_agent,
            capability_covered=", ".join(newly),
            predicate_used=pred_used,
            predicate_label=pred_label,
            incoming_edge=incoming,
            brief=brief,
            attempt_count=0,
            raw_output=raw_output,
        )
        trace.steps.append(step)
        log.info("hop %d: %s  covers[%s]  (covered %d/%d)",
                 hop, current_agent, ", ".join(newly) or "-",
                 len(covered), len(required))

        # ---- §7 coverage-complete safety net -------------------------------
        if required.issubset(covered):
            step.termination = Termination(True, "coverage_satisfied")
            final_status = "completed"
            log.success("coverage satisfied -> completed")
            if on_step:
                on_step(step)
            break

        # ---- §4 hop-decision session --------------------------------------
        session = HopDecisionSession(
            kg=kg, query=query, provider=provider, eval_log=eval_log,
            session_id=f"{uuid.uuid4().hex[:8]}",
        )
        outcome = session.run(
            task=task, task_type_label=task_type_label,
            current_agent=current_agent, required=entry.required,
            covered=covered, last_brief=brief, trace_summary=list(trace_summary),
        )
        step.attempt_count = outcome.attempt_count

        if outcome.kind == OUT_TERMINATE:
            step.termination = Termination(True, "llm_voluntary")
            final_status = "voluntary_early_stop"
            log.warning("orchestrator voluntarily terminated (early stop)")
            if on_step:
                on_step(step)
            break
        if outcome.kind == OUT_FAILED:
            step.termination = Termination(True, "session_retry_exceeded")
            final_status = "session_retry_exceeded"
            log.error("session retry cap exceeded -> hard fail")
            if on_step:
                on_step(step)
            break
        if outcome.kind == OUT_COMMIT and outcome.agent:
            incoming = IncomingEdge(from_agent=current_agent)
            pending_edge = (outcome.predicate or "", outcome.label or "")
            log.info("  -> commit %s  [%s]  (attempts=%d)",
                     outcome.agent, outcome.predicate, outcome.attempt_count)
            if on_step:
                on_step(step)
            current_agent = outcome.agent
            continue
        # Defensive: unknown outcome
        final_status = "voluntary_early_stop"
        if on_step:
            on_step(step)
        break
    else:
        # Loop exhausted MAX_HOP_COUNT without a terminal step.
        if trace.steps:
            trace.steps[-1].termination = Termination(True, "max_hop")
            if on_step:
                on_step(trace.steps[-1])
        log.error("max hop count (%d) exceeded", MAX_HOP_COUNT)

    trace.capabilities_covered = sorted(covered)
    trace.final_status = final_status
    trace.final_output = raw_history[-1] if raw_history else ""
    return RunOutput(trace, eval_log, ok=(final_status == "completed"),
                     reason=final_status)
