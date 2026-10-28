"""LLM route-stop sequencing with exact stop-set validation.

Only terminal-to-store distance is currently known, so output route costs
remain a proxy, not real road-network tour distances.
"""
from functools import lru_cache
from pydantic import BaseModel
from app.core.llm import get_chat_model


class ProposedRoute(BaseModel):
    store_ids: list[int]
    rationale: str


@lru_cache
def _model():
    return get_chat_model().with_structured_output(ProposedRoute)


async def propose_stop_order(*, terminal_id: int, stores: list[int], distance_by_store: dict):
    if not stores:
        return []
    prompt = (
        "You are a route sequencing planner. Return each store exactly once, "
        "with no invented stops. Prefer shorter distance and delivery time, "
        "but do not claim a true optimized tour: only terminal-to-store legs "
        "are available. "
        f"Terminal: {terminal_id}. Stores: {stores}. "
        f"Known terminal legs (km, hours): {distance_by_store}."
    )
    proposal = await _model().ainvoke(prompt)
    if len(proposal.store_ids) != len(stores) or set(proposal.store_ids) != set(stores):
        return None
    return proposal.store_ids
