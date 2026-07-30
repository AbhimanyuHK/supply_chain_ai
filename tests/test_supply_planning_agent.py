import asyncio
import datetime
import re

import pytest

import app.agents.supply_planning_agent as supply_planning_agent
from app.agents.supply_planning_agent import _LLMBatchPlanningResponse, _LLMCandidate, _LLMShortagePlan, plan_supply_node
from app.core.business_rules import BusinessRules
from app.models.entities import LocationType
from app.schemas.constraint_validation import ConstraintValidationResult, ConstraintViolation, ScenarioValidation
from app.schemas.distance import DistanceMatrixRead
from app.schemas.inventory import InventoryRead
from app.schemas.inventory_analysis import InventoryAnalysisRecord, InventoryAnalysisResult
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead
from tests.conftest import requires_llm_configured as requires_groq_key

BUSINESS_RULES = BusinessRules(estimated_transport_cost_per_km=50.0)


def _snapshot(inventory_rows, distance_rows, terminals) -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[StoreRead(store_id=1, store_name="S", latitude=0, longitude=0, capacity=100, priority=1)],
        terminals=terminals,
        products=[ProductRead(product_id=1, sku="SKU-1", name="P", category="C", weight=1, volume=1, cost=1)],
        inventory=inventory_rows,
        demand_history=[],
        fleet=[],
        distance_matrix=distance_rows,
        business_rules=BUSINESS_RULES,
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _shortage(store_id: int, product_id: int, shortage_qty: float) -> InventoryAnalysisResult:
    record = InventoryAnalysisRecord(
        location_type=LocationType.STORE,
        location_id=store_id,
        product_id=product_id,
        on_hand_qty=10,
        available_qty=10,
        reserved_qty=0,
        incoming_qty=0,
        damaged_qty=0,
        avg_daily_demand=5.0,
        safety_stock=35.0,
        reorder_point=50.0,
        shortage_qty=shortage_qty,
        below_reorder_point=True,
    )
    return InventoryAnalysisResult(records=[record], shortages=[record])


@pytest.mark.asyncio
async def test_shortage_with_no_candidate_terminal_is_unresolved():
    # Terminal exists but has zero stock of the product -> no viable candidate.
    terminals = [TerminalRead(terminal_id=1, terminal_name="T1", latitude=0, longitude=0, capacity=1000)]
    inventory = [
        InventoryRead(
            inventory_id=1, location_type=LocationType.TERMINAL, location_id=1, product_id=1,
            available_qty=0, reserved_qty=0, incoming_qty=0, damaged_qty=0,
        )
    ]
    state = {
        "master_data": _snapshot(inventory, distance_rows=[], terminals=terminals),
        "inventory_analysis": _shortage(store_id=1, product_id=1, shortage_qty=20),
    }

    update = await plan_supply_node(state)
    result = update["supply_planning"]

    assert result.candidate_plans == []
    assert len(result.unresolved_shortages) == 1
    assert result.unresolved_shortages[0].store_id == 1
    assert result.unresolved_shortages[0].product_id == 1


@requires_groq_key
@pytest.mark.asyncio
async def test_generates_candidate_plans_with_real_computed_cost_and_distance():
    terminals = [
        TerminalRead(terminal_id=1, terminal_name="Near", latitude=0, longitude=0, capacity=1000),
        TerminalRead(terminal_id=2, terminal_name="Far", latitude=0, longitude=0, capacity=1000),
    ]
    inventory = [
        InventoryRead(
            inventory_id=1, location_type=LocationType.TERMINAL, location_id=1, product_id=1,
            available_qty=100, reserved_qty=0, incoming_qty=0, damaged_qty=0,
        ),
        InventoryRead(
            inventory_id=2, location_type=LocationType.TERMINAL, location_id=2, product_id=1,
            available_qty=50, reserved_qty=0, incoming_qty=0, damaged_qty=0,
        ),
    ]
    distance_rows = [
        DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=10.0, travel_time=0.5),
        DistanceMatrixRead(terminal_id=2, store_id=1, distance_km=500.0, travel_time=12.0),
    ]
    state = {
        "master_data": _snapshot(inventory, distance_rows, terminals),
        "inventory_analysis": _shortage(store_id=1, product_id=1, shortage_qty=20),
    }

    update = await plan_supply_node(state)
    result = update["supply_planning"]

    assert result.unresolved_shortages == []
    assert 1 <= len(result.candidate_plans) <= 2

    plans_by_terminal = {p.terminal_id: p for p in result.candidate_plans}
    for terminal_id, plan in plans_by_terminal.items():
        assert plan.store_id == 1
        assert plan.product_id == 1
        # Cost/distance/delivery are computed by us, not the LLM - must match exactly.
        if terminal_id == 1:
            assert plan.estimated_transport_cost == 10.0 * 50.0
            assert plan.estimated_delivery_hours == 0.5
            assert 0 <= plan.quantity <= 100
        else:
            assert plan.estimated_transport_cost == 500.0 * 50.0
            assert plan.estimated_delivery_hours == 12.0
            assert 0 <= plan.quantity <= 50
        assert 0 <= plan.score <= 100
        assert plan.rationale


@requires_groq_key
@pytest.mark.asyncio
async def test_quantity_never_exceeds_terminal_availability():
    # Deliberately scarce stock (2 units) vs a large shortage (500) - even if the LLM
    # wanted to allocate the full shortage, the agent must clamp to what's on hand.
    terminals = [TerminalRead(terminal_id=1, terminal_name="T1", latitude=0, longitude=0, capacity=1000)]
    inventory = [
        InventoryRead(
            inventory_id=1, location_type=LocationType.TERMINAL, location_id=1, product_id=1,
            available_qty=2, reserved_qty=0, incoming_qty=0, damaged_qty=0,
        )
    ]
    distance_rows = [DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=5.0, travel_time=0.2)]
    state = {
        "master_data": _snapshot(inventory, distance_rows, terminals),
        "inventory_analysis": _shortage(store_id=1, product_id=1, shortage_qty=500),
    }

    update = await plan_supply_node(state)
    result = update["supply_planning"]

    assert len(result.candidate_plans) == 1
    assert 0 <= result.candidate_plans[0].quantity <= 2


class _FakeSettings:
    """Stand-in for `Settings` in tests that don't need a real LLM - just the
    handful of fields `plan_supply_node` reads to control batching."""

    def __init__(self, batch_size=2, max_candidate_terminals=5, max_concurrent=10):
        self.supply_planning_batch_size = batch_size
        self.supply_planning_max_candidate_terminals = max_candidate_terminals
        self.llm_max_concurrent_requests = max_concurrent


def _multi_product_snapshot(product_ids: list[int]) -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[StoreRead(store_id=1, store_name="S", latitude=0, longitude=0, capacity=1000, priority=1)],
        terminals=[TerminalRead(terminal_id=1, terminal_name="T1", latitude=0, longitude=0, capacity=1000)],
        products=[
            ProductRead(product_id=pid, sku=f"SKU-{pid}", name="P", category="C", weight=1, volume=1, cost=1)
            for pid in product_ids
        ],
        inventory=[
            InventoryRead(
                inventory_id=pid, location_type=LocationType.TERMINAL, location_id=1, product_id=pid,
                available_qty=100, reserved_qty=0, incoming_qty=0, damaged_qty=0,
            )
            for pid in product_ids
        ],
        demand_history=[],
        fleet=[],
        distance_matrix=[DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=10.0, travel_time=1.0)],
        business_rules=BUSINESS_RULES,
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _multi_shortages(product_ids: list[int]) -> InventoryAnalysisResult:
    records = [
        InventoryAnalysisRecord(
            location_type=LocationType.STORE, location_id=1, product_id=pid,
            on_hand_qty=10, available_qty=10, reserved_qty=0, incoming_qty=0, damaged_qty=0,
            avg_daily_demand=5.0, safety_stock=35.0, reorder_point=50.0, shortage_qty=20.0,
            below_reorder_point=True,
        )
        for pid in product_ids
    ]
    return InventoryAnalysisResult(records=records, shortages=records)


def _extract_pairs(prompt: str) -> list[tuple[int, int]]:
    return [(int(sid), int(pid)) for sid, pid in re.findall(r"store_id=(\d+), product_id=(\d+)", prompt)]


class _FakeStructuredLLM:
    def __init__(self, respond):
        self._respond = respond

    async def ainvoke(self, prompt: str) -> _LLMBatchPlanningResponse:
        return await self._respond(prompt)


@pytest.mark.asyncio
async def test_batches_multiple_shortages_and_matches_back_by_store_and_product(monkeypatch):
    product_ids = [1, 2, 3]
    monkeypatch.setattr(supply_planning_agent, "get_settings", lambda: _FakeSettings(batch_size=2))

    call_count = 0

    async def respond(prompt: str) -> _LLMBatchPlanningResponse:
        nonlocal call_count
        call_count += 1
        return _LLMBatchPlanningResponse(
            shortage_plans=[
                _LLMShortagePlan(
                    store_id=sid, product_id=pid,
                    candidates=[_LLMCandidate(terminal_id=1, quantity=15, rationale="ok", score=80.0)],
                )
                for sid, pid in _extract_pairs(prompt)
            ]
        )

    monkeypatch.setattr(supply_planning_agent, "_get_structured_llm", lambda: _FakeStructuredLLM(respond))

    state = {
        "master_data": _multi_product_snapshot(product_ids),
        "inventory_analysis": _multi_shortages(product_ids),
    }
    update = await plan_supply_node(state)
    result = update["supply_planning"]

    # 3 shortages at batch_size=2 -> 2 batches (2 + 1).
    assert call_count == 2
    assert result.unresolved_shortages == []
    assert {p.product_id for p in result.candidate_plans} == set(product_ids)
    assert all(p.quantity == 15 and p.terminal_id == 1 for p in result.candidate_plans)


@pytest.mark.asyncio
async def test_batch_response_omitting_a_shortage_produces_no_candidates_for_it(monkeypatch):
    product_ids = [1, 2]
    monkeypatch.setattr(supply_planning_agent, "get_settings", lambda: _FakeSettings(batch_size=10))

    async def respond(prompt: str) -> _LLMBatchPlanningResponse:
        # Deliberately answer only the first shortage in the batch, omitting the second.
        first_sid, first_pid = _extract_pairs(prompt)[0]
        return _LLMBatchPlanningResponse(
            shortage_plans=[
                _LLMShortagePlan(
                    store_id=first_sid, product_id=first_pid,
                    candidates=[_LLMCandidate(terminal_id=1, quantity=10, rationale="ok", score=50.0)],
                )
            ]
        )

    monkeypatch.setattr(supply_planning_agent, "_get_structured_llm", lambda: _FakeStructuredLLM(respond))

    state = {
        "master_data": _multi_product_snapshot(product_ids),
        "inventory_analysis": _multi_shortages(product_ids),
    }
    update = await plan_supply_node(state)
    result = update["supply_planning"]

    # The omitted shortage gets zero candidate plans, but it's NOT reclassified as
    # unresolved - a real candidate terminal existed in the data, the LLM just didn't
    # address it in this batch. Distinct from unresolved_shortages (no data at all).
    assert result.unresolved_shortages == []
    assert len(result.candidate_plans) == 1
    assert result.candidate_plans[0].product_id == product_ids[0]


@pytest.mark.asyncio
async def test_retry_violation_message_lands_in_correct_shortage_block(monkeypatch):
    product_ids = [1, 2]
    monkeypatch.setattr(supply_planning_agent, "get_settings", lambda: _FakeSettings(batch_size=10))

    captured_prompt = ""

    async def respond(prompt: str) -> _LLMBatchPlanningResponse:
        nonlocal captured_prompt
        captured_prompt = prompt
        return _LLMBatchPlanningResponse(
            shortage_plans=[
                _LLMShortagePlan(
                    store_id=sid, product_id=pid,
                    candidates=[_LLMCandidate(terminal_id=1, quantity=5, rationale="ok", score=50.0)],
                )
                for sid, pid in _extract_pairs(prompt)
            ]
        )

    monkeypatch.setattr(supply_planning_agent, "_get_structured_llm", lambda: _FakeStructuredLLM(respond))

    state = {
        "master_data": _multi_product_snapshot(product_ids),
        "inventory_analysis": _multi_shortages(product_ids),
        "constraint_validation": ConstraintValidationResult(
            scenario_validations=[ScenarioValidation(strategy="priority_first", violations=[], is_valid=False)],
            final_strategy="priority_first",
            unresolved_violations=[
                ConstraintViolation(
                    constraint="max_shipment_qty", store_id=1, product_id=2,
                    message="THIS_SHORTAGE_QTY_TOO_HIGH",
                )
            ],
            replanning_triggered=True,
        ),
    }
    await plan_supply_node(state)

    # The retry note only belongs to product_id=2's block, not product_id=1's.
    product_1_block, product_2_block = captured_prompt.split("product_id=2")
    assert "THIS_SHORTAGE_QTY_TOO_HIGH" not in product_1_block
    assert "THIS_SHORTAGE_QTY_TOO_HIGH" in product_2_block


@pytest.mark.asyncio
async def test_concurrency_never_exceeds_configured_limit(monkeypatch):
    product_ids = [1, 2, 3, 4]
    monkeypatch.setattr(
        supply_planning_agent, "get_settings", lambda: _FakeSettings(batch_size=1, max_concurrent=2)
    )

    in_flight = 0
    max_observed = 0

    async def respond(prompt: str) -> _LLMBatchPlanningResponse:
        nonlocal in_flight, max_observed
        in_flight += 1
        max_observed = max(max_observed, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        sid, pid = _extract_pairs(prompt)[0]
        return _LLMBatchPlanningResponse(
            shortage_plans=[
                _LLMShortagePlan(
                    store_id=sid, product_id=pid,
                    candidates=[_LLMCandidate(terminal_id=1, quantity=5, rationale="ok", score=50.0)],
                )
            ]
        )

    monkeypatch.setattr(supply_planning_agent, "_get_structured_llm", lambda: _FakeStructuredLLM(respond))

    state = {
        "master_data": _multi_product_snapshot(product_ids),
        "inventory_analysis": _multi_shortages(product_ids),
    }
    await plan_supply_node(state)

    assert max_observed <= 2
