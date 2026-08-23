"""Embedding providers — interchangeable behind a single protocol.

Swap the backend with `KG_EMBED_PROVIDER` (see config.py); application code
only ever talks to the :class:`EmbeddingProvider` protocol, never a concrete
vendor SDK. Three providers ship:

  * ``local``  — pure-Python deterministic hashing embedder (bag of word
                 tokens + character n-grams hashed into a fixed-dim vector,
                 L2-normalised). Zero dependencies, no network, fully
                 reproducible — the offline default that keeps the demo and
                 the tests hermetic.
  * ``openai`` — OpenAI embeddings API (also serves any OpenAI-compatible
                 endpoint via ``base_url``).
  * ``ollama`` — local Ollama server through its OpenAI-compatible route.
  * ``gemini`` — Google Gemini embedding models via the google-genai SDK.

Adding another vendor is a new class + one branch in :func:`make_provider`;
no other module changes.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import List, Protocol

from config import EmbeddingConfig


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dim: int

    def embed(self, texts: List[str]) -> List[List[float]]: ...


# ----------------------------------------------------------------------
# Local hashing embedder (offline default)
# ----------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def _tokens(text: str) -> List[str]:
    """Lexical features: lowercased word/camelCase tokens + 3-char n-grams.

    Splitting camelCase matters because the KG's labels are fragments like
    ``AssessChestPain`` — we want the tokens ``assess``, ``chest``, ``pain``
    so a natural-language task ("patient with chest pain") lands near them.
    """
    words = [w.lower() for w in _TOKEN_RE.findall(text)]
    feats: List[str] = list(words)
    joined = "".join(words)
    for i in range(len(joined) - 2):
        feats.append("#" + joined[i : i + 3])
    return feats


class LocalHashingProvider:
    name = "local"

    def __init__(self, model: str = "hash-ngram", dim: int = 512) -> None:
        self.model = model
        self.dim = dim

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for feat in _tokens(text):
            h = hashlib.md5(feat.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]


# ----------------------------------------------------------------------
# OpenAI-compatible provider (OpenAI proper + Ollama + any compatible host)
# ----------------------------------------------------------------------

class OpenAICompatibleProvider:
    name = "openai"

    def __init__(self, model: str, dim: int,
                 base_url: str | None = None, api_key: str | None = None) -> None:
        from openai import OpenAI

        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        self.client = OpenAI(**kwargs)
        self.model = model
        self.dim = dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


# ----------------------------------------------------------------------
# Google Gemini provider
# ----------------------------------------------------------------------

class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str, dim: int) -> None:
        from google import genai

        # genai.Client() reads GOOGLE_API_KEY / GEMINI_API_KEY from the env.
        self.client = genai.Client()
        self.model = model
        self.dim = dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        from google.genai import types

        resp = self.client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self.dim),
        )
        # Gemini only pre-normalises the full 3072-dim output; reduced
        # dimensions must be renormalised. The vector index normalises on
        # add/query anyway, so cosine ranking is correct either way.
        return [list(e.values) for e in resp.embeddings]


def make_provider(cfg: EmbeddingConfig | None = None) -> EmbeddingProvider:
    cfg = cfg or EmbeddingConfig.from_env()
    if cfg.provider == "local":
        return LocalHashingProvider(model=cfg.model, dim=cfg.dim)
    if cfg.provider in ("openai", "ollama"):
        provider = OpenAICompatibleProvider(
            cfg.model, cfg.dim, base_url=cfg.base_url, api_key=cfg.api_key,
        )
        provider.name = cfg.provider
        return provider
    if cfg.provider == "gemini":
        return GeminiProvider(cfg.model, cfg.dim)
    raise ValueError(
        f"Unknown embedding provider {cfg.provider!r}. "
        "Try one of: local, openai, ollama, gemini."
    )
