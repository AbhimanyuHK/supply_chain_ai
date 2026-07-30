import datetime

import pytest

from app.agents.inventory_analysis_agent import analyze_inventory_node
from app.core.business_rules import BusinessRules
from app.models.entities import LocationType
from app.schemas.forecast import DemandForecastPoint, DemandForecastResult
from app.schemas.inventory import InventoryRead
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead

BUSINESS_RULES = BusinessRules(
    default_safety_stock_days=7,
    default_lead_time_days=2,
    reorder_point_multiplier=1.5,
)


def _snapshot(inventory_rows: list[InventoryRead]) -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[StoreRead(store_id=1, store_name="S", latitude=0, longitude=0, capacity=100, priority=1)],
        terminals=[TerminalRead(terminal_id=1, terminal_name="T", latitude=0, longitude=0, capacity=1000)],
        products=[ProductRead(product_id=1, sku="SKU-1", name="P", category="C", weight=1, volume=1, cost=1)],
        inventory=inventory_rows,
        demand_history=[],
        fleet=[],
        distance_matrix=[],
        business_rules=BUSINESS_RULES,
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _forecast(store_id: int, product_id: int, daily_qty: float, horizon: int = 14) -> DemandForecastResult:
    today = datetime.date.today()
    points = [
        DemandForecastPoint(
            store_id=store_id,
            product_id=product_id,
            date=today + datetime.timedelta(days=i + 1),
            predicted_qty=daily_qty,
            low_qty=daily_qty * 0.5,
            high_qty=daily_qty * 1.5,
        )
        for i in range(horizon)
    ]
    return DemandForecastResult(horizon_days=horizon, model_name="test-model", forecasts=points, skipped_pairs=[])


@pytest.mark.asyncio
async def test_store_below_reorder_point_is_flagged_with_correct_math():
    inventory = [
        InventoryRead(
            inventory_id=1,
            location_type=LocationType.STORE,
            location_id=1,
            product_id=1,
            available_qty=50,
            reserved_qty=5,
            incoming_qty=20,
            damaged_qty=1,
        )
    ]
    state = {
        "master_data": _snapshot(inventory),
        "demand_forecast": _forecast(store_id=1, product_id=1, daily_qty=10.0),
    }

    update = await analyze_inventory_node(state)
    result = update["inventory_analysis"]

    assert len(result.records) == 1
    record = result.records[0]

    # avg_daily_demand=10, safety_stock=10*7=70, lead_time_demand=10*2=20,
    # reorder_point=20*1.5+70=100, position=available(50)+incoming(20)=70 < 100
    assert record.avg_daily_demand == 10.0
    assert record.safety_stock == 70.0
    assert record.reorder_point == 100.0
    assert record.on_hand_qty == 50 + 5 + 1
    assert record.below_reorder_point is True
    assert record.shortage_qty == 30.0
    assert result.shortages == [record]


@pytest.mark.asyncio
async def test_store_above_reorder_point_has_no_shortage():
    inventory = [
        InventoryRead(
            inventory_id=1,
            location_type=LocationType.STORE,
            location_id=1,
            product_id=1,
            available_qty=200,
            reserved_qty=0,
            incoming_qty=0,
            damaged_qty=0,
        )
    ]
    state = {
        "master_data": _snapshot(inventory),
        "demand_forecast": _forecast(store_id=1, product_id=1, daily_qty=10.0),
    }

    update = await analyze_inventory_node(state)
    result = update["inventory_analysis"]

    assert result.records[0].below_reorder_point is False
    assert result.records[0].shortage_qty == 0.0
    assert result.shortages == []


@pytest.mark.asyncio
async def test_terminal_inventory_has_no_safety_stock_math():
    inventory = [
        InventoryRead(
            inventory_id=1,
            location_type=LocationType.TERMINAL,
            location_id=1,
            product_id=1,
            available_qty=5,
            reserved_qty=0,
            incoming_qty=0,
            damaged_qty=0,
        )
    ]
    state = {
        "master_data": _snapshot(inventory),
        # Even with a forecast present for this (location_id, product_id) pair,
        # terminals should never get safety-stock math applied.
        "demand_forecast": _forecast(store_id=1, product_id=1, daily_qty=999.0),
    }

    update = await analyze_inventory_node(state)
    record = update["inventory_analysis"].records[0]

    assert record.avg_daily_demand is None
    assert record.safety_stock is None
    assert record.reorder_point is None
    assert record.shortage_qty == 0.0
    assert record.below_reorder_point is False


@pytest.mark.asyncio
async def test_store_with_no_forecast_data_skips_safety_stock_math():
    inventory = [
        InventoryRead(
            inventory_id=1,
            location_type=LocationType.STORE,
            location_id=1,
            product_id=1,
            available_qty=5,
            reserved_qty=0,
            incoming_qty=0,
            damaged_qty=0,
        )
    ]
    empty_forecast = DemandForecastResult(horizon_days=14, model_name="test-model", forecasts=[], skipped_pairs=[])
    state = {"master_data": _snapshot(inventory), "demand_forecast": empty_forecast}

    update = await analyze_inventory_node(state)
    record = update["inventory_analysis"].records[0]

    assert record.avg_daily_demand is None
    assert record.shortage_qty == 0.0
