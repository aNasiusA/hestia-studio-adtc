"""Stage 0 (one-time): build the semantic-recall index over the KG.

Adapted from the source project's ``query_index()`` setup. We embed two
kinds of node — ``Capability`` and ``Agent`` — because the task is recalled
against *what can be done* and *who can do it*. Each node is turned into a
short document that folds in its neighbourhood (an agent's capabilities, a
capability's performers + the processes that need it) so that the very
short KG labels (e.g. ``AssessChestPain``) still have enough lexical/semantic
surface to match a natural-language task.

The embedding provider and vector backend are entirely hidden inside
``EmbeddingService`` — this module only decides *what text* to embed.
"""
from __future__ import annotations

from typing import Dict
from logutil import get_logger

from config import EmbeddingConfig
from embeddings import EmbeddingService
from kg.loader import KGData

CAP_PREFIX = "cap:"
AGENT_PREFIX = "agent:"

log = get_logger(__name__)

def _spaced(local_name: str) -> str:
    """`cap_AssessChestPain` -> `Assess Chest Pain` (drop type prefix)."""
    core = local_name.split("_", 1)[1] if "_" in local_name else local_name
    out, prev_lower = [], False
    for ch in core:
        if ch.isupper() and prev_lower:
            out.append(" ")
        out.append(ch)
        prev_lower = ch.islower()
    return "".join(out)


def build_documents(kg: KGData) -> Dict[str, str]:
    """Return ``{node_id: document_text}`` for capabilities and agents."""
    # capability -> processes that require it (for extra recall surface)
    cap_processes: Dict[str, list] = {}
    for tt, caps in kg.task_requires.items():
        for c in caps:
            cap_processes.setdefault(c, []).append(_spaced(tt))

    docs: Dict[str, str] = {}

    for cap in kg.capabilities:
        performers = kg.agents_by_capability.get(cap, [])
        specialties = sorted({kg.agent_specialty.get(a, "") for a in performers})
        parts = [_spaced(cap), kg.capability_label.get(cap, "")]
        if performers:
            parts.append("Performed by " + ", ".join(_spaced(a) for a in performers) + ".")
        if any(specialties):
            parts.append("Specialties: " + ", ".join(s for s in specialties if s) + ".")
        if cap in cap_processes:
            parts.append("Used in: " + ", ".join(sorted(set(cap_processes[cap]))) + ".")
        docs[CAP_PREFIX + cap] = " ".join(parts)

    for agent in kg.agents:
        caps = sorted(kg.agent_handles.get(agent, set()))
        tools = sorted(kg.agent_owns.get(agent, set()))
        parts = [
            _spaced(agent),
            f"{kg.agent_specialty.get(agent, '')} specialist agent.",
        ]
        if caps:
            parts.append("Capabilities: " + ", ".join(_spaced(c) for c in caps) + ".")
        if tools:
            parts.append("Tools: " + ", ".join(_spaced(t) for t in tools) + ".")
        docs[AGENT_PREFIX + agent] = " ".join(parts)

    # log.info(docs)
    return docs


def build_index(kg: KGData, cfg: EmbeddingConfig | None = None) -> EmbeddingService:
    service = EmbeddingService(cfg)
    service.build(build_documents(kg))
    return service
