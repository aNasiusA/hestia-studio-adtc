"""Domain-agent executor (plan.md §12).

One concrete domain-agent prompting strategy for the demo: a shared assembly
pattern (role + capabilities + tools + injected context, templated from the KG
spec) rather than hand-authored prompts. The executor is deliberately thin — a
KG agent's identity is fully derived from the graph, so there is no per-agent
Python.

Tools are stubbed: an agent "owns" tools in the KG, and we surface them in the
prompt, but the demo does not execute real tool calls (that is not what the
method is about).
"""
from __future__ import annotations

from typing import List, Optional

from agents.context import AgentContextProvider, LastOutputOnly
from agents.llm import LLMProvider, make_provider
from agents.prompts import build_domain_system_prompt, build_domain_user_prompt
from kg.loader import KGData


class DomainAgentExecutor:
    def __init__(self, kg: KGData, *,
                 provider: Optional[LLMProvider] = None,
                 context_provider: Optional[AgentContextProvider] = None) -> None:
        self.kg = kg
        self.provider = provider if provider is not None else make_provider()
        self.context_provider = context_provider or LastOutputOnly()

    def run(self, agent: str, task: str, history: List[str]) -> str:
        """Execute ``agent``'s step and return its raw output.

        ``history`` is the ordered list of prior raw outputs; how much of it the
        agent actually sees is decided by the pluggable context provider (demo
        default: last-output-only)."""
        prior_context = self.context_provider.build(task=task, history=history)
        system = build_domain_system_prompt(self.kg, agent)
        user = build_domain_user_prompt(task, prior_context)
        return self.provider.generate(system=system, user=user)
