"""Agent-execution layer for v3.

Two LLM-backed roles the orchestration loop drives (plan.md §5, §12):

  * :class:`~agents.domain.DomainAgentExecutor` — runs one KG agent's step,
    grounded only in that agent's own spec (capabilities, tools, specialty).
  * :class:`~agents.brief.BriefAgent` — distils a domain agent's raw output into
    a short, next-step-decision-oriented brief for the orchestrator.

The LLM provider (:mod:`agents.llm`) is swappable by env var. A real provider is
required — there is no mock/offline fallback, so a missing or failing LLM service
surfaces as an error rather than a fake result.
"""
from agents.llm import LLMProvider, make_provider  # noqa: F401
from agents.domain import DomainAgentExecutor  # noqa: F401
from agents.brief import BriefAgent  # noqa: F401
from agents.context import AgentContextProvider, LastOutputOnly  # noqa: F401
