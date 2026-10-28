"""Independent critique of feasible allocation proposals.

The critic is an LLM adviser; it cannot override Python feasibility checks.
"""
from functools import lru_cache

from pydantic import BaseModel, Field
from app.core.llm import get_chat_model


class Critique(BaseModel):
    weaknesses: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    risk_level: str = "unknown"


@lru_cache
def _critic():
    return get_chat_model().with_structured_output(Critique)


async def critique_plan(*, objective: str, scenario, demand, stock, lanes) -> Critique:
    prompt = (
        "Act as a skeptical independent supply-chain optimization critic. "
        "Analyze allocation weaknesses, uncovered high-priority demand, "
        "inventory concentration, excessive transportation cost, and practical "
        "changes that preserve all stock and demand constraints. "
        "Never claim mathematical optimality. Return specific actionable improvements. "
        f"Objective: {objective}. Plan: {scenario.model_dump(mode='json')}. "
        f"Demand: {demand}. Stock: {stock}. Available lanes: {lanes}."
    )
    return await _critic().ainvoke(prompt)
