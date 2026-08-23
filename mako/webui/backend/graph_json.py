"""Convert the v3-langraph healthcare KG into Cytoscape.js-shaped JSON.

Adapted from v2/viz/graph_json.py (`kg_to_cy`). v3-langraph's KGData differs
structurally in one way: `task_requires` is an *unordered* Set (v3
deliberately drops kg:sequenceIndex, see kg/loader.py's module docstring)
rather than v2's ordered list, so capability lists here are sorted for stable
output and `requires` edges carry no sequenceIndex.

Handoffs are projected as **nodes**, not agent->agent edges — one node plus two
half-edges each. The graph already models them that way (`kg:handoff_N a
kg:DelegationHandoff`), and it gives the per-edge attributes (`kg:condition`,
`kg:weight`, terminality) somewhere to live and something to click. Note this
makes the projection a *bipartite-ish* graph: agents never connect to agents
directly, always through a handoff.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from kg.loader import KGData

TOOLS_CLUSTER_ID = "domain:__tools"
SHARED = "__shared"


def _specialty_of_capability(kg: KGData, cap: str) -> str:
    specs = Counter(kg.agent_specialty.get(a, "") for a in kg.agents_by_capability.get(cap, []))
    specs.pop("", None)
    if not specs:
        return SHARED
    top = specs.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return SHARED  # handled across specialties
    return top[0][0]


def _specialty_of_process(kg: KGData, tt: str) -> str:
    specs: Counter = Counter()
    for cap in kg.task_requires.get(tt, set()):
        performers = kg.agents_by_capability.get(cap, [])
        if len(performers) == 1:
            specs[kg.agent_specialty.get(performers[0], "")] += 1
    specs.pop("", None)
    return specs.most_common(1)[0][0] if specs else SHARED


def handoff_node_id(src: str, predicate: str, dst: str) -> str:
    """Stable id for a handoff node.

    Deterministic, unlike the ``_eid()`` running counter used for edges (whose
    values depend on dict iteration order): the frontend resolves a trace hop
    to its handoff node by rebuilding this string, so the format is a contract.
    Its mirror is ``handoffNodeId()`` in webui/v2/src/lib/kgTypes.ts.
    """
    return f"handoff:{src}__{predicate}__{dst}"


def _handoff_classes(kg: KGData) -> List[Dict[str, Any]]:
    """Per-class legend vocabulary, keyed by predicate.

    Class and predicate are 1:1 in practice but that correspondence is nowhere
    stated in the graph, so it is recovered here via the reified instances and
    keyed on the predicate — the only identifier every transition is guaranteed
    to have. Unreified predicates still get a row, labelled by predicate name.
    """
    by_pred: Dict[str, Dict[str, Any]] = {}
    for e in kg.transitions:
        h = kg.handoff_by_pair.get((e.src, e.dst))
        entry = by_pred.setdefault(e.predicate, {
            "predicate": e.predicate,
            "label": h.class_label if h else e.predicate,
            "cls": h.cls if h else "",
            "isTerminal": h.is_terminal if h else None,
            "comment": kg.predicate_label(e.predicate),
            "count": 0,
            "conditions": set(),
        })
        entry["count"] += 1
        if h and h.condition:
            entry["conditions"].add(h.condition)
    out = []
    for entry in by_pred.values():
        entry["conditions"] = sorted(entry["conditions"])
        out.append(entry)
    # Descending count — kg-visualizer's legend ordering (buildLegend, :932).
    out.sort(key=lambda e: (-e["count"], e["predicate"]))
    return out


def kg_to_cy(kg: KGData) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    specialties = sorted({s for s in kg.agent_specialty.values() if s}) + [SHARED]
    for d in specialties:
        nodes.append({"data": {"id": f"domain:{d}", "label": d, "type": "Domain", "domain": d}})
    nodes.append({"data": {"id": TOOLS_CLUSTER_ID, "label": "Tools (shared)",
                           "type": "Domain", "domain": "__tools"}})

    for a in kg.agents:
        d = kg.agent_specialty.get(a, "") or SHARED
        nodes.append({"data": {
            "id": a, "label": kg.agent_label.get(a, a), "type": "Agent", "domain": d,
            "parent": f"domain:{d}",
            "tools": sorted(kg.agent_owns.get(a, set())),
            "capabilities": sorted(kg.agent_handles.get(a, set())),
        }})

    for c in kg.capabilities:
        d = _specialty_of_capability(kg, c)
        nodes.append({"data": {
            "id": c, "label": kg.capability_label.get(c, c), "type": "Capability",
            "domain": d, "parent": f"domain:{d}",
        }})

    for tt in kg.task_types:
        d = _specialty_of_process(kg, tt)
        nodes.append({"data": {
            "id": tt, "label": kg.task_label.get(tt, tt), "type": "TaskType",
            "domain": d, "parent": f"domain:{d}",
            "requires": sorted(kg.task_requires.get(tt, set())),
        }})

    for t in kg.tools:
        nodes.append({"data": {
            "id": f"tool:{t}", "label": kg.tool_label.get(t, t), "type": "Tool",
            "domain": "__tools", "parent": TOOLS_CLUSTER_ID,
        }})

    edge_id = 0

    def _eid() -> str:
        nonlocal edge_id
        edge_id += 1
        return f"e{edge_id}"

    for a, caps in kg.agent_handles.items():
        for c in caps:
            edges.append({"data": {"id": _eid(), "source": a, "target": c, "kind": "handles"}})
    for a, tools in kg.agent_owns.items():
        for t in tools:
            edges.append({"data": {"id": _eid(), "source": a, "target": f"tool:{t}", "kind": "owns"}})
    for tt, caps in kg.task_requires.items():
        for c in sorted(caps):
            edges.append({"data": {"id": _eid(), "source": tt, "target": c, "kind": "requires"}})
    for src, dst in sorted(kg.cap_precedes):
        edges.append({"data": {"id": _eid(), "source": src, "target": dst, "kind": "precedes"}})
    # Handoffs are emitted as first-class *nodes*, not agent->agent edges: each
    # one becomes a node plus the two half-edges that chain through it, so the
    # handoff itself is selectable and has somewhere to carry its attributes.
    #
    # `kg.transitions` drives the loop, not `kg.handoffs` — transitions are what
    # the orchestrator may actually traverse, so a graph whose reification is
    # absent or incomplete still renders a topology that matches routing exactly
    # (just with empty condition/weight). The reified instance only enriches.
    for e in kg.transitions:
        src_d = kg.agent_specialty.get(e.src, "")
        dst_d = kg.agent_specialty.get(e.dst, "")
        h = kg.handoff_by_pair.get((e.src, e.dst))
        node_id = handoff_node_id(e.src, e.predicate, e.dst)
        nodes.append({"data": {
            "id": node_id,
            # Short class name ("Delegation"), falling back to the raw predicate
            # when unreified — never the rdfs:comment, which is a paragraph.
            "label": h.class_label if h else e.predicate,
            "type": "Handoff",
            # Clusters with the source agent; `crossDomain` is what flags the
            # handoffs that leave that domain.
            "domain": src_d or SHARED,
            "parent": f"domain:{src_d or SHARED}",
            "predicate": e.predicate,
            "predicateLabel": kg.predicate_label(e.predicate),
            "handoffId": h.id if h else "",
            "handoffClass": h.cls if h else "",
            "condition": h.condition if h else "",
            "weight": h.weight if h else None,
            "isTerminal": h.is_terminal if h else None,
            "from": e.src,
            "to": e.dst,
            "fromLabel": kg.agent_label.get(e.src, e.src),
            "toLabel": kg.agent_label.get(e.dst, e.dst),
            "crossDomain": bool(src_d and dst_d and src_d != dst_d),
        }})
        # Both halves keep kind "handoff" so existing edge-kind filtering and
        # legend grouping keep working; `half` is what lets the stylesheet draw
        # the arrowhead on the outgoing half only, so the pair reads as one
        # continuous arrow passing through the node.
        for half, source, target in (("in", e.src, node_id), ("out", node_id, e.dst)):
            edges.append({"data": {
                "id": _eid(), "source": source, "target": target, "kind": "handoff",
                "half": half, "predicate": e.predicate,
                "label": kg.predicate_label(e.predicate),
                "crossDomain": bool(src_d and dst_d and src_d != dst_d),
            }})

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "agentCount": len(kg.agents),
            "capabilityCount": len(kg.capabilities),
            "taskTypeCount": len(kg.task_types),
            "domainCount": len(specialties),
            "handoffCount": len(kg.transitions),
            "handoffNodeCount": len(kg.transitions),
            "reifiedHandoffCount": len(kg.handoffs),
            "transitionPredicates": kg.transition_predicates,
            # Class-level vocabulary for the legend: label + count + terminality
            # per handoff class, so the frontend doesn't have to re-derive it.
            "handoffClasses": _handoff_classes(kg),
        },
    }
