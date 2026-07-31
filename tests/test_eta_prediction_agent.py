import pytest

from app.agents.eta_prediction_agent import predict_eta_node
from app.core.business_rules import BusinessRules
from app.schemas.constraint_validation import ConstraintValidationResult
from app.schemas.cost_optimization import CostedLine, CostOptimizationResult, ScenarioCostSummary
from app.schemas.route_planning import (
    RoutePlanningResult,
    RouteStop,
    ScenarioRoutePlan,
    VehicleRoute,
)

BUSINESS_RULES = BusinessRules(max_lead_time_days=2, eta_variance_buffer_pct=0.1)


def _costed_line(vehicle_id, vehicle_capacity_exceeded):
    return CostedLine(
        terminal_id=1, store_id=1, product_id=1, quantity=5, vehicle_id=vehicle_id,
        transportation_cost=10.0, handling_cost=1.0, holding_cost=1.0, delay_penalty=0.0,
        total_cost=12.0, vehicle_capacity_exceeded=vehicle_capacity_exceeded,
    )


def _cost_optimization(vehicle_id, vehicle_capacity_exceeded) -> CostOptimizationResult:
    return CostOptimizationResult(
        scenarios=[
            ScenarioCostSummary(
                strategy="priority_first", lines=[_costed_line(vehicle_id, vehicle_capacity_exceeded)],
                total_transportation_cost=10.0, total_handling_cost=1.0, total_holding_cost=1.0,
                total_delay_penalty=0.0, total_cost=12.0, high_priority_shortages_fulfilled=1,
                high_priority_shortages_total=1, fully_satisfies_high_priority=True, fulfillment_rate=1.0,
            )
        ],
        recommended_strategy="priority_first",
        recommendation_rationale="",
    )


def _constraint_validation() -> ConstraintValidationResult:
    return ConstraintValidationResult(
        scenario_validations=[], final_strategy="priority_first", unresolved_violations=[],
        replanning_triggered=False,
    )


def _route_planning(travel_time_hours) -> RoutePlanningResult:
    return RoutePlanningResult(
        scenario_routes=[
            ScenarioRoutePlan(
                strategy="priority_first",
                vehicle_routes=[
                    VehicleRoute(
                        vehicle_id=1, terminal_id=1,
                        stops=[RouteStop(sequence=1, store_id=1, distance_km=10.0, travel_time_hours=travel_time_hours)],
                        total_route_distance_km=10.0, route_transportation_cost=100.0,
                    )
                ],
            )
        ]
    )


def _state(route_planning, cost_optimization, constraint_validation, replanning_attempts=0):
    return {
        "route_planning": route_planning,
        "master_data": type("Snap", (), {"business_rules": BUSINESS_RULES})(),
        "cost_optimization": cost_optimization,
        "constraint_validation": constraint_validation,
        "replanning_attempts": replanning_attempts,
    }


@pytest.mark.asyncio
async def test_not_at_risk_when_within_lead_time_and_no_other_flags():
    # travel_time=1h, buffer 10% -> predicted_eta=1.1h, well under max_lead_time (48h).
    state = _state(_route_planning(1.0), _cost_optimization(vehicle_id=1, vehicle_capacity_exceeded=False), _constraint_validation())

    update = await predict_eta_node(state)

    stop = update["eta_prediction"].scenario_predictions[0].stop_etas[0]
    assert stop.at_risk is False
    assert stop.risk_reasons == []
    assert stop.suggested_contingency is None


@pytest.mark.asyncio
async def test_at_risk_when_exceeding_max_lead_time():
    # travel_time=50h, buffer 10% -> predicted_eta=55h, exceeds max_lead_time (48h).
    state = _state(_route_planning(50.0), _cost_optimization(vehicle_id=1, vehicle_capacity_exceeded=False), _constraint_validation())

    update = await predict_eta_node(state)

    stop = update["eta_prediction"].scenario_predictions[0].stop_etas[0]
    assert stop.at_risk is True
    assert "exceeds_max_lead_time" in stop.risk_reasons


@pytest.mark.asyncio
async def test_at_risk_when_vehicle_capacity_exceeded():
    state = _state(_route_planning(1.0), _cost_optimization(vehicle_id=1, vehicle_capacity_exceeded=True), _constraint_validation())

    update = await predict_eta_node(state)

    stop = update["eta_prediction"].scenario_predictions[0].stop_etas[0]
    assert stop.at_risk is True
    assert "vehicle_capacity_exceeded" in stop.risk_reasons


@pytest.mark.asyncio
async def test_at_risk_when_run_needed_replanning():
    # constraint_validation.replanning_triggered is always False on the result that
    # actually reaches this node (route_after_validation only proceeds downstream when
    # it's False) - the real, persistent signal is the run-level replanning_attempts
    # counter, which is what this agent must read instead.
    state = _state(
        _route_planning(1.0), _cost_optimization(vehicle_id=1, vehicle_capacity_exceeded=False),
        _constraint_validation(), replanning_attempts=1,
    )

    update = await predict_eta_node(state)

    stop = update["eta_prediction"].scenario_predictions[0].stop_etas[0]
    assert stop.at_risk is True
    assert "replanning_triggered" in stop.risk_reasons


@pytest.mark.asyncio
async def test_multiple_reasons_all_recorded():
    state = _state(
        _route_planning(50.0), _cost_optimization(vehicle_id=1, vehicle_capacity_exceeded=True),
        _constraint_validation(), replanning_attempts=1,
    )

    update = await predict_eta_node(state)

    stop = update["eta_prediction"].scenario_predictions[0].stop_etas[0]
    assert set(stop.risk_reasons) == {"exceeds_max_lead_time", "vehicle_capacity_exceeded", "replanning_triggered"}
    assert update["eta_prediction"].scenario_predictions[0].at_risk_count == 1


@pytest.mark.asyncio
async def test_no_routes_short_circuits():
    state = {
        "route_planning": RoutePlanningResult(scenario_routes=[]),
        "master_data": type("Snap", (), {"business_rules": BUSINESS_RULES})(),
        "cost_optimization": CostOptimizationResult(scenarios=[], recommended_strategy=None, recommendation_rationale=""),
        "constraint_validation": _constraint_validation(),
    }

    update = await predict_eta_node(state)

    assert update["eta_prediction"].scenario_predictions == []
