"""Vendor-agnostic embeddings + vector-search service.

Both the embedding provider and the similarity-search backend are selected
by configuration (see ``config.EmbeddingConfig`` / env vars) so recall can
be re-pointed at OpenAI, Ollama, FAISS, etc. without touching pipeline code.
"""
from embeddings.service import EmbeddingService

__all__ = ["EmbeddingService"]
