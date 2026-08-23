"""EmbeddingService — one seam that binds a provider to a backend.

This is the only object the recall stage constructs. It hides both choices
(embedding provider *and* vector backend) behind ``build`` / ``query`` so
that swapping either is a config change, never a code change.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from config import EmbeddingConfig
from embeddings.providers import EmbeddingProvider, make_provider
from embeddings.vector_index import VectorIndex, make_vector_index


class EmbeddingService:
    def __init__(self, cfg: EmbeddingConfig | None = None,
                 provider: EmbeddingProvider | None = None,
                 index: VectorIndex | None = None) -> None:
        self.cfg = cfg or EmbeddingConfig.from_env()
        self.provider = provider or make_provider(self.cfg)
        self.index = index or make_vector_index(self.cfg.vector_backend)
        self._built = False

    @property
    def descriptor(self) -> str:
        return (f"{self.provider.name}:{self.provider.model} "
                f"(dim={self.provider.dim}) / vector={self.index.backend}")

    def build(self, documents: Dict[str, str]) -> "EmbeddingService":
        """Embed a ``{id: text}`` corpus and load it into the index."""
        ids = list(documents.keys())
        vectors = self.provider.embed([documents[i] for i in ids])
        self.index.add(ids, vectors)
        self._built = True
        return self

    def query(self, text: str, k: int = 5) -> List[Tuple[str, float]]:
        if not self._built:
            raise RuntimeError("EmbeddingService.query() called before build().")
        vec = self.provider.embed([text])[0]
        return self.index.search(vec, k)
