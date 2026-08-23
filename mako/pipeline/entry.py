"""Task entry / first-agent selection (plan.md §1).

Adapted from v2's pipeline. v2 walked a full ordered chain (a DP over
``sequenceIndex``-ordered steps) to produce a sequence and picked the first
agent as a side effect. v3 keeps only what it needs: the **entry agent**.
Everything downstream of the first hop is decided progressively by the
orchestrator loop (§4), not precomputed here.

Two stages:

  1. **Process selection** (v2 Stage 2, reused unchanged in logic) —
     :func:`select_process` scores each ``TaskType`` by the summed affinity of
     the required capabilities recall surfaces, and returns the best process
     plus the capabilities it matched. Neither this nor capability affinity
     depends on ordering, so removing ``sequenceIndex`` (loader change) does not
     affect it. The selected process's required-capability *set* is what §6/§7
     later use for the coverage check, so this stage is a genuine dependency,
     not just an entry-agent mechanism.

  2. **Entry-agent selection** (§1, Change 2 — Option B, pooled candidates) —
     the candidate pool is the union of all agents handling *any* required
     capability (no privileged "anchor" capability). Each candidate is scored by
     ``nodeBonus`` only — ``W_EDGE`` does not apply at entry because there is no
     predecessor to transition *from*. The argmax (alphabetical tie-break) is
     the entry agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from kg.loader import KGData
from pipeline.recall import RecallResult

# Node-scoring weights, identical to v2. W_EDGE (2.0 in v2) is deliberately
# absent: it only ever scored a transition from a predecessor, and the entry
# hop has none (plan.md §1, Change 2).
_W_RECALLED = 1.0    # this agent was semantically recalled
_W_SPECIALTY = 0.5   # agent matches the process's dominant specialty


@dataclass
class EntryResult:
    ok: bool
    reason: str
    process: Optional[str] = None
    process_label: str = ""
    entry_agent: Optional[str] = None
    required: List[str] = field(default_factory=list)          # sorted required set
    matched_capabilities: List[str] = field(default_factory=list)
    candidates: List[str] = field(default_factory=list)         # pooled, sorted
    dominant_specialty: Optional[str] = None
    recalled: bool = False                                      # entry agent recalled?


# ----------------------------------------------------------------------
# Stage 2: pick the Process (v2 Stage 2, logic unchanged)
# ----------------------------------------------------------------------

def _capability_affinity(recall: RecallResult, kg: KGData) -> Dict[str, float]:
    """How strongly each capability is implied by recall.

    Direct capability hits count fully; a capability is also implied (at half
    weight) by any recalled agent that handles it, so recall of *who* can act
    still steers process selection.
    """
    affinity: Dict[str, float] = {}
    for cap, score in recall.capabilities:
        affinity[cap] = max(affinity.get(cap, 0.0), score)
    for agent, score in recall.agents:
        for cap in kg.agent_handles.get(agent, set()):
            affinity[cap] = max(affinity.get(cap, 0.0), 0.5 * score)
    return affinity


def select_process(recall: RecallResult, kg: KGData) -> Tuple[Optional[str], List[str]]:
    """Return (best task-type, matched capabilities) or (None, []).

    Score = summed affinity of the required capabilities the process covers.
    Ties break toward more matched capabilities, then a tighter (shorter)
    process, then alphabetical — all deterministic. ``required`` is now an
    unordered set (sequenceIndex removed), so we iterate it sorted to keep the
    matched list deterministic.
    """
    affinity = _capability_affinity(recall, kg)
    best: Optional[Tuple[float, int, int, str]] = None
    best_matched: List[str] = []
    for tt in kg.task_types:
        required = kg.task_requires.get(tt, set())
        matched = [c for c in sorted(required) if affinity.get(c, 0.0) > 0.0]
        if not matched:
            continue
        score = sum(affinity[c] for c in matched)
        key = (score, len(matched), -len(required), tt)
        if best is None or key > best:
            best = key
            best_matched = matched
    if best is None:
        return None, []
    return best[3], best_matched


# ----------------------------------------------------------------------
# Stage: entry-agent selection (plan.md §1, Change 2)
# ----------------------------------------------------------------------

def _dominant_specialty(kg: KGData, required: Set[str]) -> Optional[str]:
    """Specialty of the process, inferred from its unambiguous capabilities.

    Capabilities with exactly one performer are the anchors; their most common
    specialty is the process's centre of gravity and gently biases ambiguous
    candidates toward staying in-domain. Alphabetical tie-break among equally
    common specialties (``max(sorted(...))``).
    """
    counts: Dict[str, int] = {}
    for cap in required:
        performers = kg.agents_by_capability.get(cap, [])
        if len(performers) == 1:
            spec = kg.agent_specialty.get(performers[0], "")
            if spec:
                counts[spec] = counts.get(spec, 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=lambda s: counts[s])


def select_entry_agent(recall: RecallResult, kg: KGData,
                       process: Optional[str] = None) -> EntryResult:
    """Pick the single entry agent for the recalled task (plan.md §1).

    Pooled candidates = every agent handling any required capability; scored by
    ``nodeBonus`` only; argmax with alphabetical tie-break.
    """
    matched: List[str] = []
    if process is None:
        process, matched = select_process(recall, kg)
    else:
        matched = sorted(kg.task_requires.get(process, set()))

    if process is None:
        return EntryResult(
            ok=False,
            reason="No process matched the recalled capabilities — returning no "
                   "entry agent rather than a guessed one.",
        )

    required_set = kg.task_requires.get(process, set())
    required = sorted(required_set)
    process_label = kg.task_label.get(process, process)
    if not required_set:
        return EntryResult(ok=False, reason=f"Process {process!r} has no required capabilities.",
                           process=process, process_label=process_label,
                           matched_capabilities=matched)

    # Pooled candidate set: union of performers over *all* required capabilities
    # (no anchor capability — plan.md §1, Change 2, Option B).
    candidate_set: Set[str] = set()
    for cap in required_set:
        candidate_set.update(kg.agents_by_capability.get(cap, []))
    candidates = sorted(candidate_set)
    if not candidates:
        return EntryResult(
            ok=False,
            reason=f"Process {process!r} has required capabilities with no "
                   "performing agents.",
            process=process, process_label=process_label,
            required=required, matched_capabilities=matched,
        )

    recalled_agents = set(recall.agent_uris)
    dominant = _dominant_specialty(kg, required_set)

    def node_bonus(agent: str) -> float:
        b = 0.0
        if agent in recalled_agents:
            b += _W_RECALLED
        if dominant and kg.agent_specialty.get(agent) == dominant:
            b += _W_SPECIALTY
        return b

    # argmax over the pooled candidates; `sorted` first gives the alphabetical
    # tie-break used deterministically throughout v1/v2/v3.
    entry_agent = max(candidates, key=node_bonus)

    return EntryResult(
        ok=True,
        reason="ok",
        process=process,
        process_label=process_label,
        entry_agent=entry_agent,
        required=required,
        matched_capabilities=matched,
        candidates=candidates,
        dominant_specialty=dominant,
        recalled=(entry_agent in recalled_agents),
    )
