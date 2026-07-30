import datetime

import pytest

from app.database.repositories import (
    DemandHistoryRepository,
    DistanceMatrixRepository,
    FleetRepository,
    InventoryRepository,
    ProductRepository,
    StoreRepository,
    TerminalRepository,
)
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


async def _seed_basic(db_session) -> dict:
    store_a = Store(store_name="Store A", latitude=1, longitude=1, capacity=100, priority=1)
    store_b = Store(store_name="Store B", latitude=2, longitude=2, capacity=200, priority=2)
    terminal = Terminal(terminal_name="Terminal A", latitude=3, longitude=3, capacity=1000)
    product_a = Product(sku="SKU-A", name="Product A", category="Cat", weight=1, volume=1, cost=10)
    product_b = Product(sku="SKU-B", name="Product B", category="Cat", weight=1, volume=1, cost=20)
    db_session.add_all([store_a, store_b, terminal, product_a, product_b])
    await db_session.flush()
    return {"store_a": store_a, "store_b": store_b, "terminal": terminal, "product_a": product_a, "product_b": product_b}


@pytest.mark.asyncio
async def test_store_repository_list_all_and_by_ids(db_session):
    entities = await _seed_basic(db_session)
    repo = StoreRepository(db_session)

    all_stores = await repo.list_all()
    assert len(all_stores) == 2

    filtered = await repo.list_by_ids([entities["store_a"].store_id])
    assert [s.store_id for s in filtered] == [entities["store_a"].store_id]

    assert await repo.list_by_ids([]) == []


@pytest.mark.asyncio
async def test_terminal_repository(db_session):
    entities = await _seed_basic(db_session)
    repo = TerminalRepository(db_session)

    assert len(await repo.list_all()) == 1
    assert (await repo.list_by_ids([entities["terminal"].terminal_id]))[0].terminal_name == "Terminal A"


@pytest.mark.asyncio
async def test_product_repository(db_session):
    entities = await _seed_basic(db_session)
    repo = ProductRepository(db_session)

    assert len(await repo.list_all()) == 2
    result = await repo.list_by_ids([entities["product_b"].product_id])
    assert result[0].sku == "SKU-B"


@pytest.mark.asyncio
async def test_inventory_repository_filters_by_location_type_and_product(db_session):
    entities = await _seed_basic(db_session)
    store_a, terminal, product_a, product_b = (
        entities["store_a"],
        entities["terminal"],
        entities["product_a"],
        entities["product_b"],
    )

    db_session.add_all(
        [
            Inventory(
                location_type=LocationType.STORE,
                location_id=store_a.store_id,
                product_id=product_a.product_id,
                available_qty=10,
            ),
            Inventory(
                location_type=LocationType.TERMINAL,
                location_id=terminal.terminal_id,
                product_id=product_a.product_id,
                available_qty=500,
            ),
            # Different product - should not be returned when we only ask for product_a.
            Inventory(
                location_type=LocationType.STORE,
                location_id=store_a.store_id,
                product_id=product_b.product_id,
                available_qty=99,
            ),
        ]
    )
    await db_session.flush()

    repo = InventoryRepository(db_session)
    rows = await repo.list_for_locations_and_products(
        terminal_ids=[terminal.terminal_id],
        store_ids=[store_a.store_id],
        product_ids=[product_a.product_id],
    )

    assert len(rows) == 2
    assert {r.location_type for r in rows} == {LocationType.STORE, LocationType.TERMINAL}
    assert all(r.product_id == product_a.product_id for r in rows)

    assert await repo.list_for_locations_and_products(terminal_ids=[], store_ids=[], product_ids=[]) == []


@pytest.mark.asyncio
async def test_demand_history_repository_filters_by_since_date(db_session):
    entities = await _seed_basic(db_session)
    store_a, product_a = entities["store_a"], entities["product_a"]
    today = datetime.date.today()

    db_session.add_all(
        [
            DemandHistory(date=today - datetime.timedelta(days=5), store_id=store_a.store_id, product_id=product_a.product_id, sales_qty=3),
            DemandHistory(date=today - datetime.timedelta(days=100), store_id=store_a.store_id, product_id=product_a.product_id, sales_qty=7),
        ]
    )
    await db_session.flush()

    repo = DemandHistoryRepository(db_session)
    recent = await repo.list_recent(
        store_ids=[store_a.store_id], product_ids=[product_a.product_id], since_date=today - datetime.timedelta(days=30)
    )

    assert len(recent) == 1
    assert recent[0].sales_qty == 3


@pytest.mark.asyncio
async def test_fleet_repository(db_session):
    entities = await _seed_basic(db_session)
    terminal = entities["terminal"]
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
    await db_session.flush()

    repo = FleetRepository(db_session)
    result = await repo.list_by_terminal_ids([terminal.terminal_id])
    assert len(result) == 1
    assert result[0].vehicle_type == "truck_5t"


@pytest.mark.asyncio
async def test_distance_matrix_repository(db_session):
    entities = await _seed_basic(db_session)
    terminal, store_a = entities["terminal"], entities["store_a"]
    db_session.add(
        DistanceMatrix(terminal_id=terminal.terminal_id, store_id=store_a.store_id, distance_km=10, travel_time=0.5)
    )
    await db_session.flush()

    repo = DistanceMatrixRepository(db_session)
    result = await repo.list_by_terminal_and_store_ids([terminal.terminal_id], [store_a.store_id])
    assert len(result) == 1
    assert float(result[0].distance_km) == 10
