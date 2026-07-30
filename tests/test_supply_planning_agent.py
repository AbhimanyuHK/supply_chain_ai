import datetime

import pytest

from app.agents.supply_planning_agent import plan_supply_node
from app.core.business_rules import BusinessRules
from app.models.entities import LocationType
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
