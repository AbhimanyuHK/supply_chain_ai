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


def reset_llm_client_caches() -> None:
    """Drops every cached chat-model client: this factory's own `get_chat_model`
    cache, plus each LLM-calling agent's own `.with_structured_output(...)`-wrapped
    cache (`_get_structured_llm`/`_get_ranking_llm` in supply_planning_agent,
    allocation_agent, decision_review_agent, final_recommendation_agent).

    Only long-lived processes that call `asyncio.run()` more than once need this
    (e.g. the Streamlit demo dashboard, which reruns the whole workflow on every
    click within one process) - each cached client holds an httpx-based async
    client that can end up bound to whatever event loop was running when it was
    first built. `asyncio.run()` tears its loop down when it returns, so a client
    left over from a previous run risks a stale-loop error ("Event loop is
    closed") the next time it's touched. Calling this at the end of a run drops
    the references while the loop that created them is still alive, so cleanup
    happens now rather than being left to garbage collection at some later,
    unpredictable point (possibly after the loop has already closed). The CLI
    script and the FastAPI server never need this - each keeps exactly one event
    loop alive for its whole process lifetime.
    """
    get_chat_model.cache_clear()

    from app.agents import (
        allocation_agent,
        decision_review_agent,
        final_recommendation_agent,
        supply_planning_agent,
    )

    supply_planning_agent._get_structured_llm.cache_clear()
    allocation_agent._get_ranking_llm.cache_clear()
    decision_review_agent._get_structured_llm.cache_clear()
    final_recommendation_agent._get_structured_llm.cache_clear()
