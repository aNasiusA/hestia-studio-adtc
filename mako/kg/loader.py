"""Load the healthcare KG and expose a typed access layer for v3.

This is the *domain* the v3 method runs against (plan.md §1/§2). The healthcare
graph is reused directly from v2, with **one deliberate removal**: the
hand-authored ``kg:sequenceIndex`` on each ``TaskType -requires-> Capability``
edge is gone (plan.md §1, Change 1). A process's required capabilities are now
an **unordered set** — v3 discovers order progressively through execution and
graph traversal, never by reading a precomputed position off the schema.

Agent Graph ("what exists")
    kg:Agent  --kg:handles--> kg:Capability      (agent capabilities)
    kg:Agent  --kg:owns-->     kg:Tool           (stubbed tools)
    kg:Agent   kg:specialty    "<domain>"        (domain membership)

Process Graph ("what is required, unordered")
    kg:TaskType --kg:requires--> [ kg:capability c ]
        A named business process as an *unordered set* of required
        capabilities (no sequenceIndex).
    kg:Capability --kg:precedes--> kg:Capability
        Capability-level ordering DAG (background authority, retained).

Named, domain-specific transition edges (the whole point of the method — NOT
one generic CAN_HANDOFF_TO):
    <agent> --p--> <agent>   for every p rdfs:subPropertyOf kg:canHandoffTo
    In healthcare that vocabulary is {delegatesTo, escalatesTo, refersTo,
    returnsTo, consults}. These are **discovered from the graph**, not
    hard-coded — a new domain declaring its own sub-properties of
    kg:canHandoffTo works with zero code change (plan.md §2).

Reified handoffs (presentation only)
    <handoff> a <cls>, for every cls rdfs:subClassOf kg:HandoffEdge
        Each transition is *also* stated as an object node carrying the
        per-edge attributes a bare triple cannot hold — kg:condition and
        kg:weight — plus a class whose rdfs:label and kg:isTerminal describe
        what the handoff means. Discovered by the same BFS shape as the
        predicate vocabulary above, so it inherits the same zero-code-change
        guarantee. Loaded for the UI; routing ignores it entirely.

Bridge / fusion
    A required capability's performer is resolved as "an agent that kg:handles
    that capability" — the same free-union bridge as v2.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, NamedTuple, Set, Tuple

from rdflib import Graph, Namespace, RDF, RDFS, URIRef

KG = Namespace("http://example.org/healthkg#")
DEFAULT_TTL = Path(__file__).parent / "healthcare_kg.ttl"
CAN_HANDOFF_TO = KG.canHandoffTo
HANDOFF_EDGE = KG.HandoffEdge


class TransitionEdge(NamedTuple):
    src: str          # source agent local-name
    predicate: str    # named transition predicate local-name (e.g. "delegatesTo")
    dst: str          # destination agent local-name


class HandoffInstance(NamedTuple):
    """A *reified* handoff — the ``kg:handoff_N`` object node backing a
    transition edge.

    The graph states every handoff twice: once as the direct triple
    ``<agent> <predicate> <agent>`` that :meth:`_discover_transitions` reads,
    and once as an instance of a ``kg:HandoffEdge`` subclass carrying the
    per-edge attributes that have nowhere to live on a bare triple::

        kg:handoff_1 a kg:DelegationHandoff ;
            kg:condition "stage_complete" ;
            kg:from kg:Surgery_SurgicalPlanning ;
            kg:to kg:Surgery_IntraOpCoordination ;
            kg:weight 6e-01 .

    Routing never consults these — ``transitions`` remains the sole authority
    for what the orchestrator may traverse (see ``_discover_handoff_instances``
    for why this stays strictly presentational).
    """
    id: str            # instance local-name, e.g. "handoff_1"
    cls: str           # class local-name, e.g. "DelegationHandoff"
    class_label: str   # the class's rdfs:label, e.g. "Delegation"
    src: str           # kg:from agent local-name
    dst: str           # kg:to agent local-name
    predicate: str     # joined from the direct triples on (src, dst)
    condition: str     # kg:condition, e.g. "stage_complete"
    weight: float      # kg:weight (xsd:double)
    is_terminal: bool  # the class's kg:isTerminal — does ownership transfer?


def _local(ref) -> str:
    s = str(ref)
    return s.split("#", 1)[1] if "#" in s else s.rsplit("/", 1)[-1]


class KGData:
    """Query-friendly view of the loaded healthcare KG."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph

        # Node sets / labels
        self.agents: List[str] = []
        self.agent_label: Dict[str, str] = {}
        self.agent_specialty: Dict[str, str] = {}

        self.capabilities: List[str] = []
        self.capability_label: Dict[str, str] = {}

        self.tools: List[str] = []
        self.tool_label: Dict[str, str] = {}

        # Agent graph edges
        self.agent_handles: Dict[str, Set[str]] = {}
        self.agent_owns: Dict[str, Set[str]] = {}

        # Capability ordering DAG
        self.cap_precedes: Set[Tuple[str, str]] = set()

        # Process graph: task type -> UNORDERED set of required capabilities
        # (plan.md §1, Change 1 — sequenceIndex removed).
        self.task_types: List[str] = []
        self.task_label: Dict[str, str] = {}
        self.task_requires: Dict[str, Set[str]] = {}

        # Named transition-edge vocabulary + edges (discovered, not hard-coded)
        self.transition_predicates: List[str] = []
        self.transitions: List[TransitionEdge] = []
        # Predicate-level, human-readable edge labels (plan.md §2). Attached
        # per-predicate via rdfs:comment — these are shared by every edge using
        # that predicate. Per-*instance* attributes live on the reified handoff
        # objects below instead.
        self.predicate_comment: Dict[str, str] = {}

        # Reified handoff instances (presentation only — see HandoffInstance).
        # `handoff_by_pair` is keyed on (src, dst): the graph declares at most
        # one predicate per ordered agent pair, so that key is unambiguous.
        self.handoffs: List[HandoffInstance] = []
        self.handoff_by_pair: Dict[Tuple[str, str], HandoffInstance] = {}

        # Indexes
        self.agents_by_capability: Dict[str, List[str]] = {}
        self.agents_by_specialty: Dict[str, List[str]] = {}
        self.out_edges: Dict[str, List[Tuple[str, str]]] = {}  # src -> [(dst, pred)]
        self.in_edges: Dict[str, List[Tuple[str, str]]] = {}   # dst -> [(src, pred)]

        self._populate()
        self._build_indexes()

    # ------------------------------------------------------------------
    def _populate(self) -> None:
        g = self.graph

        for c in g.subjects(RDF.type, KG.Capability):
            name = _local(c)
            self.capabilities.append(name)
            lbl = g.value(c, RDFS.label)
            self.capability_label[name] = str(lbl) if lbl else name
        self.capabilities.sort()

        for t in g.subjects(RDF.type, KG.Tool):
            name = _local(t)
            self.tools.append(name)
            lbl = g.value(t, RDFS.label)
            self.tool_label[name] = str(lbl) if lbl else name
        self.tools.sort()

        for a in g.subjects(RDF.type, KG.Agent):
            name = _local(a)
            self.agents.append(name)
            lbl = g.value(a, RDFS.label)
            self.agent_label[name] = str(lbl) if lbl else name
            spec = g.value(a, KG.specialty)
            self.agent_specialty[name] = str(spec) if spec else ""
            self.agent_handles[name] = {_local(c) for c in g.objects(a, KG.handles)}
            self.agent_owns[name] = {_local(t) for t in g.objects(a, KG.owns)}
        self.agents.sort()

        for src, dst in g.subject_objects(KG.precedes):
            self.cap_precedes.add((_local(src), _local(dst)))

        for tt in g.subjects(RDF.type, KG.TaskType):
            name = _local(tt)
            self.task_types.append(name)
            lbl = g.value(tt, RDFS.label)
            self.task_label[name] = str(lbl) if lbl else name
            # Unordered set of required capabilities (no sequenceIndex read).
            caps: Set[str] = set()
            for req in g.objects(tt, KG.requires):
                cap = g.value(req, KG.capability)
                if cap is None:
                    continue
                caps.add(_local(cap))
            self.task_requires[name] = caps
        self.task_types.sort()

        self._discover_transitions()
        self._discover_handoff_instances()

    def _discover_transitions(self) -> None:
        """Find every named transition predicate and its edges.

        A predicate is a transition edge iff it is (transitively) an
        rdfs:subPropertyOf kg:canHandoffTo. We read the vocabulary straight
        from the graph so the method never hard-codes healthcare's specific
        edge names — that is the zero-code-change extensibility guarantee.
        """
        g = self.graph
        preds: Set[URIRef] = set()
        frontier = [CAN_HANDOFF_TO]
        seen: Set[URIRef] = set()
        while frontier:
            parent = frontier.pop()
            for sub in g.subjects(RDFS.subPropertyOf, parent):
                if sub in seen or sub == CAN_HANDOFF_TO:
                    continue
                seen.add(sub)
                if isinstance(sub, URIRef):
                    preds.add(sub)
                    frontier.append(sub)

        agent_set = set(self.agents)
        for p in preds:
            pname = _local(p)
            comment = g.value(p, RDFS.comment)
            self.predicate_comment[pname] = str(comment) if comment else ""
            for s, o in g.subject_objects(p):
                s_l, o_l = _local(s), _local(o)
                if s_l in agent_set and o_l in agent_set:
                    self.transitions.append(TransitionEdge(s_l, pname, o_l))
        self.transition_predicates = sorted(pname for pname in {t.predicate for t in self.transitions})
        self.transitions.sort()

    def _discover_handoff_instances(self) -> None:
        """Load the reified ``kg:HandoffEdge`` instances backing the transitions.

        Deliberately mirrors :meth:`_discover_transitions`: a class is a handoff
        class iff it is (transitively) an ``rdfs:subClassOf kg:HandoffEdge``,
        discovered by the same BFS the predicate vocabulary uses. A new domain
        declaring its own handoff subclasses therefore works with zero code
        change, exactly as it does for the predicates (plan.md §2).

        This runs *after* ``_discover_transitions`` and never feeds back into
        it. `transitions` stays the sole routing authority; everything here is
        presentational metadata, so a graph with no reification at all simply
        yields an empty index rather than changing what the orchestrator can do.

        ``kg:from``/``kg:to``/``kg:condition``/``kg:weight`` are not declared as
        ``rdf:Property`` anywhere in the graph, so unlike the class and
        predicate vocabularies they cannot be discovered — they are named
        literally. (``kg:from`` needs ``KG["from"]``: ``from`` is a keyword.)
        """
        g = self.graph

        classes: Set[URIRef] = set()
        frontier = [HANDOFF_EDGE]
        seen: Set[URIRef] = set()
        while frontier:
            parent = frontier.pop()
            for sub in g.subjects(RDFS.subClassOf, parent):
                if sub in seen or sub == HANDOFF_EDGE:
                    continue
                seen.add(sub)
                if isinstance(sub, URIRef):
                    classes.add(sub)
                    frontier.append(sub)

        # (src, dst) -> predicate, from the already-loaded direct triples. The
        # class↔predicate correspondence (DelegationHandoff↔delegatesTo) is
        # nowhere stated in the graph, so the agent pair is the only sound join.
        pred_by_pair = {(t.src, t.dst): t.predicate for t in self.transitions}
        agent_set = set(self.agents)

        for cls in classes:
            cls_name = _local(cls)
            lbl = g.value(cls, RDFS.label)
            class_label = str(lbl) if lbl else cls_name
            terminal = g.value(cls, KG.isTerminal)
            is_terminal = bool(terminal.toPython()) if terminal is not None else True

            for inst in g.subjects(RDF.type, cls):
                src, dst = g.value(inst, KG["from"]), g.value(inst, KG.to)
                if src is None or dst is None:
                    continue
                src_l, dst_l = _local(src), _local(dst)
                if src_l not in agent_set or dst_l not in agent_set:
                    continue
                predicate = pred_by_pair.get((src_l, dst_l), "")
                if not predicate:
                    # Reified without a matching direct triple: unreachable by
                    # the orchestrator, so it is not a real edge. Skip it rather
                    # than render a transition that could never be traversed.
                    continue
                cond = g.value(inst, KG.condition)
                w = g.value(inst, KG.weight)
                self.handoffs.append(HandoffInstance(
                    id=_local(inst),
                    cls=cls_name,
                    class_label=class_label,
                    src=src_l,
                    dst=dst_l,
                    predicate=predicate,
                    condition=str(cond) if cond is not None else "",
                    weight=float(w) if w is not None else 0.0,
                    is_terminal=is_terminal,
                ))

        self.handoffs.sort()
        self.handoff_by_pair = {(h.src, h.dst): h for h in self.handoffs}

    # ------------------------------------------------------------------
    def _build_indexes(self) -> None:
        by_cap: Dict[str, List[str]] = defaultdict(list)
        for agent, caps in self.agent_handles.items():
            for c in caps:
                by_cap[c].append(agent)
        for c in by_cap:
            by_cap[c].sort()
        self.agents_by_capability = dict(by_cap)

        by_spec: Dict[str, List[str]] = defaultdict(list)
        for agent, spec in self.agent_specialty.items():
            by_spec[spec].append(agent)
        for s in by_spec:
            by_spec[s].sort()
        self.agents_by_specialty = dict(by_spec)

        out_e: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        in_e: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for edge in self.transitions:
            out_e[edge.src].append((edge.dst, edge.predicate))
            in_e[edge.dst].append((edge.src, edge.predicate))
        for d in out_e:
            out_e[d].sort()
        for d in in_e:
            in_e[d].sort()
        self.out_edges = dict(out_e)
        self.in_edges = dict(in_e)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def agents_covering(self, capability: str) -> List[str]:
        return list(self.agents_by_capability.get(capability, []))

    def predicate_label(self, predicate: str) -> str:
        """Human-readable edge label for a named transition predicate (plan.md §2).

        Falls back to the predicate's local name when no rdfs:comment is set."""
        return self.predicate_comment.get(predicate) or predicate

    def transition_predicate(self, src: str, dst: str) -> str | None:
        """The named edge from `src` to `dst`, or None if there is none.

        When several named edges exist for the pair, the first alphabetically
        is returned for determinism (there is normally at most one)."""
        for d, pred in self.out_edges.get(src, []):
            if d == dst:
                return pred
        return None

    def successors(self, agent: str) -> List[Tuple[str, str]]:
        return list(self.out_edges.get(agent, []))

    def predecessors(self, agent: str) -> List[Tuple[str, str]]:
        return list(self.in_edges.get(agent, []))


def load_kg(ttl_path: Path = DEFAULT_TTL) -> KGData:
    g = Graph()
    g.parse(str(ttl_path), format="turtle")
    return KGData(g)
