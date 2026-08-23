"""End-to-end orchestration loop (plan.md §9), with termination (§7) and loop
safety (§8) wired in — plus a resumable extension so a paused or hop-limited
run isn't a dead end.

    entry_agent <- recall -> select_process -> pooled nodeBonus argmax   [§1]
    loop (bounded by a hop budget):
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

Resumability
------------
A run that pauses for one of two reasons is not final:

  * ``voluntary_early_stop`` — the model itself decided it needed more input
    before proposing the next hop. ``current_agent`` already executed; what's
    missing is a decision for what comes after it.
  * ``max_hop_exceeded`` — the hop budget ran out mid-flight. The *next*
    agent to run was already decided (``current_agent`` was advanced) but
    never executed.

Both cases capture a :class:`LoopState` snapshot on the returned
:class:`RunOutput` (``resume_state``). :func:`continue_orchestration` takes
that snapshot plus additional human-provided context, folds the context in at
the right point for each case, and resumes the same loop with a fresh hop
budget — rather than restarting the whole case from scratch.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set, Tuple

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

# Reasons a paused run can be resumed from. Anything else (completed,
# session_retry_exceeded) is final.
RESUMABLE_REASONS = {"voluntary_early_stop", "max_hop_exceeded"}


@dataclass
class LoopState:
    """Everything needed to resume the hop loop from where it paused.

    Not serialized to disk — this lives only in-process (the webui's
    TaskRegistry holds it in memory against a task_id) for the lifetime of a
    single case's back-and-forth. It is *not* the audit record; ``trace`` and
    ``eval_log`` inside it are the same objects being built up across
    resumptions and are what eventually gets persisted.
    """

    kg: KGData
    query: KGQueryBackend
    provider: LLMProvider
    domain: DomainAgentExecutor
    brief_agent: BriefAgent
    task: str
    task_type_label: str
    required: Set[str]
    covered: Set[str]
    raw_history: List[str]
    trace_summary: List[str]
    incoming: Optional[IncomingEdge]
    pending_edge: Tuple[str, str]
    current_agent: str
    trace: Trace
    eval_log: EvalLog
    last_brief: Optional[str] = None
    hops_used: int = 0
    # True  -> current_agent already executed; its TraceStep is trace.steps[-1].
    #          Resuming means re-running only the hop-decision session for it.
    # False -> current_agent still needs to be executed (domain step first).
    awaiting_decision: bool = False


class RunOutput:
    """Bundle returned by :func:`run_orchestration` / :func:`continue_orchestration`."""

    def __init__(self, trace: Trace, eval_log: EvalLog, ok: bool, reason: str,
                 resume_state: Optional[LoopState] = None) -> None:
        self.trace = trace
        self.eval_log = eval_log
        self.ok = ok
        self.reason = reason
        # Present only when `reason` is in RESUMABLE_REASONS.
        self.resume_state = resume_state

    @property
    def resumable(self) -> bool:
        return self.resume_state is not None


def _covered_required(kg: KGData, agent: str, required: set, already: set) -> List[str]:
    """Required capabilities this agent newly covers."""
    handled = kg.agent_handles.get(agent, set())
    return sorted((handled & required) - already)


def _finalize(out: RunOutput, state: LoopState) -> RunOutput:
    out.trace.capabilities_covered = sorted(state.covered)
    out.trace.final_output = state.raw_history[-1] if state.raw_history else ""
    out.trace.final_status = out.reason
    return out


def _run_from(state: LoopState, on_step: Optional[Callable[[TraceStep], None]],
              hop_budget: int) -> RunOutput:
    """Run (or resume) the hop loop for up to ``hop_budget`` more hops."""
    hop = state.hops_used
    end_hop = state.hops_used + hop_budget

    while hop < end_hop:
        if state.awaiting_decision:
            # Resuming a voluntary-stop: the step for current_agent already
            # exists (with additional context folded into last_brief by the
            # caller) — only the hop-decision needs re-running. It was
            # already emitted via on_step() in the run that first paused, so
            # this iteration must not re-emit it (that would duplicate the
            # card in any UI rendering these events) — only genuinely new
            # steps get emitted below.
            step = state.trace.steps[-1]
            step_already_emitted = True
            state.awaiting_decision = False
        else:
            step_already_emitted = False
            raw_output = state.domain.run(state.current_agent, state.task, state.raw_history)
            brief = state.brief_agent.summarize(state.current_agent, raw_output)
            state.raw_history.append(raw_output)
            state.last_brief = brief

            newly = _covered_required(state.kg, state.current_agent, state.required, state.covered)
            state.covered.update(newly)
            state.trace_summary.append(state.current_agent)

            pred_used, pred_label = ("", "")
            if state.incoming is not None:
                pred_used, pred_label = state.pending_edge

            step = TraceStep(
                step_index=hop,
                agent=state.current_agent,
                capability_covered=", ".join(newly),
                predicate_used=pred_used,
                predicate_label=pred_label,
                incoming_edge=state.incoming,
                brief=brief,
                attempt_count=0,
                raw_output=raw_output,
            )
            state.trace.steps.append(step)
            log.info("hop %d: %s  covers[%s]  (covered %d/%d)",
                     hop, state.current_agent, ", ".join(newly) or "-",
                     len(state.covered), len(state.required))

            if state.required.issubset(state.covered):
                step.termination = Termination(True, "coverage_satisfied")
                if on_step:
                    on_step(step)
                log.success("coverage satisfied -> completed")
                state.hops_used = hop + 1
                return _finalize(RunOutput(state.trace, state.eval_log, True, "completed"), state)

        session = HopDecisionSession(
            kg=state.kg, query=state.query, provider=state.provider, eval_log=state.eval_log,
            session_id=f"{uuid.uuid4().hex[:8]}",
        )
        outcome = session.run(
            task=state.task, task_type_label=state.task_type_label,
            current_agent=state.current_agent, required=list(state.required),
            covered=state.covered, last_brief=state.last_brief,
            trace_summary=list(state.trace_summary),
        )
        step.attempt_count = outcome.attempt_count

        if outcome.kind == OUT_TERMINATE:
            step.termination = Termination(True, "llm_voluntary")
            if on_step and not step_already_emitted:
                on_step(step)
            log.warning("orchestrator voluntarily terminated (early stop)")
            state.hops_used = hop + 1
            state.awaiting_decision = True
            return _finalize(
                RunOutput(state.trace, state.eval_log, False, "voluntary_early_stop", resume_state=state),
                state,
            )
        if outcome.kind == OUT_FAILED:
            step.termination = Termination(True, "session_retry_exceeded")
            if on_step and not step_already_emitted:
                on_step(step)
            log.error("session retry cap exceeded -> hard fail")
            state.hops_used = hop + 1
            return _finalize(RunOutput(state.trace, state.eval_log, False, "session_retry_exceeded"), state)
        if outcome.kind == OUT_COMMIT and outcome.agent:
            state.incoming = IncomingEdge(from_agent=state.current_agent)
            state.pending_edge = (outcome.predicate or "", outcome.label or "")
            log.info("  -> commit %s  [%s]  (attempts=%d)",
                     outcome.agent, outcome.predicate, outcome.attempt_count)
            if on_step and not step_already_emitted:
                on_step(step)
            state.current_agent = outcome.agent
            state.awaiting_decision = False
            hop += 1
            continue

        # Defensive: unknown outcome kind.
        step.termination = Termination(True, "llm_voluntary")
        if on_step and not step_already_emitted:
            on_step(step)
        state.hops_used = hop + 1
        state.awaiting_decision = True
        return _finalize(
            RunOutput(state.trace, state.eval_log, False, "voluntary_early_stop", resume_state=state),
            state,
        )

    # Hop budget exhausted without a terminal decision this round.
    if state.trace.steps:
        state.trace.steps[-1].termination = Termination(True, "max_hop")
        if on_step:
            on_step(state.trace.steps[-1])
    log.error("hop budget (%d) exceeded for this run/continuation", hop_budget)
    state.hops_used = hop
    state.awaiting_decision = False  # current_agent is decided but not yet executed
    return _finalize(
        RunOutput(state.trace, state.eval_log, False, "max_hop_exceeded", resume_state=state),
        state,
    )


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
    hop_budget: int = MAX_HOP_COUNT,
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

    state = LoopState(
        kg=kg, query=query, provider=provider, domain=domain, brief_agent=brief_agent,
        task=task, task_type_label=task_type_label, required=required, covered=set(),
        raw_history=[], trace_summary=[], incoming=None, pending_edge=("", ""),
        current_agent=entry.entry_agent, trace=trace, eval_log=eval_log,
    )
    return _run_from(state, on_step, hop_budget)


def continue_orchestration(
    state: LoopState,
    additional_info: str,
    *,
    on_step: Optional[Callable[[TraceStep], None]] = None,
    hop_budget: int = MAX_HOP_COUNT,
) -> RunOutput:
    """Resume a paused run with human-provided context folded in.

    Where the context lands depends on why the run paused:

      * ``awaiting_decision`` (voluntary_early_stop) — folded into
        ``last_brief``, which feeds directly into the hop-decision session's
        system prompt (see ``agents/prompts.py::orch_state_block``) as
        "Brief from the current agent's output". The model re-decides with
        the human's input in hand.
      * otherwise (max_hop_exceeded) — folded into the tail of
        ``raw_history``, which is what the *next* domain agent's context
        provider reads (``LastOutputOnly`` shows only the most recent
        entry, so appending here — not as a new list item — keeps it from
        silently overriding the last agent's actual output).
    """
    note = f"\n\n[Additional information provided by clinical staff]\n{additional_info.strip()}"
    if state.awaiting_decision:
        state.last_brief = (state.last_brief or "") + note
    elif state.raw_history:
        state.raw_history[-1] = state.raw_history[-1] + note
    else:
        state.raw_history.append(additional_info.strip())
    return _run_from(state, on_step, hop_budget)
