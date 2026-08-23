"""Two separate persistent streams (plan.md §6 and §10).

  * **Trace** (§6) — the audit record of what the run actually did: one
    :class:`TraceStep` per hop, plus run-level coverage and final status.
  * **EvalLog** (§10) — a *separate* stream, one :class:`EvalLogRecord` per
    ``validate_decision`` call (including rejected ones), for offline
    judge/human evaluation of decision quality.

They are kept strictly apart. ``attempt_count`` on a TraceStep is the only bridge
field — it records how many tries the winning decision took, without carrying the
failed attempts themselves (those live only in the EvalLog).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ----------------------------------------------------------------------
# Trace (§6)
# ----------------------------------------------------------------------
@dataclass
class IncomingEdge:
    from_agent: str


@dataclass
class Termination:
    is_terminal: bool = False
    # coverage_satisfied | llm_voluntary | max_hop | session_retry_exceeded | None
    reason: Optional[str] = None


@dataclass
class TraceStep:
    step_index: int
    agent: str
    capability_covered: str                       # required caps this agent covers
    predicate_used: str                           # edge used to reach this agent
    predicate_label: str
    incoming_edge: Optional[IncomingEdge]         # None for the entry hop
    brief: str                                    # Brief Agent's output for this hop
    attempt_count: int                            # attempts within the session before commit
    raw_output: str = ""                          # domain agent's full generated text for this hop
    termination: Termination = field(default_factory=Termination)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.incoming_edge is None:
            d["incoming_edge"] = None
        return d


@dataclass
class Trace:
    task: str
    task_type: str                                # selected process τ (§1)
    steps: List[TraceStep] = field(default_factory=list)
    capabilities_required: List[str] = field(default_factory=list)
    capabilities_covered: List[str] = field(default_factory=list)
    # completed | max_hop_exceeded | session_retry_exceeded | voluntary_early_stop
    final_status: str = "completed"
    entry_agent: Optional[str] = None
    final_output: str = ""

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "task_type": self.task_type,
            "entry_agent": self.entry_agent,
            "capabilities_required": sorted(self.capabilities_required),
            "capabilities_covered": sorted(self.capabilities_covered),
            "final_status": self.final_status,
            "steps": [s.to_dict() for s in self.steps],
            "final_output": self.final_output,
        }


# ----------------------------------------------------------------------
# EvalLog (§10) — separate stream
# ----------------------------------------------------------------------
@dataclass
class EvalLogRecord:
    session_id: str
    attempt_number: int                           # ordinal within the session
    valid_transition_list: List[Dict[str, str]]   # [{agent, predicate, label}]
    previous_output: str                          # the Brief shown for this decision
    selected_transition: str
    is_valid_transition: bool
    failure_reason: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvalLog:
    """Append-only collection of eval records for the whole run."""

    records: List[EvalLogRecord] = field(default_factory=list)

    def add(self, record: EvalLogRecord) -> None:
        self.records.append(record)

    def to_list(self) -> List[dict]:
        return [r.to_dict() for r in self.records]
