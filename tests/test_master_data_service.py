import datetime

import pytest

from app.models.entities import (
    DemandHistory,
    DistanceMatrix,
    Fleet,
    Inventory,
    LocationType,
    Product,
    Store,
    Terminal,
    VehicleStatus,
)
from app.schemas.planning import PlanningRequest
from app.services.master_data_service import MasterDataService


async def _seed_full(db_session) -> dict:
    stores = [
        Store(store_name="Store 1", latitude=1, longitude=1, capacity=100, priority=1),
        Store(store_name="Store 2", latitude=2, longitude=2, capacity=200, priority=2),
    ]
    terminal = Terminal(terminal_name="Terminal 1", latitude=3, longitude=3, capacity=1000)
    products = [
        Product(sku="SKU-1", name="P1", category="Cat", weight=1, volume=1, cost=10),
        Product(sku="SKU-2", name="P2", category="Cat", weight=1, volume=1, cost=20),
    ]
    db_session.add_all([*stores, terminal, *products])
    await db_session.flush()

    for store in stores:
        for product in products:
            db_session.add(
                Inventory(
                    location_type=LocationType.STORE,
                    location_id=store.store_id,
                    product_id=product.product_id,
                    available_qty=50,
                )
            )
    for product in products:
        db_session.add(
            Inventory(
                location_type=LocationType.TERMINAL,
                location_id=terminal.terminal_id,
                product_id=product.product_id,
                available_qty=500,
            )
        )

    today = datetime.date.today()
    for store in stores:
        for product in products:
            db_session.add(
                DemandHistory(
                    date=today - datetime.timedelta(days=1),
                    store_id=store.store_id,
                    product_id=product.product_id,
                    sales_qty=5,
                )
            )

    db_session.add(
        Fleet(
            terminal_id=terminal.terminal_id,
            vehicle_type="truck_5t",
            capacity_weight=5000,
            capacity_volume=20,
            cost_per_km=10,
            fixed_cost=100,
            status=VehicleStatus.AVAILABLE,
        )
    )

    for store in stores:
        db_session.add(
            DistanceMatrix(terminal_id=terminal.terminal_id, store_id=store.store_id, distance_km=10, travel_time=0.5)
        )

    await db_session.flush()
    return {"stores": stores, "terminal": terminal, "products": products}


@pytest.mark.asyncio
async def test_load_returns_everything_when_unscoped(db_session):
    await _seed_full(db_session)
    service = MasterDataService(db_session)

    snapshot = await service.load(PlanningRequest())

    assert len(snapshot.stores) == 2
    assert len(snapshot.terminals) == 1
    assert len(snapshot.products) == 2
    assert len(snapshot.inventory) == 6  # 2 stores x 2 products + 1 terminal x 2 products
    assert len(snapshot.demand_history) == 4  # 2 stores x 2 products x 1 day
    assert len(snapshot.fleet) == 1
    assert len(snapshot.distance_matrix) == 2
    assert snapshot.business_rules.default_safety_stock_days == 7
    assert snapshot.loaded_at is not None


@pytest.mark.asyncio
async def test_load_scopes_to_requested_stores_and_products(db_session):
    entities = await _seed_full(db_session)
    store_1 = entities["stores"][0]
    product_1 = entities["products"][0]
    service = MasterDataService(db_session)

    snapshot = await service.load(
        PlanningRequest(store_ids=[store_1.store_id], product_ids=[product_1.product_id])
    )

    assert len(snapshot.stores) == 1
    assert len(snapshot.products) == 1
    # 1 store x 1 product + 1 terminal x 1 product (terminals always in scope)
    assert len(snapshot.inventory) == 2
    assert len(snapshot.demand_history) == 1
    assert len(snapshot.distance_matrix) == 1


@pytest.mark.asyncio
async def test_load_excludes_demand_history_outside_window(db_session):
    entities = await _seed_full(db_session)
    store_1, product_1 = entities["stores"][0], entities["products"][0]
    db_session.add(
        DemandHistory(
            date=datetime.date.today() - datetime.timedelta(days=200),
            store_id=store_1.store_id,
            product_id=product_1.product_id,
            sales_qty=99,
        )
    )
    await db_session.flush()
    service = MasterDataService(db_session)

    snapshot = await service.load(PlanningRequest(demand_history_window_days=30))

    assert all(d.sales_qty != 99 for d in snapshot.demand_history)
