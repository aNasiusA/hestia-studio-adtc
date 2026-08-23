"""Prompt assembly for v3's LLM roles (plan.md §4, §5, §12).

Three prompt families, each assembled from small, independently-testable pieces:

  * **Domain agent** (§12) — a shared assembly pattern (role + specialty +
    capabilities + tools + injected context), not hand-authored per agent. One
    concrete strategy chosen for the demo; still swappable.
  * **Brief Agent** (§5) — narrowly framed around *next-step-decision support*,
    not general summarization.
  * **Orchestrator** (§4) — assembled from independently-testable blocks:
    role/identity, current-state, valid-transitions, decision-format,
    termination-criteria. Each is a pure function of its inputs so it can be
    tested in isolation, then concatenated at call time.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from kg.loader import KGData
from kg.query import Transition


def _spaced(local_name: str) -> str:
    """`cap_AssessChestPain` -> `Assess Chest Pain` (drop the type prefix)."""
    core = local_name.split("_", 1)[1] if "_" in local_name else local_name
    out, prev_lower = [], False
    for ch in core:
        if ch.isupper() and prev_lower:
            out.append(" ")
        out.append(ch)
        prev_lower = ch.islower()
    return "".join(out)


# ----------------------------------------------------------------------
# Domain agent (§12)
# ----------------------------------------------------------------------
def build_domain_system_prompt(kg: KGData, agent: str) -> str:
    label = kg.agent_label.get(agent, agent)
    specialty = kg.agent_specialty.get(agent, "")
    caps = sorted(kg.agent_handles.get(agent, set()))
    tools = sorted(kg.agent_owns.get(agent, set()))
    cap_txt = ", ".join(_spaced(c) for c in caps) or "(none declared)"
    tool_txt = ", ".join(_spaced(t) for t in tools) or "(none)"
    return (
        f"You are the {label} agent, a {specialty} specialist operating as one "
        f"step inside a larger healthcare multi-agent workflow.\n"
        f"Your capabilities: {cap_txt}.\n"
        f"Tools available to you: {tool_txt}.\n\n"
        "You handle only your own step of the clinical pathway. Do the work your "
        "capabilities cover and nothing outside them — you do not decide who acts "
        "next; an orchestrator handles hand-offs. Produce a concise, clinically "
        "plausible result (3-5 sentences): what you did, the key finding, and the "
        "current status of the case as you hand it back."
    )


def build_domain_user_prompt(task: str, prior_context: Optional[str]) -> str:
    parts = [f"Original task:\n{task}\n"]
    if prior_context:
        parts.append(f"Context from the preceding step:\n{prior_context}\n")
    parts.append("Produce your step's output.")
    return "\n".join(parts)


# ----------------------------------------------------------------------
# Brief Agent (§5)
# ----------------------------------------------------------------------
def build_brief_system_prompt(extra_instructions: str = "") -> str:
    base = (
        "You are the Brief Agent in a knowledge-graph-grounded orchestrator. "
        "After a domain agent runs, you distil its raw output into a short brief "
        "whose SOLE purpose is to help the orchestrator decide the NEXT agent to "
        "hand the case to. This is next-step-decision support, not general "
        "summarization.\n\n"
        "Extract and state plainly:\n"
        "  - what this agent accomplished,\n"
        "  - the current case status signal (e.g. success / needs-input / "
        "urgent / error),\n"
        "  - what kind of step the case now calls for next.\n\n"
        "Be terse and decision-oriented. 2-4 sentences. Do not invent facts not "
        "present in the raw output."
    )
    return base + (f"\n\n{extra_instructions}" if extra_instructions else "")


def build_brief_user_prompt(agent_label: str, raw_output: str) -> str:
    return (
        f"Raw output from the {agent_label} agent:\n"
        f"------------------------------------------\n{raw_output}\n"
        f"------------------------------------------\n\n"
        "Write the decision-oriented brief."
    )


# ----------------------------------------------------------------------
# Orchestrator blocks (§4) — each independently testable
# ----------------------------------------------------------------------
def orch_role_block() -> str:
    return (
        "You are the Orchestrator in a knowledge-graph-grounded multi-agent "
        "system. At each hop you decide which agent should act next, choosing "
        "ONLY from the named transition edges the graph allows out of the "
        "current agent. You do not invent agents or edges. Your goal is to route "
        "the case so that all of the task's required capabilities get covered, "
        "using the edge semantics (why each edge exists) to pick well at branch "
        "points."
    )


def orch_state_block(*, task: str, task_type_label: str, current_agent_label: str,
                     required: Sequence[str], covered: Sequence[str],
                     last_brief: Optional[str],
                     trace_summary: Sequence[str]) -> str:
    req = ", ".join(_spaced(c) for c in required) or "(none)"
    cov = ", ".join(_spaced(c) for c in covered) or "(none yet)"
    remaining = [c for c in required if c not in set(covered)]
    rem = ", ".join(_spaced(c) for c in remaining) or "(none — coverage complete)"
    lines = [
        f"Task: {task}",
        f"Process (task type): {task_type_label}",
        f"Required capabilities: {req}",
        f"Covered so far: {cov}",
        f"Still uncovered: {rem}",
        f"Current agent (you are deciding who follows it): {current_agent_label}",
    ]
    if trace_summary:
        lines.append("Path so far: " + " -> ".join(trace_summary))
    if last_brief:
        lines.append(f"\nBrief from the current agent's output:\n{last_brief}")
    return "\n".join(lines)


def orch_transitions_block(transitions: List[Transition]) -> str:
    if not transitions:
        return (
            "Valid transitions out of the current agent: NONE. The current agent "
            "is a terminal node in the graph — you can only TERMINATE."
        )
    lines = ["Valid transitions out of the current agent (your only options):"]
    for i, t in enumerate(transitions, 1):
        lines.append(f"  {i}. -> {t.agent}   [{t.predicate}] {t.label}")
    return "\n".join(lines)


def orch_decision_format_block() -> str:
    return (
        "Decide by CALLING EXACTLY ONE TOOL per turn (native function-calling — do "
        "not describe the call in prose, actually invoke it). The tools available "
        "to you:\n"
        "  get_valid_transitions()\n"
        "      Re-fetch the current agent's valid transitions from the graph.\n"
        "  validate_decision(candidate_agent=\"<AgentName>\")\n"
        "      Dry-run check a candidate before committing. Returns is_valid + a "
        "reason.\n"
        "  commit(agent=\"<AgentName>\")\n"
        "      Commit the next agent. REQUIRED PROTOCOL: a commit is only accepted "
        "if your most recent action was validate_decision for that exact agent and "
        "it returned is_valid=true. Otherwise the commit is rejected and you must "
        "try again.\n"
        "  terminate()\n"
        "      End the run now (voluntary early stop).\n\n"
        "Use the exact agent local-names shown in the transitions list."
    )


def orch_termination_block(*, coverage_complete: bool) -> str:
    if coverage_complete:
        return (
            "Termination: all required capabilities are already covered. You may "
            "TERMINATE now; the harness will also stop on its own (coverage is a "
            "safety net)."
        )
    return (
        "Termination criteria: keep routing until every required capability is "
        "covered. You may TERMINATE early if the case genuinely cannot progress "
        "toward the remaining capabilities, but this is recorded as an early stop, "
        "so prefer to continue while a productive transition exists."
    )


def assemble_orchestrator_system() -> str:
    """The stable system prompt: role + decision format (mechanism)."""
    return "\n\n".join([orch_role_block(), orch_decision_format_block()])
