import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.entities import (
    DemandHistory,
    DistanceMatrix,
    Fleet,
    Inventory,
    LocationType,
    Product,
    Shipment,
    ShipmentStatus,
    Store,
    Terminal,
    VehicleStatus,
)


async def _make_store(db_session, **overrides) -> Store:
    store = Store(
        store_name=overrides.get("store_name", "Downtown Store"),
        latitude=overrides.get("latitude", 12.9716),
        longitude=overrides.get("longitude", 77.5946),
        capacity=overrides.get("capacity", 5000),
        priority=overrides.get("priority", 1),
    )
    db_session.add(store)
    await db_session.flush()
    return store


async def _make_terminal(db_session, **overrides) -> Terminal:
    terminal = Terminal(
        terminal_name=overrides.get("terminal_name", "Central Terminal"),
        latitude=overrides.get("latitude", 13.0827),
        longitude=overrides.get("longitude", 80.2707),
        capacity=overrides.get("capacity", 100000),
    )
    db_session.add(terminal)
    await db_session.flush()
    return terminal


async def _make_product(db_session, **overrides) -> Product:
    product = Product(
        sku=overrides.get("sku", "SKU-0001"),
        name=overrides.get("name", "Rice 5kg"),
        category=overrides.get("category", "Grocery"),
        weight=overrides.get("weight", 5.0),
        volume=overrides.get("volume", 0.01),
        cost=overrides.get("cost", 250.0),
        expiry_days=overrides.get("expiry_days", 365),
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest.mark.asyncio
async def test_store_round_trip(db_session):
    store = await _make_store(db_session)
    result = await db_session.execute(select(Store).where(Store.store_id == store.store_id))
    fetched = result.scalar_one()
    assert fetched.store_name == "Downtown Store"
    assert fetched.priority == 1


@pytest.mark.asyncio
async def test_product_unique_sku_constraint(db_session):
    await _make_product(db_session, sku="SKU-DUP")
    await db_session.flush()

    db_session.add(
        Product(sku="SKU-DUP", name="Other", category="Grocery", weight=1, volume=1, cost=1)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_store_negative_capacity_violates_check_constraint(db_session):
    db_session.add(
        Store(store_name="Bad Store", latitude=0, longitude=0, capacity=-1, priority=1)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_inventory_requires_existing_product_fk(db_session):
    db_session.add(
        Inventory(
            location_type=LocationType.STORE,
            location_id=999999,
            product_id=999999,
            available_qty=10,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_inventory_round_trip_and_unique_constraint(db_session):
    store = await _make_store(db_session)
    product = await _make_product(db_session, sku="SKU-INV")

    inv = Inventory(
        location_type=LocationType.STORE,
        location_id=store.store_id,
        product_id=product.product_id,
        available_qty=100,
        reserved_qty=10,
        incoming_qty=20,
        damaged_qty=0,
    )
    db_session.add(inv)
    await db_session.flush()

    db_session.add(
        Inventory(
            location_type=LocationType.STORE,
            location_id=store.store_id,
            product_id=product.product_id,
            available_qty=5,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_demand_history_round_trip(db_session):
    store = await _make_store(db_session)
    product = await _make_product(db_session, sku="SKU-DEMAND")

    demand = DemandHistory(
        date=datetime.date(2026, 7, 1),
        store_id=store.store_id,
        product_id=product.product_id,
        sales_qty=42,
        promotion=True,
        holiday=False,
    )
    db_session.add(demand)
    await db_session.flush()

    result = await db_session.execute(
        select(DemandHistory).where(DemandHistory.store_id == store.store_id)
    )
    fetched = result.scalar_one()
    assert fetched.sales_qty == 42
    assert fetched.promotion is True


@pytest.mark.asyncio
async def test_fleet_round_trip(db_session):
    terminal = await _make_terminal(db_session)

    vehicle = Fleet(
        terminal_id=terminal.terminal_id,
        vehicle_type="truck_10t",
        capacity_weight=10000,
        capacity_volume=40,
        cost_per_km=12.5,
        fixed_cost=500,
        status=VehicleStatus.AVAILABLE,
    )
    db_session.add(vehicle)
    await db_session.flush()

    result = await db_session.execute(select(Fleet).where(Fleet.terminal_id == terminal.terminal_id))
    fetched = result.scalar_one()
    assert fetched.status == VehicleStatus.AVAILABLE


@pytest.mark.asyncio
async def test_shipment_quantity_must_be_positive(db_session):
    terminal = await _make_terminal(db_session)
    store = await _make_store(db_session)
    product = await _make_product(db_session, sku="SKU-SHIP")

    db_session.add(
        Shipment(
            terminal_id=terminal.terminal_id,
            store_id=store.store_id,
            product_id=product.product_id,
            quantity=0,
            shipment_date=datetime.date(2026, 7, 15),
            status=ShipmentStatus.PLANNED,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_shipment_round_trip(db_session):
    terminal = await _make_terminal(db_session)
    store = await _make_store(db_session)
    product = await _make_product(db_session, sku="SKU-SHIP-OK")

    shipment = Shipment(
        terminal_id=terminal.terminal_id,
        store_id=store.store_id,
        product_id=product.product_id,
        quantity=450,
        shipment_date=datetime.date(2026, 7, 15),
        status=ShipmentStatus.PLANNED,
    )
    db_session.add(shipment)
    await db_session.flush()

    result = await db_session.execute(
        select(Shipment).where(Shipment.shipment_id == shipment.shipment_id)
    )
    fetched = result.scalar_one()
    assert fetched.quantity == 450
    assert fetched.status == ShipmentStatus.PLANNED


@pytest.mark.asyncio
async def test_distance_matrix_round_trip(db_session):
    terminal = await _make_terminal(db_session)
    store = await _make_store(db_session)

    db_session.add(
        DistanceMatrix(
            terminal_id=terminal.terminal_id,
            store_id=store.store_id,
            distance_km=42.5,
            travel_time=1.25,
        )
    )
    await db_session.flush()

    result = await db_session.execute(
        select(DistanceMatrix).where(DistanceMatrix.terminal_id == terminal.terminal_id)
    )
    fetched = result.scalar_one()
    assert float(fetched.distance_km) == 42.5
