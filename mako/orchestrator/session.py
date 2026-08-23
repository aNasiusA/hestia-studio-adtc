"""One hop-decision session (plan.md §4) — **LangGraph StateGraph**.

This is the LangGraph migration of v3's hop-decision session. The semantics are
identical to v3; the mechanism changes from "prompt the model to emit one JSON
action, parse the last JSON object" to native provider function-calling driven by
an explicit ``StateGraph``:

  * The four actions — ``get_valid_transitions``, ``validate_decision``,
    ``commit``, ``terminate`` — are LangChain ``@tool`` schemas bound onto the
    model via ``bind_tools`` (plan.md §4). The model *calls* a tool; the harness
    executes real code against the real graph.
  * The loop is an explicit ``StateGraph`` (``agent`` → ``tools`` → back), **not**
    an ``AgentExecutor`` or any auto-looping agent. ``AgentExecutor`` would decide
    internally when to accept a final answer — that would break the action-masking
    gate. Here the gate is our own node logic in :meth:`_tools`.
  * Session chat history = the graph's growing ``messages`` list (a fresh list per
    session, reset on commit — same semantics as v3). Failed ``validate_decision``
    and rejected ``commit`` attempts stay in the messages, so later rounds in the
    same session see why earlier ones failed.

**Action-masking gate (harness-owned, plan.md §4):** a ``commit`` is accepted
only if the most recent action was ``validate_decision(agent)`` returning
``is_valid=true`` for that exact agent. Otherwise the commit is rejected (a
rejection ToolMessage is fed back) and the session continues, subject to the
retry cap. This decision lives in :meth:`_tools`, never in framework control flow.

Every ``validate_decision`` call — accepted or not — appends one record to the
separate EvalLog (§10). On commit/terminate the session ends; its messages are
discarded and only the resolved outcome folds into the Trace.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from langchain_core.messages import (BaseMessage, HumanMessage, SystemMessage,
                                     ToolMessage)
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from typing_extensions import Annotated, TypedDict

try:  # add_messages reducer lives here across langgraph versions
    from langgraph.graph.message import add_messages
except Exception:  # pragma: no cover - fallback for older layouts
    from langgraph.graph import add_messages  # type: ignore

from agents.llm import LLMProvider
from agents.prompts import (assemble_orchestrator_system, orch_state_block,
                            orch_termination_block, orch_transitions_block)
from kg.loader import KGData
from kg.query import KGQueryBackend, Transition
from orchestrator.constants import SESSION_RETRY_CAP
from orchestrator.trace import EvalLog, EvalLogRecord

# Session outcome kinds (unchanged from v3)
OUT_COMMIT = "commit"
OUT_TERMINATE = "terminate"
OUT_FAILED = "session_retry_exceeded"


@dataclass
class SessionOutcome:
    kind: str                          # commit | terminate | session_retry_exceeded
    agent: Optional[str] = None
    predicate: Optional[str] = None
    label: Optional[str] = None
    attempt_count: int = 0


# ----------------------------------------------------------------------
# Tool schemas (plan.md §4). These declare the function-calling surface bound
# via bind_tools; the *bodies* are never executed — the session's `tools` node
# runs the real graph code so the action-masking gate stays harness-owned.
# ----------------------------------------------------------------------
@tool
def get_valid_transitions() -> str:
    """Re-fetch the current agent's valid outgoing transition edges from the
    knowledge graph. Takes no arguments; returns the list of allowed next agents
    with their edge predicate and label."""
    raise NotImplementedError  # executed by HopDecisionSession._tools


@tool
def validate_decision(candidate_agent: str) -> str:
    """Dry-run check whether handing the case to candidate_agent is a valid named
    transition out of the current agent. Returns is_valid plus a reason. Call this
    before commit — a commit is only accepted right after this returns
    is_valid=true for that exact agent."""
    raise NotImplementedError  # executed by HopDecisionSession._tools


@tool
def commit(agent: str) -> str:
    """Commit the next agent to hand the case to. REQUIRED PROTOCOL: only accepted
    if your most recent action was validate_decision(agent) returning
    is_valid=true for that exact agent; otherwise it is rejected and you must try
    again."""
    raise NotImplementedError  # executed by HopDecisionSession._tools


@tool
def terminate() -> str:
    """End the run now (voluntary early stop). Takes no arguments. Use only when
    the case genuinely cannot progress toward the remaining required
    capabilities."""
    raise NotImplementedError  # executed by HopDecisionSession._tools


_TOOLS = [get_valid_transitions, validate_decision, commit, terminate]


class SessionState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    rounds: int                                   # model inferences taken (retry rounds)
    last_validation: Optional[Tuple[str, bool]]   # (candidate, is_valid) most recent
    outcome: Optional[dict]                       # set once terminal


def _transition_dicts(transitions: List[Transition]) -> List[dict]:
    return [{"agent": t.agent, "predicate": t.predicate, "label": t.label}
            for t in transitions]


class HopDecisionSession:
    """A single next-agent decision round, run as a compiled ``StateGraph``.

    Constructed fresh per hop by the outer loop; :meth:`run` executes one graph to
    completion and returns the resolved :class:`SessionOutcome`.
    """

    def __init__(self, *, kg: KGData, query: KGQueryBackend,
                 provider: LLMProvider, eval_log: EvalLog,
                 session_id: str) -> None:
        self.kg = kg
        self.query = query
        self.eval_log = eval_log
        self.session_id = session_id
        # Native function-calling: bind the KG tools onto the LangChain model.
        self.model = provider.chat_model.bind_tools(_TOOLS)
        self.system = assemble_orchestrator_system()

        # Per-run context, set in run() before the graph is invoked.
        self.current_agent = ""
        self.transitions: List[Transition] = []
        self._validate_ordinal = 0
        self._last_brief: Optional[str] = None

        self.graph = self._build_graph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------
    def _build_graph(self):
        g = StateGraph(SessionState)
        g.add_node("agent", self._agent)
        g.add_node("tools", self._tools)
        g.add_node("nudge", self._nudge)
        g.add_node("fail", self._fail)
        g.set_entry_point("agent")
        g.add_conditional_edges(
            "agent", self._route_after_agent,
            {"tools": "tools", "nudge": "nudge", "fail": "fail"},
        )
        g.add_conditional_edges(
            "tools", self._route_after_tools,
            {"agent": "agent", "fail": "fail", END: END},
        )
        g.add_edge("nudge", "agent")
        g.add_edge("fail", END)
        return g.compile()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    def _agent(self, state: SessionState) -> dict:
        """One model inference (a retry round)."""
        ai = self.model.invoke(state["messages"])
        return {"messages": [ai], "rounds": state["rounds"] + 1}

    def _route_after_agent(self, state: SessionState) -> str:
        ai = state["messages"][-1]
        if getattr(ai, "tool_calls", None):
            return "tools"
        # The model answered in prose without calling a tool. Nudge and retry
        # (this consumes a round), unless the retry cap is already reached.
        if state["rounds"] >= SESSION_RETRY_CAP:
            return "fail"
        return "nudge"

    def _nudge(self, state: SessionState) -> dict:
        return {"messages": [HumanMessage(content=(
            "You did not call a tool. Respond by CALLING EXACTLY ONE TOOL "
            "(get_valid_transitions, validate_decision, commit, or terminate)."
        ))]}

    def _tools(self, state: SessionState) -> dict:
        """Execute the model's tool call(s) against the real graph and enforce the
        action-masking gate. This is the harness-owned decision logic (plan.md
        §4) — deliberately not delegated to a prebuilt ToolNode / AgentExecutor.
        """
        ai = state["messages"][-1]
        new_msgs: List[BaseMessage] = []
        last_validation = state.get("last_validation")
        outcome: Optional[dict] = None

        for call in getattr(ai, "tool_calls", []) or []:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            cid = call.get("id")

            if name == "get_valid_transitions":
                new_msgs.append(ToolMessage(
                    content=self._render_transitions(), tool_call_id=cid))

            elif name == "validate_decision":
                cand = str(args.get("candidate_agent", "")).strip()
                self._validate_ordinal += 1
                v = self.query.validate_decision(self.current_agent, cand)
                # §10: log EVERY validate_decision call, accepted or rejected.
                self.eval_log.add(EvalLogRecord(
                    session_id=self.session_id,
                    attempt_number=self._validate_ordinal,
                    valid_transition_list=_transition_dicts(self.transitions),
                    previous_output=self._last_brief or "",
                    selected_transition=cand,
                    is_valid_transition=v.is_valid,
                    failure_reason=v.reason,
                ))
                last_validation = (cand, v.is_valid)
                res = ("is_valid=true" if v.is_valid
                       else f"is_valid=false — {v.reason}")
                new_msgs.append(ToolMessage(
                    content=f"validate_decision({cand}): {res}", tool_call_id=cid))

            elif name == "commit":
                agent = str(args.get("agent", "")).strip()
                # Action-masking gate: accept only if the most recent action was a
                # successful validate_decision for this exact agent.
                if (last_validation is not None
                        and last_validation[0] == agent and last_validation[1]):
                    pred, label = self._edge_for(agent)
                    outcome = {
                        "kind": OUT_COMMIT, "agent": agent,
                        "predicate": pred, "label": label,
                        "attempt_count": state["rounds"],
                    }
                    new_msgs.append(ToolMessage(
                        content=f"commit({agent}) accepted.", tool_call_id=cid))
                else:
                    new_msgs.append(ToolMessage(content=(
                        "commit REJECTED: a commit is only accepted immediately "
                        "after validate_decision returns is_valid=true for that "
                        "exact agent. Validate the candidate first, then commit."
                    ), tool_call_id=cid))

            elif name == "terminate":
                outcome = {"kind": OUT_TERMINATE, "attempt_count": state["rounds"]}
                new_msgs.append(ToolMessage(
                    content="terminate accepted (voluntary early stop).",
                    tool_call_id=cid))

            else:  # defensive: unknown tool name
                new_msgs.append(ToolMessage(
                    content=f"Unknown tool {name!r}.", tool_call_id=cid))

        updates: dict = {"messages": new_msgs, "last_validation": last_validation}
        if outcome is not None:
            updates["outcome"] = outcome
        return updates

    def _route_after_tools(self, state: SessionState) -> str:
        if state.get("outcome") is not None:
            return END
        if state["rounds"] >= SESSION_RETRY_CAP:
            return "fail"
        return "agent"

    def _fail(self, state: SessionState) -> dict:
        # Retry cap exceeded -> hard-fail as a diagnostic (not an exception).
        return {"outcome": {"kind": OUT_FAILED,
                            "attempt_count": SESSION_RETRY_CAP}}

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self, *, task: str, task_type_label: str, current_agent: str,
            required: List[str], covered: set, last_brief: Optional[str],
            trace_summary: List[str]) -> SessionOutcome:
        self.current_agent = current_agent
        # Auto-injected on turn one; separately re-fetchable via get_valid_transitions.
        self.transitions = self.query.get_valid_transitions(current_agent)
        self._validate_ordinal = 0
        self._last_brief = last_brief

        user = self._initial_user(
            task=task, task_type_label=task_type_label,
            current_agent=current_agent, required=required,
            covered=covered, last_brief=last_brief, trace_summary=trace_summary,
        )
        init: SessionState = {
            "messages": [SystemMessage(content=self.system),
                         HumanMessage(content=user)],
            "rounds": 0,
            "last_validation": None,
            "outcome": None,
        }
        # Generous recursion budget; our own round counter enforces the real cap
        # (each round is up to two supersteps: agent -> tools/nudge).
        final = self.graph.invoke(
            init, config={"recursion_limit": SESSION_RETRY_CAP * 3 + 10})

        oc = final.get("outcome") or {"kind": OUT_FAILED,
                                      "attempt_count": SESSION_RETRY_CAP}
        return SessionOutcome(
            kind=oc["kind"], agent=oc.get("agent"),
            predicate=oc.get("predicate"), label=oc.get("label"),
            attempt_count=oc.get("attempt_count", 0),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _initial_user(self, *, task: str, task_type_label: str,
                      current_agent: str, required: List[str], covered: set,
                      last_brief: Optional[str],
                      trace_summary: List[str]) -> str:
        current_label = self.kg.agent_label.get(current_agent, current_agent)
        coverage_complete = set(required).issubset(set(covered))
        blocks = [
            orch_state_block(
                task=task, task_type_label=task_type_label,
                current_agent_label=current_label, required=required,
                covered=sorted(covered), last_brief=last_brief,
                trace_summary=trace_summary,
            ),
            orch_transitions_block(self.transitions),
            orch_termination_block(coverage_complete=coverage_complete),
            "Decide your next action now by calling exactly one tool.",
        ]
        return "\n\n".join(blocks)

    def _render_transitions(self) -> str:
        if not self.transitions:
            return ("Valid transitions out of the current agent: NONE. The current "
                    "agent is a terminal node — you can only terminate.")
        lines = ["Valid transitions out of the current agent:"]
        for i, t in enumerate(self.transitions, 1):
            lines.append(f"  {i}. -> {t.agent}   [{t.predicate}] {t.label}")
        return "\n".join(lines)

    def _edge_for(self, agent: str) -> Tuple[str, str]:
        for t in self.transitions:
            if t.agent == agent:
                return t.predicate, t.label
        return "", ""
