"""Seed the configured database with sample electronics-retail data.

Populates all 8 core tables with a small, internally-consistent dataset so the
API/tests/agents (once built) have something realistic to run against:
  - 6 stores (major Indian cities)
  - 3 distribution terminals
  - 12 electronic products
  - Inventory at every terminal and store, for every product
  - 30 days of demand history per store/product
  - A small fleet per terminal
  - A terminal-to-store distance matrix (haversine great-circle distance)

Re-running this script wipes and re-inserts all rows in these 8 tables (in
FK-safe order) so it is safe to run repeatedly during development.

Usage:
    venv/Scripts/python.exe scripts/seed_data.py
"""

import asyncio
import datetime
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.base import Base  # noqa: E402
from app.database.session import AsyncSessionLocal, engine  # noqa: E402
from app.models.entities import (  # noqa: E402
    DemandHistory,
    DistanceMatrix,
    Fleet,
    Inventory,
    LocationType,
    Product,
    Shipment,
    Store,
    Terminal,
    VehicleStatus,
)

RNG_SEED = 42

STORES = [
    dict(store_name="Bangalore Central", latitude=12.9716, longitude=77.5946, capacity=8000, priority=1),
    dict(store_name="Chennai T Nagar", latitude=13.0418, longitude=80.2341, capacity=6000, priority=2),
    dict(store_name="Mumbai Andheri", latitude=19.1197, longitude=72.8468, capacity=10000, priority=1),
    dict(store_name="Delhi Connaught Place", latitude=28.6315, longitude=77.2167, capacity=9000, priority=1),
    dict(store_name="Hyderabad Hitech City", latitude=17.4483, longitude=78.3915, capacity=7000, priority=2),
    dict(store_name="Pune Viman Nagar", latitude=18.5679, longitude=73.9143, capacity=5000, priority=3),
]

TERMINALS = [
    dict(terminal_name="South Zone Terminal - Bangalore", latitude=12.8452, longitude=77.6602, capacity=200_000),
    dict(terminal_name="West Zone Terminal - Mumbai", latitude=19.0760, longitude=72.8777, capacity=250_000),
    dict(terminal_name="North Zone Terminal - Delhi", latitude=28.7041, longitude=77.1025, capacity=220_000),
]

PRODUCTS = [
    dict(sku="SKU-ELEC-001", name="Smartphone X12", category="Smartphones", weight=0.20, volume=0.0010, cost=45000),
    dict(sku="SKU-ELEC-002", name="Laptop Pro 15", category="Laptops", weight=1.80, volume=0.0060, cost=75000),
    dict(sku="SKU-ELEC-003", name="LED TV 55-inch", category="Televisions", weight=15.00, volume=0.2500, cost=55000),
    dict(sku="SKU-ELEC-004", name="Tablet Air", category="Tablets", weight=0.50, volume=0.0020, cost=28000),
    dict(sku="SKU-ELEC-005", name="Smartwatch S3", category="Wearables", weight=0.05, volume=0.0002, cost=12000),
    dict(sku="SKU-ELEC-006", name="Bluetooth Speaker Mini", category="Audio", weight=0.60, volume=0.0030, cost=3500),
    dict(sku="SKU-ELEC-007", name="Wireless Earbuds Pro", category="Audio", weight=0.05, volume=0.0001, cost=6500),
    dict(sku="SKU-ELEC-008", name="Gaming Console X", category="Gaming", weight=3.50, volume=0.0200, cost=42000),
    dict(sku="SKU-ELEC-009", name="Digital Camera DSLR", category="Cameras", weight=0.80, volume=0.0040, cost=38000),
    dict(sku="SKU-ELEC-010", name="Home Theater System 5.1", category="Audio", weight=12.00, volume=0.1500, cost=25000),
    dict(sku="SKU-ELEC-011", name="Power Bank 20000mAh", category="Accessories", weight=0.40, volume=0.0010, cost=1800),
    dict(sku="SKU-ELEC-012", name="WiFi Router AX3000", category="Networking", weight=0.70, volume=0.0030, cost=5500),
]

VEHICLE_TYPES = [
    dict(vehicle_type="tempo_1t", capacity_weight=1000, capacity_volume=6, cost_per_km=8.0, fixed_cost=300),
    dict(vehicle_type="truck_5t", capacity_weight=5000, capacity_volume=20, cost_per_km=15.0, fixed_cost=800),
    dict(vehicle_type="truck_10t", capacity_weight=10000, capacity_volume=40, cost_per_km=22.0, fixed_cost=1500),
]

DEMAND_HISTORY_DAYS = 30


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _wipe_existing(session) -> None:
    from sqlalchemy import delete

    # Child tables first, to respect foreign keys.
    for model in (Shipment, DistanceMatrix, DemandHistory, Inventory, Fleet, Product, Terminal, Store):
        await session.execute(delete(model))
    await session.flush()


async def seed() -> None:
    random.seed(RNG_SEED)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await _wipe_existing(session)

        stores = [Store(**data) for data in STORES]
        terminals = [Terminal(**data) for data in TERMINALS]
        products = [Product(**data, expiry_days=None) for data in PRODUCTS]
        session.add_all(stores + terminals + products)
        await session.flush()

        # Inventory: healthy stock at every terminal, lighter stock at every store.
        for terminal in terminals:
            for product in products:
                session.add(
                    Inventory(
                        location_type=LocationType.TERMINAL,
                        location_id=terminal.terminal_id,
                        product_id=product.product_id,
                        available_qty=random.randint(500, 5000),
                        reserved_qty=random.randint(0, 200),
                        incoming_qty=random.randint(0, 800),
                        damaged_qty=random.randint(0, 15),
                    )
                )
        for store in stores:
            for product in products:
                session.add(
                    Inventory(
                        location_type=LocationType.STORE,
                        location_id=store.store_id,
                        product_id=product.product_id,
                        available_qty=random.randint(5, 200),
                        reserved_qty=random.randint(0, 20),
                        incoming_qty=random.randint(0, 50),
                        damaged_qty=random.randint(0, 3),
                    )
                )

        # 30 days of demand history per store/product.
        today = datetime.date.today()
        for store in stores:
            for product in products:
                for day_offset in range(DEMAND_HISTORY_DAYS, 0, -1):
                    demand_date = today - datetime.timedelta(days=day_offset)
                    is_weekend = demand_date.weekday() >= 5
                    is_holiday = random.random() < 0.03
                    is_promotion = random.random() < 0.08
                    base = random.randint(0, 12)
                    if is_weekend:
                        base = int(base * 1.4)
                    if is_promotion:
                        base = int(base * 2.0)
                    if is_holiday:
                        base = int(base * 1.6)
                    session.add(
                        DemandHistory(
                            date=demand_date,
                            store_id=store.store_id,
                            product_id=product.product_id,
                            sales_qty=base,
                            promotion=is_promotion,
                            holiday=is_holiday,
                        )
                    )

        # Fleet: one of each vehicle type per terminal.
        for terminal in terminals:
            for vehicle in VEHICLE_TYPES:
                session.add(
                    Fleet(terminal_id=terminal.terminal_id, status=VehicleStatus.AVAILABLE, **vehicle)
                )

        # Distance matrix: every terminal to every store.
        for terminal in terminals:
            for store in stores:
                distance_km = round(
                    _haversine_km(
                        float(terminal.latitude), float(terminal.longitude),
                        float(store.latitude), float(store.longitude),
                    ),
                    2,
                )
                travel_time_hours = round(distance_km / 40.0, 2)  # assume 40 km/h average
                session.add(
                    DistanceMatrix(
                        terminal_id=terminal.terminal_id,
                        store_id=store.store_id,
                        distance_km=distance_km,
                        travel_time=travel_time_hours,
                    )
                )

        await session.commit()

        print(f"Seeded {len(stores)} stores, {len(terminals)} terminals, {len(products)} products")
        print(f"Seeded inventory for {len(terminals) + len(stores)} locations x {len(products)} products")
        print(f"Seeded {len(stores) * len(products) * DEMAND_HISTORY_DAYS} demand history rows")
        print(f"Seeded {len(terminals) * len(VEHICLE_TYPES)} fleet vehicles")
        print(f"Seeded {len(terminals) * len(stores)} distance matrix entries")


if __name__ == "__main__":
    asyncio.run(seed())
