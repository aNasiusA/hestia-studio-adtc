"""Stage 1: semantic recall (adapted from the source project's query_index).

Embed the task text, search the vector index, and split the hits back into
candidate capabilities and candidate agents. No graph reasoning happens
here — recall's only job is to answer "semantically, what is this task
about?" and hand a candidate set to the process-chain expander. The LLM /
embedding model is the authority on *intent*; the graph is the authority on
*order* (that split is the whole design, plan.md §1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from embeddings import EmbeddingService
from pipeline.embed_index import AGENT_PREFIX, CAP_PREFIX


@dataclass
class RecallResult:
    task_text: str
    capabilities: List[Tuple[str, float]] = field(default_factory=list)  # ranked
    agents: List[Tuple[str, float]] = field(default_factory=list)        # ranked
    raw: List[Tuple[str, float]] = field(default_factory=list)           # all hits

    @property
    def capability_uris(self) -> List[str]:
        return [c for c, _ in self.capabilities]

    @property
    def agent_uris(self) -> List[str]:
        return [a for a, _ in self.agents]


def recall_candidates(task_text: str, service: EmbeddingService,
                      k: int = 10) -> RecallResult:
    """Return ranked candidate capabilities + agents for a task description."""
    hits = service.query(task_text, k=k)
    caps: List[Tuple[str, float]] = []
    agents: List[Tuple[str, float]] = []
    for node_id, score in hits:
        if node_id.startswith(CAP_PREFIX):
            caps.append((node_id[len(CAP_PREFIX):], score))
        elif node_id.startswith(AGENT_PREFIX):
            agents.append((node_id[len(AGENT_PREFIX):], score))
    return RecallResult(task_text=task_text, capabilities=caps, agents=agents, raw=hits)
