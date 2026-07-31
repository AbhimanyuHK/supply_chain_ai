from app.agents.scenario_selection import select_reviewable_scenarios
from app.schemas.allocation import AllocationLine, AllocationResult, AllocationScenario
from app.schemas.constraint_validation import ConstraintValidationResult, ScenarioValidation


def _line() -> AllocationLine:
    return AllocationLine(
        terminal_id=1, store_id=1, product_id=1, quantity=10,
        estimated_transport_cost=10.0, estimated_delivery_hours=1.0,
    )


def _scenario(strategy: str) -> AllocationScenario:
    return AllocationScenario(
        strategy=strategy, lines=[_line()], total_quantity_allocated=10,
        total_shortage_quantity=10, fulfillment_rate=1.0, total_estimated_cost=100.0,
        high_priority_shortages_fulfilled=1, high_priority_shortages_total=1,
    )


def test_returns_only_valid_scenarios_when_some_are_valid():
    allocation = AllocationResult(scenarios=[_scenario("priority_first"), _scenario("score_first")])
    validation = ConstraintValidationResult(
        scenario_validations=[
            ScenarioValidation(strategy="priority_first", violations=[], is_valid=True),
            ScenarioValidation(strategy="score_first", violations=[], is_valid=False),
        ],
        final_strategy="priority_first",
        unresolved_violations=[],
        replanning_triggered=False,
    )

    reviewable, fell_back = select_reviewable_scenarios(allocation, validation)

    assert [s.strategy for s in reviewable] == ["priority_first"]
    assert fell_back is False


def test_falls_back_to_final_strategy_when_none_are_valid():
    allocation = AllocationResult(scenarios=[_scenario("priority_first"), _scenario("score_first")])
    validation = ConstraintValidationResult(
        scenario_validations=[
            ScenarioValidation(strategy="priority_first", violations=[], is_valid=False),
            ScenarioValidation(strategy="score_first", violations=[], is_valid=False),
        ],
        final_strategy="score_first",
        unresolved_violations=[],
        replanning_triggered=False,
    )

    reviewable, fell_back = select_reviewable_scenarios(allocation, validation)

    assert [s.strategy for s in reviewable] == ["score_first"]
    assert fell_back is True
