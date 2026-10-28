"""Benchmark utility tests; no external model or database required."""
from app.schemas.allocation import AllocationScenario
from app.services.optimization_evaluator import benchmark_scenarios


def scenario(strategy, cost, fulfillment):
    return AllocationScenario(
        strategy=strategy,
        lines=[],
        total_quantity_allocated=5,
        total_shortage_quantity=10,
        fulfillment_rate=fulfillment,
        total_estimated_cost=cost,
        high_priority_shortages_fulfilled=1,
        high_priority_shortages_total=2,
    )


def test_benchmark_compares_costs_and_feasibility():
    baseline = scenario("priority_first", 100, 0.5)
    candidate = scenario("llm_native_1", 80, 0.7)
    result = benchmark_scenarios(
        [baseline, candidate], valid_strategies={"priority_first", "llm_native_1"}
    )
    assert result[1].source == "llm"
    assert result[1].feasible is True
    assert result[1].cost_delta_vs_baseline == -20
    assert result[1].fulfillment_rate == 0.7


def test_benchmark_marks_invalid_and_missing_baseline():
    candidate = scenario("llm_native_2", 90, 0.6)
    result = benchmark_scenarios([candidate], valid_strategies=set())
    assert result[0].feasible is False
    assert result[0].cost_delta_vs_baseline is None
