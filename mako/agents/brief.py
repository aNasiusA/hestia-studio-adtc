"""Brief Agent (plan.md §5).

Runs immediately after each domain agent's execution and before the orchestrator
session begins. Its role is narrowly *next-step-decision support*: distil the raw
output into what the orchestrator needs to pick the next hop well — not a general
summary.

Adds one LLM call per hop on top of the domain agent's own call (the loop is
2 calls/hop minimum, before any orchestrator retries — worth stating plainly in
compute-cost accounting).
"""
from __future__ import annotations

from typing import Optional

from agents.llm import LLMProvider, make_provider
from agents.prompts import build_brief_system_prompt, build_brief_user_prompt
from kg.loader import KGData


class BriefAgent:
    def __init__(self, kg: KGData, *,
                 provider: Optional[LLMProvider] = None,
                 extra_instructions: str = "") -> None:
        self.kg = kg
        self.provider = provider if provider is not None else make_provider()
        # Configurable prompt: what to extract/look out for is left to the
        # builder per domain (plan.md §5).
        self.system = build_brief_system_prompt(extra_instructions)

    def summarize(self, agent: str, raw_output: str) -> str:
        label = self.kg.agent_label.get(agent, agent)
        user = build_brief_user_prompt(label, raw_output)
        return self.provider.generate(system=self.system, user=user).strip()
