"""Run v3's task-entry stage end-to-end (plan.md §1).

    NL task
      -> [0] build recall index   (pipeline.embed_index)
      -> [1] semantic recall        (pipeline.recall)
      -> [2] process selection      (pipeline.entry.select_process)
      -> [3] entry-agent selection   (pipeline.entry.select_entry_agent)

This is Stage 0 of v3 — it stops at the single entry agent; the progressive
hop-by-hop orchestration (§4 onward) is built on top of this later. Run with::

    cd v3 && python -m orchestrator.entry_run "patient with chest pain, workup needed"
"""
from __future__ import annotations

import sys
from typing import Dict, Optional

from config import EmbeddingConfig
from embeddings import EmbeddingService
from kg.loader import KGData, load_kg
from logutil import get_logger
from pipeline.embed_index import build_index
from pipeline.entry import EntryResult, select_entry_agent
from pipeline.recall import recall_candidates

log = get_logger("entry_run")

# Cache the (expensive) embedding index per (KG instance, embedding config).
_INDEX_CACHE: Dict[tuple, EmbeddingService] = {}


def get_index(kg: KGData, cfg: Optional[EmbeddingConfig] = None) -> EmbeddingService:
    cfg = cfg or EmbeddingConfig.from_env()
    key = (id(kg), cfg.provider, cfg.model, cfg.dim, cfg.vector_backend)
    service = _INDEX_CACHE.get(key)
    if service is None:
        log.info("building recall index (provider=%s, backend=%s)",
                 cfg.provider, cfg.vector_backend)
        service = build_index(kg, cfg)
        _INDEX_CACHE[key] = service
    return service


def run_entry(task: str, kg: Optional[KGData] = None,
              cfg: Optional[EmbeddingConfig] = None, k: int = 10) -> EntryResult:
    """Recall -> process selection -> entry-agent selection for one task."""
    kg = kg or load_kg()
    service = get_index(kg, cfg)

    recall = recall_candidates(task, service, k=k)
    log.info("recall: %d capabilities, %d agents",
             len(recall.capabilities), len(recall.agents))

    result = select_entry_agent(recall, kg)
    if not result.ok:
        log.warning("entry selection failed: %s", result.reason)
        return result

    log.success("process=%s  entry_agent=%s  (dominant=%s, recalled=%s)",
                result.process, result.entry_agent,
                result.dominant_specialty, result.recalled)
    log.info("required (%d): %s", len(result.required), ", ".join(result.required))
    log.info("candidates (%d): %s", len(result.candidates), ", ".join(result.candidates))
    return result


def main(argv: list[str]) -> int:
    if not argv:
        log.error('usage: python -m orchestrator.entry_run "<task description>"')
        return 2
    task = " ".join(argv)
    log.info("task: %s", task)
    result = run_entry(task)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
