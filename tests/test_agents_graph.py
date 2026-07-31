import datetime

import pytest
from sqlalchemy import select

from app.agents.demand_forecast_agent import forecast_demand_node
from app.agents.graph import build_graph, run_planning_workflow
from app.agents.master_data_agent import load_master_data_node
from app.core.config import get_settings
from app.database.repositories import PlanningRunRepository
from app.models.entities import (
    DemandHistory,
    DistanceMatrix,
    Fleet,
    Inventory,
    LocationType,
    PlanningRunStatus,
    Product,
    Shipment,
    Store,
    Terminal,
    VehicleStatus,
)
from app.schemas.planning import PlanningRequest
from app.schemas.planning_run import PlanningRunRead
from tests.conftest import requires_llm_configured as requires_groq_key


def _with_fleet_module_enabled(monkeypatch) -> None:
    real_settings = get_settings()
    monkeypatch.setattr(
        "app.agents.graph.get_settings",
        lambda: real_settings.model_copy(update={"fleet_module_enabled": True}),
    )


async def _seed_minimal(
    session_factory,
    with_demand_history: bool = False,
    store_available_qty: int = 50,
    with_distance_matrix: bool = False,
    store_capacity: int = 100,
    with_fleet: bool = False,
) -> None:
    async with session_factory() as session:
        store = Store(store_name="Graph Store", latitude=1, longitude=1, capacity=store_capacity, priority=1)
        terminal = Terminal(terminal_name="Graph Terminal", latitude=2, longitude=2, capacity=1000)
        product = Product(sku="SKU-GRAPH", name="Graph Product", category="Cat", weight=1, volume=1, cost=10)
        session.add_all([store, terminal, product])
        await session.flush()

        session.add_all(
            [
                Inventory(
                    location_type=LocationType.STORE,
                    location_id=store.store_id,
                    product_id=product.product_id,
                    available_qty=store_available_qty,
                    incoming_qty=10,
                ),
                Inventory(
                    location_type=LocationType.TERMINAL,
                    location_id=terminal.terminal_id,
                    product_id=product.product_id,
                    available_qty=500,
                ),
            ]
        )

        if with_distance_matrix:
            session.add(
                DistanceMatrix(
                    terminal_id=terminal.terminal_id, store_id=store.store_id, distance_km=25.0, travel_time=0.6
                )
            )

        if with_fleet:
            session.add(
                Fleet(
                    terminal_id=terminal.terminal_id, vehicle_type="truck", capacity_weight=1000,
                    capacity_volume=1000, cost_per_km=5.0, fixed_cost=500.0, status=VehicleStatus.AVAILABLE,
                )
            )

        if with_demand_history:
            today = datetime.date.today()
            for day_offset in range(30, 0, -1):
                session.add(
                    DemandHistory(
                        date=today - datetime.timedelta(days=day_offset),
                        store_id=store.store_id,
                        product_id=product.product_id,
                        sales_qty=(day_offset % 7) + 1,
                    )
                )

        await session.commit()


@pytest.mark.asyncio
async def test_load_master_data_node_returns_snapshot_and_trace(committed_db):
    await _seed_minimal(committed_db)

    state = {"request": PlanningRequest(), "trace": [], "errors": []}
    update = await load_master_data_node(state)

    assert "master_data" in update
    snapshot = update["master_data"]
    assert len(snapshot.stores) == 1
    assert len(snapshot.terminals) == 1
    assert len(snapshot.products) == 1
    assert len(update["trace"]) == 1
    assert "Loaded master data" in update["trace"][0]


@pytest.mark.asyncio
async def test_forecast_demand_node_skips_pairs_with_no_history(committed_db):
    await _seed_minimal(committed_db, with_demand_history=False)

    request = PlanningRequest()
    master_data_update = await load_master_data_node({"request": request, "trace": [], "errors": []})
    state = {"request": request, "master_data": master_data_update["master_data"], "trace": [], "errors": []}

    update = await forecast_demand_node(state)

    result = update["demand_forecast"]
    assert result.forecasts == []
    assert len(result.skipped_pairs) == 1


@pytest.mark.asyncio
async def test_forecast_demand_node_produces_forecast_when_history_exists(committed_db):
    await _seed_minimal(committed_db, with_demand_history=True)

    request = PlanningRequest(demand_history_window_days=90)
    master_data_update = await load_master_data_node({"request": request, "trace": [], "errors": []})
    state = {"request": request, "master_data": master_data_update["master_data"], "trace": [], "errors": []}

    update = await forecast_demand_node(state)

    result = update["demand_forecast"]
    assert result.skipped_pairs == []
    assert len(result.forecasts) == result.horizon_days
    assert all(p.predicted_qty >= 0 for p in result.forecasts)
    assert all(p.low_qty <= p.predicted_qty <= p.high_qty for p in result.forecasts)
    # Forecast dates start the day after the planning date and are contiguous.
    dates = sorted(p.date for p in result.forecasts)
    assert dates[0] == request.planning_date + datetime.timedelta(days=1)
    assert dates == [dates[0] + datetime.timedelta(days=i) for i in range(len(dates))]


@pytest.mark.asyncio
async def test_build_graph_has_expected_nodes():
    graph = build_graph()
    node_names = set(graph.get_graph().nodes.keys())
    assert {
        "load_master_data",
        "forecast_demand",
        "analyze_inventory",
        "plan_supply",
        "allocate",
        "optimize_cost",
        "validate_constraints",
        "review_decision",
        "recommend_final",
        "__start__",
        "__end__",
    } <= node_names


@pytest.mark.asyncio
async def test_run_planning_workflow_end_to_end_no_shortage(committed_db):
    # store_available_qty=50 + incoming=10 comfortably covers the ~4/day average demand
    # from the seeded history, so no shortage -> Supply Planning makes zero Groq calls,
    # meaning this test needs no API key.
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    request = PlanningRequest(planning_date=datetime.date.today())
    result = await run_planning_workflow(request)

    assert result["request"] == request
    assert len(result["master_data"].stores) == 1
    assert len(result["demand_forecast"].forecasts) == result["demand_forecast"].horizon_days
    # 2 inventory rows seeded (1 store + 1 terminal); only the store gets safety-stock math.
    assert len(result["inventory_analysis"].records) == 2
    store_records = [r for r in result["inventory_analysis"].records if r.location_type.value == "store"]
    assert store_records[0].avg_daily_demand is not None
    assert result["inventory_analysis"].shortages == []
    assert result["supply_planning"].candidate_plans == []
    assert result["supply_planning"].unresolved_shortages == []
    # No shortages -> Allocation also makes zero Groq calls.
    assert result["allocation"].scenarios == []
    assert result["allocation"].recommended_strategy is None
    assert result["cost_optimization"].scenarios == []
    assert result["cost_optimization"].recommended_strategy is None
    assert result["constraint_validation"].scenario_validations == []
    assert result["constraint_validation"].final_strategy is None
    assert result["constraint_validation"].replanning_triggered is False
    assert result["decision_review"].evaluations == []
    assert result["decision_review"].selected_strategy is None
    assert result["decision_review"].fell_back_to_invalid_scenario is False
    assert result["final_recommendation"].selected_strategy is None
    assert result["final_recommendation"].shipment_plan == []
    assert len(result["trace"]) == 9
    assert result["errors"] == []


@requires_groq_key
@pytest.mark.asyncio
async def test_run_planning_workflow_end_to_end_with_shortage_calls_groq(committed_db):
    # Near-zero store stock -> guaranteed shortage -> Supply Planning must call Groq
    # and produce at least one real candidate plan sourced from the seeded terminal.
    await _seed_minimal(
        committed_db, with_demand_history=True, store_available_qty=1, with_distance_matrix=True
    )

    request = PlanningRequest(planning_date=datetime.date.today())
    result = await run_planning_workflow(request)

    assert len(result["inventory_analysis"].shortages) == 1
    assert len(result["supply_planning"].candidate_plans) >= 1
    plan = result["supply_planning"].candidate_plans[0]
    assert plan.estimated_transport_cost > 0
    assert 0 <= plan.score <= 100
    assert plan.rationale

    allocation = result["allocation"]
    assert len(allocation.scenarios) == 3
    assert {s.strategy for s in allocation.scenarios} == {"priority_first", "score_first", "balanced"}
    assert allocation.recommended_strategy in {"priority_first", "score_first", "balanced"}
    assert all(s.rank is not None and s.rationale for s in allocation.scenarios)

    cost_optimization = result["cost_optimization"]
    assert len(cost_optimization.scenarios) == 3
    assert {s.strategy for s in cost_optimization.scenarios} == {"priority_first", "score_first", "balanced"}
    assert cost_optimization.recommended_strategy in {"priority_first", "score_first", "balanced"}
    for scenario in cost_optimization.scenarios:
        assert scenario.total_cost >= 0
        assert scenario.lines
    assert cost_optimization.recommendation_rationale

    validation = result["constraint_validation"]
    assert len(validation.scenario_validations) == 3
    assert {sv.strategy for sv in validation.scenario_validations} == {"priority_first", "score_first", "balanced"}
    assert validation.final_strategy in {"priority_first", "score_first", "balanced"}
    # If the final strategy still has unresolved violations, replanning must have been
    # exhausted (never silently ship an invalid plan without at least trying to fix it).
    if validation.unresolved_violations:
        assert result.get("replanning_attempts", 0) >= get_settings().max_replanning_attempts

    decision_review = result["decision_review"]
    assert decision_review.selected_strategy in {"priority_first", "score_first", "balanced"}
    assert decision_review.evaluations
    for evaluation in decision_review.evaluations:
        assert 0 <= evaluation.overall_score <= 100
        assert evaluation.rationale
        assert 0 <= evaluation.inventory_balance_score <= 1
        assert 0 <= evaluation.future_inventory_risk_ratio <= 1
        assert evaluation.total_transportation_distance_km >= 0
    # Only scenarios that actually passed constraint validation should ever be reviewed
    # (or, if none did, exactly the single best-effort fallback scenario).
    valid_strategies = {sv.strategy for sv in validation.scenario_validations if sv.is_valid}
    reviewed_strategies = {e.strategy for e in decision_review.evaluations}
    if valid_strategies:
        assert reviewed_strategies == valid_strategies
        assert decision_review.fell_back_to_invalid_scenario is False
    else:
        assert reviewed_strategies == {validation.final_strategy}
        assert decision_review.fell_back_to_invalid_scenario is True

    final = result["final_recommendation"]
    assert final.selected_strategy == decision_review.selected_strategy
    assert final.shipment_plan
    assert all(line.explanation for line in final.shipment_plan)
    assert final.expected_inventory_after_shipment
    assert 0 <= final.confidence_score <= 100
    assert final.business_explanation
    assert final.risk_assessment
    assert final.contingency_actions
    assert final.fell_back_to_invalid_scenario == decision_review.fell_back_to_invalid_scenario
    assert len(final.alternative_recommendations) == len(decision_review.evaluations) - 1


@requires_groq_key
@pytest.mark.asyncio
async def test_replanning_loop_fires_and_gives_up_after_max_attempts(committed_db):
    # Store capacity of 0 guarantees every scenario violates store_capacity, no matter
    # what Supply Planning proposes - proving the loop actually runs (not just routes
    # correctly in isolation) and terminates rather than looping forever.
    await _seed_minimal(
        committed_db,
        with_demand_history=True,
        store_available_qty=1,
        with_distance_matrix=True,
        store_capacity=0,
    )

    request = PlanningRequest(planning_date=datetime.date.today())
    result = await run_planning_workflow(request)

    max_attempts = get_settings().max_replanning_attempts
    assert result["replanning_attempts"] == max_attempts
    assert result["constraint_validation"].replanning_triggered is False
    assert result["constraint_validation"].unresolved_violations
    assert any(v.constraint == "store_capacity" for v in result["constraint_validation"].unresolved_violations)
    assert result["errors"]
    # plan_supply/allocate/optimize_cost/validate_constraints each run once per attempt
    # (the initial pass plus max_attempts retries) - counting trace lines proves the loop
    # actually executed that many times, not just that routing logic would allow it to.
    plan_supply_runs = sum(1 for line in result["trace"] if line.startswith("Planned supply"))
    assert plan_supply_runs == max_attempts + 1

    # Even with zero valid scenarios, Decision Review still runs (on the best-effort pick).
    decision_review = result["decision_review"]
    assert decision_review.fell_back_to_invalid_scenario is True
    assert decision_review.selected_strategy == result["constraint_validation"].final_strategy
    assert len(decision_review.evaluations) == 1

    # ...and Final Recommendation still produces a plan, with the fallback clearly flagged.
    final = result["final_recommendation"]
    assert final.selected_strategy == decision_review.selected_strategy
    assert final.fell_back_to_invalid_scenario is True
    assert final.unresolved_shortages_count == len(result["supply_planning"].unresolved_shortages)
    assert final.shipment_plan


@pytest.mark.asyncio
async def test_run_planning_workflow_persists_a_success_row(committed_db):
    # No-shortage scope, same as test_run_planning_workflow_end_to_end_no_shortage -
    # needs no API key, since the point here is verifying persistence, not any
    # particular LLM-calling agent's behavior.
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    request = PlanningRequest(planning_date=datetime.date.today())
    result = await run_planning_workflow(request)

    async with committed_db() as session:
        rows = await PlanningRunRepository(session).find_by_scope_key(request.scope_key())

    assert len(rows) == 1
    run = PlanningRunRead.model_validate(rows[0])
    assert run.status == PlanningRunStatus.SUCCESS
    assert run.error_message is None
    assert run.llm_provider == get_settings().llm_provider
    assert run.master_data_snapshot is not None
    assert run.final_recommendation is not None
    assert run.trace == result["trace"]

    # The reconstructed state dict matches what a live run returned - proves the
    # round-trip through JSON is lossless for the fields the Streamlit UI renders.
    reconstructed = run.to_state_dict()
    assert len(reconstructed["master_data"].stores) == len(result["master_data"].stores)
    assert reconstructed["final_recommendation"].selected_strategy == result["final_recommendation"].selected_strategy


@pytest.mark.asyncio
async def test_run_planning_workflow_persists_a_failed_row_and_still_raises(committed_db, monkeypatch):
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    async def _boom(state):
        raise RuntimeError("simulated node failure for persistence test")

    monkeypatch.setattr("app.agents.graph.load_master_data_node", _boom)

    request = PlanningRequest(planning_date=datetime.date.today())
    with pytest.raises(RuntimeError, match="simulated node failure"):
        await run_planning_workflow(request)

    async with committed_db() as session:
        rows = await PlanningRunRepository(session).find_by_scope_key(request.scope_key())

    assert len(rows) == 1
    run = rows[0]
    assert run.status == PlanningRunStatus.FAILED
    assert "simulated node failure" in run.error_message
    assert run.master_data_snapshot is None
    assert run.final_recommendation is None


@pytest.mark.asyncio
async def test_run_planning_workflow_returns_cached_result_on_second_call(committed_db):
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    request = PlanningRequest(planning_date=datetime.date.today())
    result1 = await run_planning_workflow(request)
    result2 = await run_planning_workflow(request)

    async with committed_db() as session:
        rows = await PlanningRunRepository(session).find_by_scope_key(request.scope_key())

    # Only the first call actually computed anything - the second was a cache hit,
    # so no second row was written, and the result is identical.
    assert len(rows) == 1
    assert result2["trace"] == result1["trace"]
    assert result2["final_recommendation"].selected_strategy == result1["final_recommendation"].selected_strategy


@pytest.mark.asyncio
async def test_run_planning_workflow_force_rerun_recomputes(committed_db):
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    request = PlanningRequest(planning_date=datetime.date.today())
    await run_planning_workflow(request)
    await run_planning_workflow(request, force_rerun=True)

    async with committed_db() as session:
        rows = await PlanningRunRepository(session).find_by_scope_key(request.scope_key())

    assert len(rows) == 2


@pytest.mark.asyncio
async def test_run_planning_workflow_cache_miss_when_data_changes(committed_db):
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    request = PlanningRequest(planning_date=datetime.date.today())
    await run_planning_workflow(request)

    # The underlying data genuinely changed since the cached run - a repeat call
    # (without force_rerun) must not reuse a now-stale result.
    async with committed_db() as session:
        result = await session.execute(
            select(Inventory).where(Inventory.location_type == LocationType.STORE)
        )
        store_inventory = result.scalars().first()
        store_inventory.available_qty = 999
        await session.commit()

    await run_planning_workflow(request)

    async with committed_db() as session:
        rows = await PlanningRunRepository(session).find_by_scope_key(request.scope_key())

    assert len(rows) == 2


@pytest.mark.asyncio
async def test_build_graph_with_fleet_module_enabled_has_new_nodes(monkeypatch):
    _with_fleet_module_enabled(monkeypatch)

    graph = build_graph()
    node_names = set(graph.get_graph().nodes.keys())

    assert {"assign_fleet", "plan_route", "predict_eta"} <= node_names


@pytest.mark.asyncio
async def test_build_graph_with_fleet_module_disabled_has_no_new_nodes():
    graph = build_graph()
    node_names = set(graph.get_graph().nodes.keys())

    assert not ({"assign_fleet", "plan_route", "predict_eta"} & node_names)


@requires_groq_key
@pytest.mark.asyncio
async def test_run_planning_workflow_with_fleet_module_enabled_writes_shipment_rows(committed_db, monkeypatch):
    _with_fleet_module_enabled(monkeypatch)
    await _seed_minimal(
        committed_db, with_demand_history=True, store_available_qty=1,
        with_distance_matrix=True, with_fleet=True,
    )

    request = PlanningRequest(planning_date=datetime.date.today())
    result = await run_planning_workflow(request)

    assert result["fleet_assignment"] is not None
    assert result["route_planning"] is not None
    assert result["eta_prediction"] is not None
    assert len(result["trace"]) == 12

    shipment_plan = result["final_recommendation"].shipment_plan
    assert shipment_plan
    # A seeded, available vehicle at the terminal means at least one line should
    # get a real, binding vehicle assignment (not just None throughout).
    assert any(line.vehicle_id is not None for line in shipment_plan)

    async with committed_db() as session:
        rows = (
            await session.execute(select(Shipment).where(Shipment.planning_run_id == result["planning_run_id"]))
        ).scalars().all()

    assert len(rows) == len(shipment_plan)
    assert {r.vehicle_id for r in rows} == {line.vehicle_id for line in shipment_plan}


@requires_groq_key
@pytest.mark.asyncio
async def test_cache_hit_does_not_duplicate_shipment_rows(committed_db, monkeypatch):
    _with_fleet_module_enabled(monkeypatch)
    await _seed_minimal(
        committed_db, with_demand_history=True, store_available_qty=1,
        with_distance_matrix=True, with_fleet=True,
    )

    request = PlanningRequest(planning_date=datetime.date.today())
    result1 = await run_planning_workflow(request)
    result2 = await run_planning_workflow(request)  # cache hit - no new computation

    assert result2["planning_run_id"] == result1["planning_run_id"]

    async with committed_db() as session:
        rows = (
            await session.execute(select(Shipment).where(Shipment.planning_run_id == result1["planning_run_id"]))
        ).scalars().all()

    assert len(rows) == len(result1["final_recommendation"].shipment_plan)


def test_scope_key_differs_by_optimization_objective():
    base = PlanningRequest(planning_date=datetime.date(2026, 1, 1), store_ids=[1], product_ids=[1])
    minimize_cost = base.model_copy(update={"optimization_objective": "minimize_cost"})
    maximize_service = base.model_copy(update={"optimization_objective": "maximize_service_level"})

    assert minimize_cost.scope_key() != maximize_service.scope_key()
