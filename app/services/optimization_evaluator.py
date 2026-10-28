"""Deterministic benchmark report for heuristic and LLM allocation candidates."""
from dataclasses import dataclass
from typing import Iterable

from app.schemas.allocation import AllocationScenario


@dataclass(frozen=True)
class ScenarioMetric:
    strategy: str
    source: str
    feasible: bool
    fulfillment_rate: float
    high_priority_fulfilled: int
    estimated_cost: float
    cost_delta_vs_baseline: float | None


def benchmark_scenarios(
    scenarios: Iterable[AllocationScenario],
    valid_strategies: set[str],
    baseline_strategy: str = "priority_first",
) -> list[ScenarioMetric]:
    scenarios = list(scenarios)
    baseline = next((s for s in scenarios if s.strategy == baseline_strategy), None)
    return [
        ScenarioMetric(
            strategy=s.strategy,
            source="llm" if s.strategy.startswith("llm_native_") else "heuristic",
            feasible=s.strategy in valid_strategies,
            fulfillment_rate=s.fulfillment_rate,
            high_priority_fulfilled=s.high_priority_shortages_fulfilled,
            estimated_cost=s.total_estimated_cost,
            cost_delta_vs_baseline=(
                s.total_estimated_cost - baseline.total_estimated_cost
                if baseline is not None else None
            ),
        )
        for s in scenarios
    ]
