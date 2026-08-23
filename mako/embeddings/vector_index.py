"""Vector-search backends — interchangeable behind a single protocol.

Swap with ``KG_VECTOR_BACKEND`` (see config.py). All backends assume the
provider already L2-normalises (the local provider does; OpenAI vectors are
near-unit and re-normalised here), so cosine similarity reduces to an inner
product and the ranking is identical across backends — only the performance
characteristics differ, which is the point of making it swappable.

Backends:
  * ``flat``  — pure-Python brute-force inner product. Zero dependencies;
                fine for the ~100-node KG. The default.
  * ``numpy`` — vectorised brute-force (needs numpy).
  * ``faiss`` — ``IndexFlatIP`` (needs faiss-cpu); matches the source
                API-discovery project's FAISS usage for larger corpora.

Adding another backend (hnswlib, a vector DB, …) is a new class + one
branch in :func:`make_vector_index`; recall.py is untouched.
"""
from __future__ import annotations

import math
from typing import List, Protocol, Sequence, Tuple


def _normalise(v: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm > 0 else list(v)


class VectorIndex(Protocol):
    backend: str

    def add(self, ids: List[str], vectors: List[List[float]]) -> None: ...

    def search(self, vector: List[float], k: int) -> List[Tuple[str, float]]: ...


class FlatIndex:
    """Pure-Python brute-force cosine index."""

    backend = "flat"

    def __init__(self) -> None:
        self._ids: List[str] = []
        self._vecs: List[List[float]] = []

    def add(self, ids: List[str], vectors: List[List[float]]) -> None:
        self._ids.extend(ids)
        self._vecs.extend(_normalise(v) for v in vectors)

    def search(self, vector: List[float], k: int) -> List[Tuple[str, float]]:
        q = _normalise(vector)
        scored = [
            (self._ids[i], sum(a * b for a, b in zip(q, vec)))
            for i, vec in enumerate(self._vecs)
        ]
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:k]


class NumpyFlatIndex:
    """Vectorised brute-force cosine index (numpy)."""

    backend = "numpy"

    def __init__(self) -> None:
        import numpy as np

        self._np = np
        self._ids: List[str] = []
        self._mat = None  # (n, dim) float32

    def add(self, ids: List[str], vectors: List[List[float]]) -> None:
        np = self._np
        arr = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        arr = np.divide(arr, norms, out=np.zeros_like(arr), where=norms > 0)
        self._ids.extend(ids)
        self._mat = arr if self._mat is None else np.vstack([self._mat, arr])

    def search(self, vector: List[float], k: int) -> List[Tuple[str, float]]:
        np = self._np
        q = np.asarray(vector, dtype="float32")
        n = np.linalg.norm(q)
        if n > 0:
            q = q / n
        sims = self._mat @ q
        order = np.argsort(-sims)[:k]
        return [(self._ids[int(i)], float(sims[int(i)])) for i in order]


class FaissIndex:
    """FAISS ``IndexFlatIP`` over normalised vectors (inner product = cosine)."""

    backend = "faiss"

    def __init__(self) -> None:
        import faiss  # noqa: F401
        import numpy as np

        self._faiss = faiss
        self._np = np
        self._ids: List[str] = []
        self._index = None

    def add(self, ids: List[str], vectors: List[List[float]]) -> None:
        np = self._np
        arr = np.asarray(vectors, dtype="float32")
        self._faiss.normalize_L2(arr)
        if self._index is None:
            self._index = self._faiss.IndexFlatIP(arr.shape[1])
        self._index.add(arr)
        self._ids.extend(ids)

    def search(self, vector: List[float], k: int) -> List[Tuple[str, float]]:
        np = self._np
        q = np.asarray([vector], dtype="float32")
        self._faiss.normalize_L2(q)
        scores, idxs = self._index.search(q, min(k, len(self._ids)))
        return [
            (self._ids[int(i)], float(s))
            for i, s in zip(idxs[0], scores[0]) if i >= 0
        ]


def make_vector_index(backend: str = "flat") -> VectorIndex:
    backend = (backend or "flat").lower()
    if backend == "flat":
        return FlatIndex()
    if backend == "numpy":
        return NumpyFlatIndex()
    if backend == "faiss":
        return FaissIndex()
    raise ValueError(
        f"Unknown vector backend {backend!r}. Try one of: flat, numpy, faiss."
    )
