import datetime

import pytest

from app.agents.allocation_agent import (
    _balanced_lines,
    _priority_first_lines,
    _score_first_lines,
    _ShortageInfo,
    allocate_node,
)
from app.core.business_rules import BusinessRules
from app.models.entities import LocationType
from app.schemas.allocation import AllocationResult
from app.schemas.inventory import InventoryRead
from app.schemas.inventory_analysis import InventoryAnalysisRecord, InventoryAnalysisResult
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.supply_planning import CandidatePlan, SupplyPlanningResult
from app.schemas.terminal import TerminalRead
from tests.conftest import requires_llm_configured as requires_groq_key


def _plan(store_id: int, product_id: int, terminal_id: int, quantity: int, score: float) -> CandidatePlan:
    return CandidatePlan(
        terminal_id=terminal_id,
        store_id=store_id,
        product_id=product_id,
        quantity=quantity,
        estimated_transport_cost=100.0,
        estimated_delivery_hours=1.0,
        rationale="test",
        score=score,
    )


# Two stores contest the SAME (terminal, product) resource, which only has enough stock
# (60) to fully satisfy one of them (each wants 60). Store A is high priority (1) but
# scored lower by Module 5 (80); Store B is low priority (5) but scored higher (90).
STORE_A = _ShortageInfo(store_id=1, product_id=1, shortage_qty=60, priority=1)
STORE_B = _ShortageInfo(store_id=2, product_id=1, shortage_qty=60, priority=5)
SHORTAGES = [STORE_A, STORE_B]
CANDIDATES_BY_SHORTAGE = {
    STORE_A.key: [_plan(store_id=1, product_id=1, terminal_id=1, quantity=60, score=80)],
    STORE_B.key: [_plan(store_id=2, product_id=1, terminal_id=1, quantity=60, score=90)],
}
TERMINAL_STOCK = {(1, 1): 60}


def _qty_for_store(lines, store_id: int) -> int:
    return sum(line.quantity for line in lines if line.store_id == store_id)


def test_priority_first_favors_higher_priority_store_when_scarce():
    lines = _priority_first_lines(SHORTAGES, CANDIDATES_BY_SHORTAGE, TERMINAL_STOCK)

    assert _qty_for_store(lines, 1) == 60  # high priority (1) served fully first
    assert _qty_for_store(lines, 2) == 0  # nothing left for low priority (5)
    assert sum(line.quantity for line in lines) <= 60  # never exceeds shared stock


def test_score_first_favors_higher_scored_candidate_regardless_of_priority():
    lines = _score_first_lines(SHORTAGES, CANDIDATES_BY_SHORTAGE, TERMINAL_STOCK)

    assert _qty_for_store(lines, 2) == 60  # higher Module-5 score (90) wins, despite low priority
    assert _qty_for_store(lines, 1) == 0
    assert sum(line.quantity for line in lines) <= 60


def test_balanced_splits_scarce_resource_proportionally():
    lines = _balanced_lines(SHORTAGES, CANDIDATES_BY_SHORTAGE, TERMINAL_STOCK)

    # Both asked for 60 out of 120 total requested against 60 available -> 50% each.
    assert _qty_for_store(lines, 1) == 30
    assert _qty_for_store(lines, 2) == 30
    assert sum(line.quantity for line in lines) <= 60


def test_strategies_never_exceed_available_stock_when_abundant():
    abundant_stock = {(1, 1): 1000}
    for strategy_fn in (_priority_first_lines, _score_first_lines, _balanced_lines):
        lines = strategy_fn(SHORTAGES, CANDIDATES_BY_SHORTAGE, abundant_stock)
        assert _qty_for_store(lines, 1) == 60
        assert _qty_for_store(lines, 2) == 60


@pytest.mark.asyncio
async def test_allocate_node_skips_llm_call_when_no_shortages():
    state = {
        "master_data": None,  # never touched - the node returns before reading it
        "inventory_analysis": InventoryAnalysisResult(records=[], shortages=[]),
        "supply_planning": SupplyPlanningResult(candidate_plans=[], unresolved_shortages=[]),
    }

    update = await allocate_node(state)
    result: AllocationResult = update["allocation"]

    assert result.scenarios == []
    assert result.recommended_strategy is None
    assert "No shortages" in update["trace"][0]


@requires_groq_key
@pytest.mark.asyncio
async def test_allocate_node_ranks_scenarios_with_real_groq():
    snapshot = MasterDataSnapshot(
        stores=[
            StoreRead(store_id=1, store_name="A", latitude=0, longitude=0, capacity=100, priority=1),
            StoreRead(store_id=2, store_name="B", latitude=0, longitude=0, capacity=100, priority=5),
        ],
        terminals=[TerminalRead(terminal_id=1, terminal_name="T", latitude=0, longitude=0, capacity=1000)],
        products=[ProductRead(product_id=1, sku="SKU-1", name="P", category="C", weight=1, volume=1, cost=1)],
        inventory=[
            InventoryRead(
                inventory_id=1, location_type=LocationType.TERMINAL, location_id=1, product_id=1,
                available_qty=60, reserved_qty=0, incoming_qty=0, damaged_qty=0,
            )
        ],
        demand_history=[],
        fleet=[],
        distance_matrix=[],
        business_rules=BusinessRules(),
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )
    inventory_analysis = InventoryAnalysisResult(
        records=[],
        shortages=[
            InventoryAnalysisRecord(
                location_type=LocationType.STORE, location_id=1, product_id=1, on_hand_qty=0,
                available_qty=0, reserved_qty=0, incoming_qty=0, damaged_qty=0, shortage_qty=60,
                below_reorder_point=True,
            ),
            InventoryAnalysisRecord(
                location_type=LocationType.STORE, location_id=2, product_id=1, on_hand_qty=0,
                available_qty=0, reserved_qty=0, incoming_qty=0, damaged_qty=0, shortage_qty=60,
                below_reorder_point=True,
            ),
        ],
    )
    supply_planning = SupplyPlanningResult(
        candidate_plans=[
            _plan(store_id=1, product_id=1, terminal_id=1, quantity=60, score=80),
            _plan(store_id=2, product_id=1, terminal_id=1, quantity=60, score=90),
        ],
        unresolved_shortages=[],
    )

    state = {
        "master_data": snapshot,
        "inventory_analysis": inventory_analysis,
        "supply_planning": supply_planning,
    }

    update = await allocate_node(state)
    result: AllocationResult = update["allocation"]

    assert len(result.scenarios) == 3
    assert {s.strategy for s in result.scenarios} == {"priority_first", "score_first", "balanced"}
    ranks = sorted(s.rank for s in result.scenarios)
    assert ranks == [1, 2, 3]
    assert all(s.rationale for s in result.scenarios)
    assert result.recommended_strategy == result.scenarios[0].strategy
