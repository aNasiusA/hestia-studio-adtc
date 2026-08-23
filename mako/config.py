"""Central runtime configuration for v2 — all knobs are environment driven.

The design goal (per the chosen build decision) is that the *embedding
provider* and the *vector-search backend* are both swappable by
configuration alone, with **no application-code change**. Everything the
recall stage needs is resolved through :class:`EmbeddingConfig` here, so a
reviewer can run the same pipeline against a local hashing embedder
offline, or against OpenAI/Ollama embeddings + FAISS, purely via env vars.

Env vars
--------
Embeddings:
    KG_EMBED_PROVIDER   local | openai | ollama | gemini    (default: local)
    KG_EMBED_MODEL      provider-specific model id
    KG_EMBED_DIM        vector dim; sets the `local` embedder's size and, for
                        `gemini`, the model's output_dimensionality. When unset,
                        remote providers use their native dim (default: 512)
    KG_EMBED_BASE_URL   base url for openai-compatible endpoints
    KG_EMBED_API_KEY    api key override (falls back to OPENAI_API_KEY;
                        gemini also reads GOOGLE_API_KEY / GEMINI_API_KEY)

Vector search backend:
    KG_VECTOR_BACKEND   flat | numpy | faiss               (default: flat)

LLM execution (reused from agents/llm.py):
    KG_LLM_PROVIDER, KG_MODEL, KG_BASE_URL, KG_API_KEY, KG_MAX_TOKENS
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from envfile import load_env

# Load the repo-root .env (if any) so KG_EMBED_* / KG_VECTOR_BACKEND resolve
# even when config.py is imported before agents/llm.py. Idempotent; real
# environment variables are never overridden.
load_env()


# Per-provider default embedding model + native dimensionality.
_EMBED_DEFAULT_MODEL = {
    "local":  "hash-ngram",
    "openai": "text-embedding-3-small",
    "ollama": "nomic-embed-text",
    "gemini": "gemini-embedding-001",
}
_EMBED_NATIVE_DIM = {
    "openai": 1536,   # text-embedding-3-small
    "ollama": 768,    # nomic-embed-text
    "gemini": 3072,   # gemini-embedding-001 default output dimensionality
}


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "local"
    model: str = "hash-ngram"
    dim: int = 512
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    vector_backend: str = "flat"

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        provider = (os.getenv("KG_EMBED_PROVIDER") or "local").lower()
        model = os.getenv("KG_EMBED_MODEL") or _EMBED_DEFAULT_MODEL.get(provider, "default")
        # An explicit KG_EMBED_DIM always wins (lets gemini reduce its
        # output_dimensionality); otherwise remote providers use their native
        # dim and `local` defaults to 512.
        explicit_dim = os.getenv("KG_EMBED_DIM")
        if explicit_dim:
            dim = int(explicit_dim)
        elif provider != "local":
            dim = _EMBED_NATIVE_DIM.get(provider, 512)
        else:
            dim = 512
        base_url = os.getenv("KG_EMBED_BASE_URL")
        api_key = os.getenv("KG_EMBED_API_KEY") or os.getenv("OPENAI_API_KEY")
        if provider == "ollama" and not base_url:
            base_url = "http://localhost:11434/v1"
        if provider == "ollama" and not api_key:
            api_key = "ollama"
        backend = (os.getenv("KG_VECTOR_BACKEND") or "flat").lower()
        return cls(
            provider=provider,
            model=model,
            dim=dim,
            base_url=base_url,
            api_key=api_key,
            vector_backend=backend,
        )
