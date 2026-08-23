"""LLM provider abstraction for v3-langraph — **LangChain model classes**.

This is the LangGraph/LangSmith migration of v3's ``agents/llm.py``. The design
decisions (§ plan.md) are unchanged; the only thing that moves is the transport:
every model call now runs through a LangChain chat-model class
(``ChatAnthropic`` / ``ChatOpenAI`` / ``ChatGoogleGenerativeAI``) instead of the
provider SDKs directly. That is the whole point of the migration — LangSmith only
sees calls made through LangChain's model classes, so *all three* call sites
(domain agent, Brief agent, orchestrator) must be on them or they leave a silent
hole in the trace tree.

Pick a backend without touching code (identical env surface to v3):

    export KG_LLM_PROVIDER=anthropic | openai | gemini | ollama | local
    export KG_MODEL=<provider-specific id>     # overrides per-provider default
    export KG_BASE_URL=<url>                   # for openai-compatible endpoints
    export KG_API_KEY=<key>                    # generic key override
    export KG_MAX_TOKENS=1024                  # per-call cap

Two entry points on every provider (same signatures as v3 so the Brief and
domain agents are unchanged):

  * ``generate(system, user)`` — single-turn (domain agents, Brief agent).
  * ``chat(system, messages)`` — multi-turn convenience seam.

The orchestrator does **not** call ``chat`` — it binds the KG tools directly onto
``provider.chat_model`` via LangGraph (plan.md §4, native function-calling). The
raw LangChain model is exposed as :attr:`LangChainProvider.chat_model` for that.

There is **no mock/offline provider**. If no real LLM provider is configured
(no ``KG_LLM_PROVIDER`` and no API key), :func:`make_provider` raises instead of
degrading to a fake — a failing service surfaces as an error, never a stand-in.
"""
from __future__ import annotations

import os
from typing import Any, List, Optional, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (AIMessage, BaseMessage, HumanMessage,
                                     SystemMessage)

from envfile import load_env

# Load the repo-root .env (if any) before reading any configuration below.
# Real environment variables are never overridden. This also brings the
# LANGCHAIN_* / LANGSMITH_* tracing vars into os.environ (see configure_tracing).
load_env()

DEFAULT_MAX_TOKENS = int(os.getenv("KG_MAX_TOKENS", "1024"))

DEFAULT_MODEL = {
    "anthropic": "claude-sonnet-4-6",
    "openai":    "gpt-4o-mini",
    "gemini":    "gemini-2.5-pro",
    "ollama":    "llama3.1",
    "local":     "llama3.1",
}

Message = dict  # {"role": "user"|"assistant", "content": str}


# ----------------------------------------------------------------------
# LangSmith tracing bootstrap (plan.md §52)
# ----------------------------------------------------------------------
def configure_tracing() -> bool:
    """Wire LangSmith call-level tracing from the environment.

    The current LangSmith docs use the ``LANGSMITH_*`` names
    (``LANGSMITH_TRACING`` / ``LANGSMITH_API_KEY`` / ``LANGSMITH_PROJECT``); the
    older ``LANGCHAIN_*`` names (``LANGCHAIN_TRACING_V2`` / ``LANGCHAIN_API_KEY``
    / ``LANGCHAIN_PROJECT``) are still accepted. LangChain reads these straight
    from ``os.environ`` at invoke time, so once ``.env`` is loaded there is
    nothing to construct — this just normalises the ``LANGSMITH_*`` names onto the
    ``LANGCHAIN_*`` names the tracer reads most reliably, sets a default project
    name, and returns whether tracing is actually enabled.

    Tracing is **optional observability**, not a required service: a missing
    LangSmith key does not raise — it simply means no traces are exported. The
    *LLM* provider itself is still required and still fails hard when absent
    (:func:`make_provider`).
    """
    # Accept the current LANGSMITH_* names as well as the legacy LANGCHAIN_* ones,
    # normalising onto the LANGCHAIN_* names the LangChain tracer reads reliably.
    if not os.getenv("LANGCHAIN_TRACING_V2") and os.getenv("LANGSMITH_TRACING"):
        os.environ["LANGCHAIN_TRACING_V2"] = os.environ["LANGSMITH_TRACING"]
    if not os.getenv("LANGCHAIN_API_KEY") and os.getenv("LANGSMITH_API_KEY"):
        os.environ["LANGCHAIN_API_KEY"] = os.environ["LANGSMITH_API_KEY"]
    # Honour an explicit LANGSMITH_PROJECT so the default below never overrides it.
    if not os.getenv("LANGCHAIN_PROJECT") and os.getenv("LANGSMITH_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = os.environ["LANGSMITH_PROJECT"]

    tracing_on = os.getenv("LANGCHAIN_TRACING_V2", "").lower() in ("1", "true", "yes")
    if tracing_on and not os.getenv("LANGCHAIN_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = "kg-orchestrator-v3"
    return tracing_on and bool(os.getenv("LANGCHAIN_API_KEY"))


def _text(msg: BaseMessage) -> str:
    """Coerce a LangChain message's content to plain text.

    Most providers return ``content`` as a ``str``; some (e.g. Anthropic tool
    turns) return a list of content blocks. We concatenate any ``text`` blocks so
    the single-turn ``generate``/``chat`` seam always yields a string.
    """
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def _to_lc_messages(system: str, messages: List[Message]) -> List[BaseMessage]:
    lc: List[BaseMessage] = [SystemMessage(content=system)] if system else []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "assistant":
            lc.append(AIMessage(content=content))
        else:
            lc.append(HumanMessage(content=content))
    return lc


# ----------------------------------------------------------------------
# Provider protocol + LangChain-backed implementation
# ----------------------------------------------------------------------
class LLMProvider(Protocol):
    name: str
    model: str
    chat_model: BaseChatModel

    def generate(self, *, system: str, user: str,
                 max_tokens: int = DEFAULT_MAX_TOKENS) -> str: ...

    def chat(self, *, system: str, messages: List[Message],
             max_tokens: int = DEFAULT_MAX_TOKENS) -> str: ...


class LangChainProvider:
    """Wraps a LangChain ``BaseChatModel`` behind v3's provider interface.

    The wrapper keeps v3's ``generate``/``chat`` seam so the Brief and domain
    agents are byte-for-byte unchanged, while :attr:`chat_model` exposes the raw
    LangChain model for the orchestrator's ``bind_tools`` path (plan.md §4).
    """

    def __init__(self, name: str, chat_model: BaseChatModel, model: str) -> None:
        self.name = name
        self.chat_model = chat_model
        self.model = model

    def _model_for(self, max_tokens: int):
        # The model is constructed with DEFAULT_MAX_TOKENS; honour a differing
        # per-call cap by rebinding, without rebuilding the client.
        if max_tokens == DEFAULT_MAX_TOKENS:
            return self.chat_model
        return self.chat_model.bind(max_tokens=max_tokens)

    def generate(self, *, system: str, user: str,
                 max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
        return self.chat(system=system,
                         messages=[{"role": "user", "content": user}],
                         max_tokens=max_tokens)

    def chat(self, *, system: str, messages: List[Message],
             max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
        lc = _to_lc_messages(system, messages)
        reply = self._model_for(max_tokens).invoke(lc)
        return _text(reply)


# ----------------------------------------------------------------------
# Model construction
# ----------------------------------------------------------------------
def _autodetect() -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        return "gemini"
    raise RuntimeError(
        "No LLM provider is configured. Set KG_LLM_PROVIDER (anthropic | openai | "
        "gemini | ollama | local) and the matching API key / endpoint. There is no "
        "mock fallback — a missing or failing LLM service is surfaced as an error, "
        "not replaced by a stand-in."
    )


def _build_chat_model(name: str, model: str, max_tokens: int) -> BaseChatModel:
    if name == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, max_tokens=max_tokens, timeout=60)

    if name in ("openai", "ollama", "local"):
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("KG_BASE_URL")
        api_key = os.getenv("KG_API_KEY") or os.getenv("OPENAI_API_KEY")
        if name in ("ollama", "local"):
            base_url = base_url or "http://localhost:11434/v1"
            api_key = api_key or "ollama"
        kwargs: dict = {"model": model, "max_tokens": max_tokens}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        return ChatOpenAI(**kwargs)

    if name == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        kwargs = {"model": model, "max_output_tokens": max_tokens}
        if api_key:
            kwargs["google_api_key"] = api_key
        return ChatGoogleGenerativeAI(**kwargs)

    raise ValueError(
        f"Unknown LLM provider {name!r}. "
        "Try one of: anthropic, openai, gemini, ollama, local."
    )


def make_provider(name: Optional[str] = None,
                  model: Optional[str] = None,
                  *, max_tokens: int = DEFAULT_MAX_TOKENS) -> LLMProvider:
    """Construct the LangChain-backed provider (env-selected, same as v3).

    Also enables LangSmith tracing if the environment asks for it — see
    :func:`configure_tracing`. Tracing being off never blocks construction.
    """
    configure_tracing()
    name = (name or os.getenv("KG_LLM_PROVIDER") or _autodetect()).lower()
    model = model or os.getenv("KG_MODEL") or DEFAULT_MODEL.get(name, "default")
    chat_model = _build_chat_model(name, model, max_tokens)
    return LangChainProvider(name, chat_model, model)
