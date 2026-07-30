"""Reasoning-engine factory shared by every LLM-calling agent.

Groq is the primary reasoning engine per the spec. Ollama is a local
fallback - no API key, no cloud quota, no network required beyond the local
Ollama server - for when Groq's daily quota or connectivity isn't available.
Switching between them is one `.env` line (`LLM_PROVIDER=groq|ollama`), not
a code change, and every agent already goes through this single factory
rather than constructing its own `ChatGroq`.

Each agent still calls `.with_structured_output(ItsOwnSchema)` on the model
this returns, since each has a different Pydantic output schema - this
factory only decides *which* underlying chat model backs that call.
"""

from functools import lru_cache
from typing import Any

from app.core.config import get_settings


def get_active_model_name() -> str:
    """The human-readable model name for whichever provider is configured -
    for trace/log messages, so they don't lie about which model actually ran."""
    settings = get_settings()
    if settings.llm_provider == "ollama":
        return f"ollama/{settings.ollama_model}"
    return settings.groq_model


@lru_cache
def get_chat_model() -> Any:
    """Returns a LangChain chat model for whichever provider is configured.

    Cached process-wide (like the Chronos pipeline) since constructing a
    client is cheap but repeated construction is pointless - callers apply
    `.with_structured_output(...)` on top of what this returns.
    """
    settings = get_settings()

    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.ollama_temperature,
        )

    from langchain_groq import ChatGroq

    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=settings.groq_temperature,
        max_retries=settings.groq_max_retries,
    )
