import datetime

from app.core.business_rules import BusinessRules
from app.models.entities import LocationType
from app.schemas.distance import DistanceMatrixRead
from app.schemas.inventory import InventoryRead
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead
from app.services.fingerprint import compute_data_fingerprint


def _snapshot(stores: list[StoreRead], loaded_at: datetime.datetime) -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=stores,
        terminals=[TerminalRead(terminal_id=1, terminal_name="T", latitude=0, longitude=0, capacity=1000)],
        products=[ProductRead(product_id=1, sku="S", name="P", category="C", weight=1, volume=1, cost=1)],
        inventory=[
            InventoryRead(
                inventory_id=1, location_type=LocationType.TERMINAL, location_id=1, product_id=1,
                available_qty=10, reserved_qty=0, incoming_qty=0, damaged_qty=0,
            )
        ],
        demand_history=[],
        fleet=[],
        distance_matrix=[DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=5.0, travel_time=1.0)],
        business_rules=BusinessRules(),
        loaded_at=loaded_at,
    )


def test_fingerprint_stable_across_list_reordering_and_loaded_at():
    store_a = StoreRead(store_id=1, store_name="A", latitude=0, longitude=0, capacity=10, priority=1)
    store_b = StoreRead(store_id=2, store_name="B", latitude=0, longitude=0, capacity=10, priority=1)

    snap1 = _snapshot([store_a, store_b], datetime.datetime(2026, 1, 1))
    snap2 = _snapshot([store_b, store_a], datetime.datetime(2026, 7, 30))

    assert compute_data_fingerprint(snap1) == compute_data_fingerprint(snap2)


def test_fingerprint_changes_when_real_data_changes():
    store_a = StoreRead(store_id=1, store_name="A", latitude=0, longitude=0, capacity=10, priority=1)
    store_b = StoreRead(store_id=2, store_name="B", latitude=0, longitude=0, capacity=10, priority=1)
    store_a_mutated = StoreRead(store_id=1, store_name="A", latitude=0, longitude=0, capacity=999, priority=1)

    snap1 = _snapshot([store_a, store_b], datetime.datetime(2026, 1, 1))
    snap2 = _snapshot([store_a_mutated, store_b], datetime.datetime(2026, 1, 1))

    assert compute_data_fingerprint(snap1) != compute_data_fingerprint(snap2)
