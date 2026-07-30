"""Decision Review Agent — eighth LangGraph node.

Modules 6 and 8 already ranked and validated the three allocation scenarios,
but only on fulfillment rate, cost, and high-priority coverage. This agent
adds the spec's remaining evaluation dimensions - inventory balance,
transportation distance, and future inventory risk - computed from real
data, then asks the configured reasoning engine (Groq or local Ollama - see
`app/core/llm.py`) for one holistic 0-100 score per scenario. The selection
itself is argmax in code, not something the LLM declares: it scores, code
picks. Only scenarios that passed Constraint Validation are considered at
all - this agent never scores an invalid plan into first place.

If nothing passed Constraint Validation (replanning attempts exhausted),
this agent falls back to reviewing Module 8's single best-effort scenario
alone and says so explicitly (`fell_back_to_invalid_scenario=True`) rather
than pretending a confident choice was made among alternatives.
"""

from collections import defaultdict
from functools import lru_cache

from loguru import logger
from pydantic import BaseModel, Field

from app.agents.state import PlanningState
from app.core.config import get_settings
from app.core.llm import get_chat_model
from app.models.entities import LocationType
from app.schemas.allocation import AllocationLine
from app.schemas.decision_review import DecisionReviewResult, ScenarioEvaluation


class _LLMScenarioScore(BaseModel):
    strategy: str
    overall_score: float = Field(ge=0, le=100)
    rationale: str


class _LLMReviewResponse(BaseModel):
    scores: list[_LLMScenarioScore]


@lru_cache
def _get_structured_llm():
    return get_chat_model().with_structured_output(_LLMReviewResponse)


def _shipped_by_terminal_product(lines: list[AllocationLine]) -> dict[tuple[int, int], int]:
    shipped: dict[tuple[int, int], int] = defaultdict(int)
    for line in lines:
        shipped[(line.terminal_id, line.product_id)] += line.quantity
    return shipped


def _inventory_balance_score(lines: list[AllocationLine], terminal_available: dict[tuple[int, int], int]) -> float:
    ratios = []
    for key, shipped_qty in _shipped_by_terminal_product(lines).items():
        available = terminal_available.get(key, 0)
        if available > 0:
            ratios.append(min(1.0, shipped_qty / available))

    if len(ratios) < 2:
        return 1.0  # nothing to compare across, trivially "balanced"

    mean = sum(ratios) / len(ratios)
    variance = sum((r - mean) ** 2 for r in ratios) / len(ratios)
    return max(0.0, 1.0 - variance**0.5)


def _future_inventory_risk_ratio(
    lines: list[AllocationLine], terminal_available: dict[tuple[int, int], int], threshold: float
) -> float:
    shipped_by_key = _shipped_by_terminal_product(lines)
    if not shipped_by_key:
        return 0.0

    drained_count = 0
    for key, shipped_qty in shipped_by_key.items():
        available = terminal_available.get(key, 0)
        if available <= 0:
            continue
        remaining_ratio = (available - shipped_qty) / available
        if remaining_ratio < threshold:
            drained_count += 1
    return drained_count / len(shipped_by_key)


def _total_distance_km(lines: list[AllocationLine], distance_by_pair: dict[tuple[int, int], float]) -> float:
    return sum(distance_by_pair.get((line.terminal_id, line.store_id), 0.0) for line in lines)


def _build_prompt(metrics_by_strategy: dict[str, dict]) -> str:
    lines = "\n".join(
        f"- {strategy}: inventory_balance={m['inventory_balance_score']:.2f} (0-1, higher=better), "
        f"total_distance={m['total_transportation_distance_km']:.1f}km, "
        f"demand_fulfillment={m['demand_fulfillment_rate']:.0%}, "
        f"future_inventory_risk={m['future_inventory_risk_ratio']:.2f} (0-1, lower=better), "
        f"total_cost={m['total_cost']:.2f}, "
        f"high_priority_covered={m['high_priority_shortages_fulfilled']}/{m['high_priority_shortages_total']}"
        for strategy, m in metrics_by_strategy.items()
    )
    return (
        "Compare these already constraint-validated shipment plan scenarios holistically:\n"
        f"{lines}\n\n"
        "Score each 0-100 reflecting overall quality, weighing (in this order of "
        "importance): fully covering high-priority stores, overall demand fulfillment, "
        "minimizing future inventory risk, balanced inventory draw-down across locations, "
        "then cost and distance as tie-breakers. Give a short one-sentence rationale per "
        "scenario."
    )


async def review_decision_node(state: PlanningState) -> dict:
    allocation = state["allocation"]

    if not allocation.scenarios:
        message = "No scenarios to review - skipped"
        logger.info(message)
        result = DecisionReviewResult(
            evaluations=[], selected_strategy=None, selection_rationale=message, fell_back_to_invalid_scenario=False
        )
        return {"decision_review": result, "trace": [message]}

    snapshot = state["master_data"]
    cost_optimization = state["cost_optimization"]
    validation = state["constraint_validation"]
    settings = get_settings()

    validity_by_strategy = {v.strategy: v.is_valid for v in validation.scenario_validations}
    reviewable_scenarios = [s for s in allocation.scenarios if validity_by_strategy.get(s.strategy, False)]

    fell_back = False
    if not reviewable_scenarios:
        reviewable_scenarios = [s for s in allocation.scenarios if s.strategy == validation.final_strategy]
        fell_back = True

    cost_by_strategy = {s.strategy: s for s in cost_optimization.scenarios}
    distance_by_pair = {
        (d.terminal_id, d.store_id): float(d.distance_km) for d in snapshot.distance_matrix
    }
    terminal_available = {
        (inv.location_id, inv.product_id): inv.available_qty
        for inv in snapshot.inventory
        if inv.location_type == LocationType.TERMINAL
    }

    metrics_by_strategy: dict[str, dict] = {}
    for scenario in reviewable_scenarios:
        cost_summary = cost_by_strategy.get(scenario.strategy)
        metrics_by_strategy[scenario.strategy] = {
            "inventory_balance_score": _inventory_balance_score(scenario.lines, terminal_available),
            "total_transportation_distance_km": _total_distance_km(scenario.lines, distance_by_pair),
            "demand_fulfillment_rate": scenario.fulfillment_rate,
            "future_inventory_risk_ratio": _future_inventory_risk_ratio(
                scenario.lines, terminal_available, settings.decision_review_critical_stock_threshold
            ),
            "total_cost": cost_summary.total_cost if cost_summary else scenario.total_estimated_cost,
            "high_priority_shortages_fulfilled": scenario.high_priority_shortages_fulfilled,
            "high_priority_shortages_total": scenario.high_priority_shortages_total,
        }

    structured_llm = _get_structured_llm()
    response: _LLMReviewResponse = await structured_llm.ainvoke(_build_prompt(metrics_by_strategy))
    score_by_strategy = {s.strategy: s for s in response.scores}

    evaluations = [
        ScenarioEvaluation(
            strategy=strategy,
            **metrics,
            overall_score=score_by_strategy[strategy].overall_score if strategy in score_by_strategy else 0.0,
            rationale=(
                score_by_strategy[strategy].rationale
                if strategy in score_by_strategy
                else "Not scored by the LLM response."
            ),
        )
        for strategy, metrics in metrics_by_strategy.items()
    ]

    best = max(evaluations, key=lambda e: e.overall_score)
    selection_rationale = best.rationale
    if fell_back:
        selection_rationale = (
            f"No scenario passed constraint validation; reviewing Module 8's best-effort pick "
            f"'{best.strategy}' alone (unresolved violations remain). {selection_rationale}"
        )

    result = DecisionReviewResult(
        evaluations=evaluations,
        selected_strategy=best.strategy,
        selection_rationale=selection_rationale,
        fell_back_to_invalid_scenario=fell_back,
    )

    message = f"Reviewed {len(evaluations)} scenario(s); selected '{best.strategy}' (score {best.overall_score:.0f})"
    logger.info(message)

    return {"decision_review": result, "trace": [message]}
