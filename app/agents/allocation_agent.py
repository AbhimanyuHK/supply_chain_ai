"""Allocation Agent — fifth LangGraph node.

Module 5 (Supply Planning) generated candidate plans *independently* per
shortage — it has no visibility into the fact that two different stores'
shortages might both want to draw from the same scarce terminal stock. This
agent resolves that: it builds several complete, internally-consistent
allocation scenarios that treat each terminal's stock as a real shared
constraint, then asks the configured reasoning engine (Groq or local Ollama
- see `app/core/llm.py`) to rank the scenarios.

Division of labor with the LLM, same pattern as Module 5 but at a coarser
grain: the three allocation strategies below are plain deterministic Python
(conservation of stock across many shipment lines is exactly the kind of
multi-step arithmetic LLMs are unreliable at). The LLM is only asked to
*rank* the resulting scenario summaries and explain the trade-offs —
mirroring how a planner would compare finished proposals, not compute them.

The three strategies answer the spec's own allocation questions directly:
  - "Should high-priority stores receive inventory first?"      -> priority_first
  - "Should inventory be split across multiple terminals?"       -> balanced
  - (an LLM-driven, score-led baseline for comparison)            -> score_first

Scope boundary: this agent does not do final cost optimization (the future
Cost Optimization Agent refines these cost estimates with real fleet data)
and does not reject/validate plans against business constraints (the future
Constraint Validation Agent's job). It ranks scenarios; it doesn't pick one.
"""

import math
from collections import defaultdict
from functools import lru_cache
from typing import NamedTuple

from loguru import logger
from pydantic import BaseModel, Field

from app.agents.state import PlanningState
from app.agents.llm_native_optimizer import generate_llm_scenarios
from app.core.llm import get_active_model_name, get_chat_model
from app.models.entities import LocationType
from app.schemas.allocation import AllocationLine, AllocationResult, AllocationScenario
from app.schemas.supply_planning import CandidatePlan


class _ShortageInfo(NamedTuple):
    store_id: int
    product_id: int
    shortage_qty: float
    priority: int

    @property
    def key(self) -> tuple[int, int]:
        return (self.store_id, self.product_id)


class _LLMScenarioRank(BaseModel):
    strategy: str
    rank: int = Field(ge=1)
    rationale: str


class _LLMRankingResponse(BaseModel):
    rankings: list[_LLMScenarioRank]


@lru_cache
def _get_ranking_llm():
    return get_chat_model().with_structured_output(_LLMRankingResponse)


def _priority_first_lines(
    shortages: list[_ShortageInfo],
    candidates_by_shortage: dict[tuple[int, int], list[CandidatePlan]],
    terminal_stock: dict[tuple[int, int], int],
) -> list[AllocationLine]:
    """Highest-priority stores (lowest priority number) drain shared stock first."""
    stock = dict(terminal_stock)
    ordered = sorted(shortages, key=lambda s: (s.priority, -s.shortage_qty))
    lines: list[AllocationLine] = []

    for shortage in ordered:
        remaining_need = shortage.shortage_qty
        candidates = sorted(candidates_by_shortage.get(shortage.key, []), key=lambda c: c.score, reverse=True)
        for candidate in candidates:
            if remaining_need <= 0:
                break
            key = (candidate.terminal_id, candidate.product_id)
            available = stock.get(key, 0)
            qty = min(candidate.quantity, available, math.ceil(remaining_need))
            if qty <= 0:
                continue
            lines.append(
                AllocationLine(
                    terminal_id=candidate.terminal_id,
                    store_id=shortage.store_id,
                    product_id=shortage.product_id,
                    quantity=qty,
                    estimated_transport_cost=candidate.estimated_transport_cost,
                    estimated_delivery_hours=candidate.estimated_delivery_hours,
                )
            )
            stock[key] = available - qty
            remaining_need -= qty

    return lines


def _score_first_lines(
    shortages: list[_ShortageInfo],
    candidates_by_shortage: dict[tuple[int, int], list[CandidatePlan]],
    terminal_stock: dict[tuple[int, int], int],
) -> list[AllocationLine]:
    """Globally greedy by Module 5's candidate score, ignoring store priority entirely."""
    stock = dict(terminal_stock)
    remaining_need = {s.key: s.shortage_qty for s in shortages}

    all_pairs = [
        (shortage, candidate)
        for shortage in shortages
        for candidate in candidates_by_shortage.get(shortage.key, [])
    ]
    all_pairs.sort(key=lambda pair: pair[1].score, reverse=True)

    lines: list[AllocationLine] = []
    for shortage, candidate in all_pairs:
        need = remaining_need[shortage.key]
        if need <= 0:
            continue
        key = (candidate.terminal_id, candidate.product_id)
        available = stock.get(key, 0)
        qty = min(candidate.quantity, available, math.ceil(need))
        if qty <= 0:
            continue
        lines.append(
            AllocationLine(
                terminal_id=candidate.terminal_id,
                store_id=shortage.store_id,
                product_id=shortage.product_id,
                quantity=qty,
                estimated_transport_cost=candidate.estimated_transport_cost,
                estimated_delivery_hours=candidate.estimated_delivery_hours,
            )
        )
        stock[key] = available - qty
        remaining_need[shortage.key] -= qty

    return lines


def _balanced_lines(
    shortages: list[_ShortageInfo],
    candidates_by_shortage: dict[tuple[int, int], list[CandidatePlan]],
    terminal_stock: dict[tuple[int, int], int],
) -> list[AllocationLine]:
    """When multiple shortages contest the same terminal's stock, split it proportionally
    to each shortage's size rather than letting one fully starve the others."""
    asks: list[tuple[_ShortageInfo, CandidatePlan, int]] = []
    for shortage in shortages:
        candidates = candidates_by_shortage.get(shortage.key, [])
        if not candidates:
            continue
        best = max(candidates, key=lambda c: c.score)
        requested = min(best.quantity, math.ceil(shortage.shortage_qty))
        if requested > 0:
            asks.append((shortage, best, requested))

    by_resource: dict[tuple[int, int], list[tuple[_ShortageInfo, CandidatePlan, int]]] = defaultdict(list)
    for ask in asks:
        by_resource[(ask[1].terminal_id, ask[1].product_id)].append(ask)

    lines: list[AllocationLine] = []
    for resource_key, group in by_resource.items():
        available = terminal_stock.get(resource_key, 0)
        total_requested = sum(requested for _, _, requested in group)
        scale = 1.0 if total_requested <= available else (available / total_requested if total_requested > 0 else 0.0)

        for shortage, candidate, requested in group:
            qty = int(requested * scale)
            if qty <= 0:
                continue
            lines.append(
                AllocationLine(
                    terminal_id=candidate.terminal_id,
                    store_id=shortage.store_id,
                    product_id=shortage.product_id,
                    quantity=qty,
                    estimated_transport_cost=candidate.estimated_transport_cost,
                    estimated_delivery_hours=candidate.estimated_delivery_hours,
                )
            )

    return lines


def _summarize_scenario(
    strategy: str,
    lines: list[AllocationLine],
    shortages: list[_ShortageInfo],
    high_priority_store_ids: set[int],
) -> AllocationScenario:
    total_quantity_allocated = sum(line.quantity for line in lines)
    total_shortage_quantity = sum(s.shortage_qty for s in shortages)
    fulfillment_rate = (
        round(total_quantity_allocated / total_shortage_quantity, 4) if total_shortage_quantity > 0 else 0.0
    )
    total_estimated_cost = sum(line.estimated_transport_cost for line in lines)

    allocated_by_shortage: dict[tuple[int, int], int] = defaultdict(int)
    for line in lines:
        allocated_by_shortage[(line.store_id, line.product_id)] += line.quantity

    high_priority_shortages = [s for s in shortages if s.store_id in high_priority_store_ids]
    fulfilled = sum(
        1 for s in high_priority_shortages if allocated_by_shortage.get(s.key, 0) >= s.shortage_qty
    )

    return AllocationScenario(
        strategy=strategy,
        lines=lines,
        total_quantity_allocated=total_quantity_allocated,
        total_shortage_quantity=total_shortage_quantity,
        fulfillment_rate=fulfillment_rate,
        total_estimated_cost=total_estimated_cost,
        high_priority_shortages_fulfilled=fulfilled,
        high_priority_shortages_total=len(high_priority_shortages),
    )


def _build_ranking_prompt(scenarios: list[AllocationScenario]) -> str:
    lines = "\n".join(
        f"- {s.strategy}: fulfillment_rate={s.fulfillment_rate:.0%}, "
        f"total_cost={s.total_estimated_cost:.2f}, "
        f"high_priority_fulfilled={s.high_priority_shortages_fulfilled}/{s.high_priority_shortages_total}, "
        f"shipment_lines={len(s.lines)}"
        for s in scenarios
    )
    return (
        "Compare these candidate strategies for allocating scarce terminal inventory to "
        f"cover store shortages:\n{lines}\n\n"
        "Rank them from best (1) to worst, in this order of importance: (1) fulfilling "
        "high-priority stores, (2) overall shortage fulfillment rate, (3) minimizing total "
        "transportation cost. Give a short one-sentence rationale for each strategy's rank."
    )


async def _rank_scenarios(scenarios: list[AllocationScenario]) -> list[AllocationScenario]:
    structured_llm = _get_ranking_llm()
    response: _LLMRankingResponse = await structured_llm.ainvoke(_build_ranking_prompt(scenarios))

    rank_by_strategy = {r.strategy: r for r in response.rankings}
    used_ranks = set()
    next_fallback_rank = len(scenarios) + 1

    for scenario in scenarios:
        llm_rank = rank_by_strategy.get(scenario.strategy)
        if llm_rank is not None and llm_rank.rank not in used_ranks:
            scenario.rank = llm_rank.rank
            scenario.rationale = llm_rank.rationale
            used_ranks.add(llm_rank.rank)
        else:
            scenario.rank = next_fallback_rank
            scenario.rationale = "Not distinctly ranked by the LLM response."
            next_fallback_rank += 1

    return sorted(scenarios, key=lambda s: s.rank)


async def allocate_node(state: PlanningState) -> dict:
    shortage_records = state["inventory_analysis"].shortages

    if not shortage_records:
        message = "No shortages to allocate - skipped scenario generation"
        logger.info(message)
        return {"allocation": AllocationResult(scenarios=[], recommended_strategy=None), "trace": [message]}

    snapshot = state["master_data"]
    candidate_plans = state["supply_planning"].candidate_plans
    business_rules = snapshot.business_rules

    store_priority_by_id = {s.store_id: s.priority for s in snapshot.stores}
    shortages = [
        _ShortageInfo(
            store_id=record.location_id,
            product_id=record.product_id,
            shortage_qty=record.shortage_qty,
            priority=store_priority_by_id.get(record.location_id, 3),
        )
        for record in shortage_records
    ]

    candidates_by_shortage: dict[tuple[int, int], list[CandidatePlan]] = defaultdict(list)
    for plan in candidate_plans:
        if plan.quantity > 0:
            candidates_by_shortage[(plan.store_id, plan.product_id)].append(plan)

    terminal_stock: dict[tuple[int, int], int] = {
        (inv.location_id, inv.product_id): inv.available_qty
        for inv in snapshot.inventory
        if inv.location_type == LocationType.TERMINAL
    }

    high_priority_store_ids = {
        s.store_id for s in snapshot.stores if s.priority <= business_rules.high_priority_store_threshold
    }

    strategy_lines = {
        "priority_first": _priority_first_lines(shortages, candidates_by_shortage, terminal_stock),
        "score_first": _score_first_lines(shortages, candidates_by_shortage, terminal_stock),
        "balanced": _balanced_lines(shortages, candidates_by_shortage, terminal_stock),
    }
    scenarios = [
        _summarize_scenario(name, lines, shortages, high_priority_store_ids)
        for name, lines in strategy_lines.items()
    ]

    # Optional LLM-native search; existing strategies remain benchmark baselines.
    from app.core.config import get_settings
    settings = get_settings()
    if settings.llm_native_optimizer_enabled:
        scenarios.extend(await generate_llm_scenarios(
            shortages=shortages,
            candidate_plans=candidate_plans,
            terminal_stock=terminal_stock,
            high_priority_store_ids=high_priority_store_ids,
            summarize=_summarize_scenario,
            iterations=settings.llm_optimizer_iterations,
            objective=state["request"].optimization_objective,
        ))

    ranked = await _rank_scenarios(scenarios)
    result = AllocationResult(scenarios=ranked, recommended_strategy=ranked[0].strategy)

    message = (
        f"Generated {len(scenarios)} allocation scenarios via {get_active_model_name()}; "
        f"recommended: {result.recommended_strategy}"
    )
    logger.info(message)

    return {"allocation": result, "trace": [message]}
