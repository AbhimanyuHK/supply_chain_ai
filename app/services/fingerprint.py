"""Content fingerprint for a `MasterDataSnapshot` - the basis for idempotent
planning runs (see `app/agents/graph.py::run_planning_workflow`).

Two snapshots that hold the same real data should fingerprint identically,
so that re-running the same scope against unchanged data returns the exact
prior result instead of triggering a fresh (expensive, LLM-calling)
computation - while a scope where the underlying data has genuinely changed
correctly gets a different fingerprint and a fresh computation.
"""

import hashlib
import json

from app.schemas.planning import MasterDataSnapshot


def compute_data_fingerprint(snapshot: MasterDataSnapshot) -> str:
    """SHA-256 of the snapshot's actual data, excluding `loaded_at` (the only
    non-deterministic field anywhere in the snapshot - none of the nested
    `*Read` schemas expose timestamps) and with every nested list sorted by
    its natural identity key first.

    Sorting matters: `json.dumps(..., sort_keys=True)` only sorts dict keys,
    never list order, and no repository applies `ORDER BY` anywhere - so two
    loads of the identical underlying rows aren't guaranteed to come back in
    the same order (this isn't hypothetical: `MasterDataService` derives
    terminal order from the distance matrix when a store scope is set, a
    different code path than the unscoped case - see master_data_service.py).
    Without normalizing order first, the cache would spuriously miss even
    when nothing about the data actually changed.
    """
    payload = {
        "stores": sorted(
            (s.model_dump(mode="json") for s in snapshot.stores), key=lambda s: s["store_id"]
        ),
        "terminals": sorted(
            (t.model_dump(mode="json") for t in snapshot.terminals), key=lambda t: t["terminal_id"]
        ),
        "products": sorted(
            (p.model_dump(mode="json") for p in snapshot.products), key=lambda p: p["product_id"]
        ),
        "inventory": sorted(
            (i.model_dump(mode="json") for i in snapshot.inventory),
            key=lambda i: (i["location_type"], i["location_id"], i["product_id"]),
        ),
        "demand_history": sorted(
            (d.model_dump(mode="json") for d in snapshot.demand_history),
            key=lambda d: (d["store_id"], d["product_id"], d["date"]),
        ),
        "fleet": sorted(
            (f.model_dump(mode="json") for f in snapshot.fleet), key=lambda f: f["vehicle_id"]
        ),
        "distance_matrix": sorted(
            (d.model_dump(mode="json") for d in snapshot.distance_matrix),
            key=lambda d: (d["terminal_id"], d["store_id"]),
        ),
        "business_rules": snapshot.business_rules.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
