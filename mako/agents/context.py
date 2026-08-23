"""Domain-agent execution context (plan.md §11.3 / §12).

*How much prior state a domain agent sees when it executes* is explicitly out of
scope as a research contribution — it is standard agent-engineering territory.
It is therefore a **pluggable interface**, swappable per domain/agent, exactly
like the KG query backend.

The demo default is :class:`LastOutputOnly` — the executing agent sees only the
immediately preceding agent's output (plus the original task). Cheap, consistent
and defensible without spending design effort on a concern the method is not
trying to advance.
"""
from __future__ import annotations

from typing import List, Optional, Protocol


class AgentContextProvider(Protocol):
    name: str

    def build(self, *, task: str, history: List[str]) -> Optional[str]:
        """Return the prior-context string to show the executing agent.

        ``history`` is the ordered list of prior agents' raw outputs (oldest
        first). Returning ``None`` means "no prior context" (the entry hop)."""
        ...


class LastOutputOnly:
    """Demo default: show only the most recent prior output."""

    name = "last-output-only"

    def build(self, *, task: str, history: List[str]) -> Optional[str]:
        return history[-1] if history else None


class FullTrace:
    """Alternative provider: concatenate every prior output (kept as a seam,
    not the demo default)."""

    name = "full-trace"

    def build(self, *, task: str, history: List[str]) -> Optional[str]:
        if not history:
            return None
        return "\n\n---\n\n".join(
            f"[step {i + 1}]\n{out}" for i, out in enumerate(history)
        )


def make_context_provider(name: Optional[str] = None) -> AgentContextProvider:
    import os
    name = (name or os.getenv("KG_AGENT_CONTEXT") or "last-output-only").lower()
    if name in ("last-output-only", "last", "last_output_only"):
        return LastOutputOnly()
    if name in ("full-trace", "full", "full_trace"):
        return FullTrace()
    raise ValueError(
        f"Unknown KG_AGENT_CONTEXT {name!r}. Try: last-output-only, full-trace."
    )
