"""KG query layer (plan.md §3) — two backend-agnostic operations.

    get_valid_transitions(current_agent) -> List[Transition{agent, predicate, label}]
    validate_decision(current_agent, candidate_agent) -> Validation{is_valid, reason?}

Design commitments from the plan:

  * **No `state` parameter.** Transitions come straight from the raw graph edges
    out of ``current_agent``; state/context is used only in the orchestrator's
    *decision*, never in the query itself.
  * **Backend-agnostic.** The same graph is queried through one interface,
    selected via the ``KG_QUERY_BACKEND`` env var. The output shape is identical
    across backends — this is a latency/engineering comparison, not expected to
    change orchestrator decisions.
        - ``rdflib``  — direct dict lookup over the loader's precomputed
          ``out_edges`` index (fastest; default).
        - ``sparql``  — same graph, a live SPARQL query instead of the index.
        - ``cypher``  — requires a real graph DB (e.g. Neo4j); left as a
          swappable stub so the "zero-orchestration-change" seam is explicit.

The predicate ``label`` is the per-predicate ``rdfs:comment`` added in §2, giving
the orchestrator LLM enough context to reason about *why* an edge exists.
"""
from __future__ import annotations

import os
from typing import List, NamedTuple, Optional, Protocol

from kg.loader import KG, KGData


class Transition(NamedTuple):
    agent: str        # destination agent local-name
    predicate: str    # named transition predicate (e.g. "delegatesTo")
    label: str        # human-readable predicate-level edge label (§2)


class Validation(NamedTuple):
    is_valid: bool
    reason: Optional[str] = None


class KGQueryBackend(Protocol):
    name: str

    def get_valid_transitions(self, current_agent: str) -> List[Transition]: ...

    def validate_decision(self, current_agent: str,
                          candidate_agent: str) -> Validation: ...


# ----------------------------------------------------------------------
# rdflib backend (default) — precomputed index lookup
# ----------------------------------------------------------------------
class RdflibBackend:
    """Direct lookup over ``KGData.out_edges`` (no query-language overhead)."""

    name = "rdflib"

    def __init__(self, kg: KGData) -> None:
        self.kg = kg
        self._agent_set = set(kg.agents)

    def get_valid_transitions(self, current_agent: str) -> List[Transition]:
        out = self.kg.out_edges.get(current_agent, [])
        return [
            Transition(agent=dst, predicate=pred,
                       label=self.kg.predicate_label(pred))
            for dst, pred in out
        ]

    def validate_decision(self, current_agent: str,
                          candidate_agent: str) -> Validation:
        if current_agent not in self._agent_set:
            return Validation(False, f"Unknown source agent {current_agent!r}.")
        if candidate_agent not in self._agent_set:
            return Validation(False, f"Unknown candidate agent {candidate_agent!r}.")
        for t in self.get_valid_transitions(current_agent):
            if t.agent == candidate_agent:
                return Validation(True, None)
        return Validation(
            False,
            f"No named transition edge from {current_agent} to {candidate_agent}. "
            f"The candidate is not reachable in one hop from the current agent.",
        )


# ----------------------------------------------------------------------
# SPARQL backend — same graph, live query instead of the index
# ----------------------------------------------------------------------
class SparqlBackend:
    """Live SPARQL over the loaded rdflib graph.

    Functionally identical output to :class:`RdflibBackend`; it exists to show
    the query layer is backend-swappable with zero orchestration change. The
    named-transition vocabulary is discovered the same way the loader does it —
    predicates that are ``rdfs:subPropertyOf kg:canHandoffTo`` — so this stays
    domain-agnostic (healthcare's edge names are never hard-coded here).
    """

    name = "sparql"

    _TRANSITIONS_Q = """
        PREFIX kg: <http://example.org/healthkg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?dst ?pred ?label WHERE {
            ?pred rdfs:subPropertyOf kg:canHandoffTo .
            ?src ?pred ?dst .
            ?dst rdf:type kg:Agent .
            OPTIONAL { ?pred rdfs:comment ?label }
            FILTER(?src = ?current)
        }
    """

    def __init__(self, kg: KGData) -> None:
        self.kg = kg
        self.graph = kg.graph
        self._agent_set = set(kg.agents)

    def get_valid_transitions(self, current_agent: str) -> List[Transition]:
        current = KG[current_agent]
        rows = self.graph.query(self._TRANSITIONS_Q, initBindings={"current": current})
        out: List[Transition] = []
        for dst, pred, label in rows:
            pname = _local(pred)
            out.append(Transition(
                agent=_local(dst),
                predicate=pname,
                label=str(label) if label else self.kg.predicate_label(pname),
            ))
        out.sort()
        return out

    def validate_decision(self, current_agent: str,
                          candidate_agent: str) -> Validation:
        if current_agent not in self._agent_set:
            return Validation(False, f"Unknown source agent {current_agent!r}.")
        if candidate_agent not in self._agent_set:
            return Validation(False, f"Unknown candidate agent {candidate_agent!r}.")
        for t in self.get_valid_transitions(current_agent):
            if t.agent == candidate_agent:
                return Validation(True, None)
        return Validation(
            False,
            f"No named transition edge from {current_agent} to {candidate_agent}. "
            f"The candidate is not reachable in one hop from the current agent.",
        )


# ----------------------------------------------------------------------
# Cypher backend — swappable stub (needs a real graph DB)
# ----------------------------------------------------------------------
class CypherBackend:
    """Placeholder for a Neo4j/Cypher backend.

    Deliberately not implemented: it requires real graph-DB infrastructure and
    stands only as the production-realistic comparison point named in §3. The
    interface is identical, so wiring a driver here needs no orchestration
    change.
    """

    name = "cypher"

    def __init__(self, kg: KGData) -> None:  # pragma: no cover - stub
        self.kg = kg

    def _unavailable(self):  # pragma: no cover - stub
        raise NotImplementedError(
            "KG_QUERY_BACKEND=cypher requires a running graph DB (e.g. Neo4j). "
            "This backend is a documented swappable stub; use 'rdflib' (default) "
            "or 'sparql' for the demo."
        )

    def get_valid_transitions(self, current_agent: str) -> List[Transition]:  # pragma: no cover
        self._unavailable()

    def validate_decision(self, current_agent: str,
                          candidate_agent: str) -> Validation:  # pragma: no cover
        self._unavailable()


_BACKENDS = {
    "rdflib": RdflibBackend,
    "sparql": SparqlBackend,
    "cypher": CypherBackend,
}


def _local(ref) -> str:
    s = str(ref)
    return s.split("#", 1)[1] if "#" in s else s.rsplit("/", 1)[-1]


def make_query_backend(kg: KGData, backend: Optional[str] = None) -> KGQueryBackend:
    """Construct the KG query backend (``KG_QUERY_BACKEND``; default ``rdflib``)."""
    name = (backend or os.getenv("KG_QUERY_BACKEND") or "rdflib").lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown KG_QUERY_BACKEND {name!r}. "
            f"Try one of: {', '.join(sorted(_BACKENDS))}."
        )
    return cls(kg)
