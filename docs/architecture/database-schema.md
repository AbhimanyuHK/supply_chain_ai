# Database Schema

Nine tables, defined in `app/models/entities.py` (SQLAlchemy 2.0 declarative
style) and created by Alembic migrations under `alembic/versions/`. Every
foreign key and every column used as a lookup/filter key by an agent
(`store_id`, `product_id`, `date`, `location`) is indexed — chosen for the
target scale of 1,000+ stores, 10,000+ terminals, and millions of inventory
rows.

## Master data tables

### `stores`

| Column | Type | Notes |
|---|---|---|
| `store_id` | PK | |
| `store_name` | string | |
| `latitude`, `longitude` | numeric(9,6) | |
| `capacity` | int | `CHECK capacity >= 0` |
| `priority` | int | Default `3`. Lower = higher priority. Indexed. |

### `terminals`

| Column | Type | Notes |
|---|---|---|
| `terminal_id` | PK | |
| `terminal_name` | string | |
| `latitude`, `longitude` | numeric(9,6) | |
| `capacity` | int | `CHECK capacity >= 0` |

### `products`

| Column | Type | Notes |
|---|---|---|
| `product_id` | PK | |
| `sku` | string | Unique. |
| `name`, `category` | string | `category` indexed. |
| `weight`, `volume` | numeric(10,3) | Used for fleet capacity checks. |
| `cost` | numeric(12,2) | Used for inventory holding cost. |
| `expiry_days` | int, nullable | Not currently consumed by any agent. |

### `inventory`

One row per (location, product) — a location is either a store or a
terminal, distinguished by `location_type`.

| Column | Type | Notes |
|---|---|---|
| `inventory_id` | PK | |
| `location_type` | enum | `store` or `terminal`. |
| `location_id` | int | Store or terminal id, depending on `location_type`. |
| `product_id` | FK → products | |
| `available_qty`, `reserved_qty`, `incoming_qty`, `damaged_qty` | int | All `CHECK >= 0`. |

Unique on `(location_type, location_id, product_id)`; indexed on
`(location_type, location_id)` and on `product_id` separately, since agents
query both directions (all inventory at a location, and all locations
holding a product).

### `demand_history`

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `date` | date | |
| `store_id` | FK → stores | |
| `product_id` | FK → products | |
| `sales_qty` | int | |
| `promotion`, `holiday` | bool | Captured but not currently consumed as forecast covariates — see {doc}`../agents/demand-forecast-agent`. |

Unique on `(date, store_id, product_id)`; indexed on `(store_id,
product_id)` and on `date` separately (the Demand Forecast Agent queries a
trailing window by date, scoped by store/product).

### `fleet`

| Column | Type | Notes |
|---|---|---|
| `vehicle_id` | PK | |
| `terminal_id` | FK → terminals | |
| `vehicle_type` | string | |
| `capacity_weight`, `capacity_volume` | numeric(10,3) | |
| `cost_per_km` | numeric(10,2) | |
| `fixed_cost` | numeric(12,2) | |
| `status` | enum | `available`, `in_transit`, `maintenance`, `out_of_service`. |

Indexed on `(terminal_id, status)` — the Cost Optimization Agent's vehicle
selection query is always "available vehicles at this terminal."

### `distance_matrix`

| Column | Type | Notes |
|---|---|---|
| `terminal_id` | FK → terminals, PK | |
| `store_id` | FK → stores, PK | |
| `distance_km`, `travel_time` | numeric(10,3) | Both `CHECK >= 0`. |

Composite primary key on `(terminal_id, store_id)` — no separate surrogate
id. Indexed additionally on `store_id` alone, since
{doc}`../features/scalability`'s Fix 1 queries "every terminal reachable
from these stores" as its primary access pattern.

### `shipments`

| Column | Type | Notes |
|---|---|---|
| `shipment_id` | PK | |
| `terminal_id`, `store_id`, `product_id` | FK | |
| `quantity` | int | `CHECK quantity > 0` |
| `shipment_date` | date | |
| `status` | enum | `planned`, `confirmed`, `in_transit`, `delivered`, `cancelled`, `exception`. |
| `vehicle_id` | FK → fleet, nullable | Populated by {doc}`../agents/fleet-assignment-agent` (Phase 2) — `NULL` when the fleet module is disabled, or if no vehicle could be assigned. |
| `planning_run_id` | FK → planning_runs, nullable, indexed | Which run produced this shipment. |

```{note}
This table is no longer unused: every successful `run_planning_workflow()`
call writes one `Shipment` row per `ShipmentPlanLine`, unconditionally —
a deliberate business decision (this table should reflect what the
platform actually recommended, not wait on some future "approve this
plan" step that doesn't exist). It models an individual *confirmed*
operational shipment with a real-world lifecycle, a different concept
from `planning_runs` below (which is an AI-decision audit log). See
{doc}`../features/persistence-and-audit-trail`.
```

## `planning_runs`

The audit trail for every AI-generated plan — see
{doc}`../features/persistence-and-audit-trail` for the full design
rationale. One row per `run_planning_workflow()` invocation.

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `planning_date` | date | |
| `store_ids`, `product_ids` | JSON, nullable | `None` means "all". |
| `demand_history_window_days` | int | |
| `scope_key` | string(64), indexed | SHA-256 of the canonical sorted scope + objective. |
| `data_fingerprint` | string(64), nullable | SHA-256 of the actual loaded master-data snapshot. See {doc}`../features/idempotency-and-caching`. |
| `optimization_objective` | string(32) | `"minimize_cost"` or `"maximize_service_level"`. |
| `llm_provider`, `llm_model` | string | Which reasoning engine produced this run. |
| `status` | enum | `success` or `failed`. |
| `error_message` | text, nullable | Populated only on failure. |
| `trace`, `errors` | JSON list of strings | |
| `replanning_attempts` | int | |
| `request_payload` | JSON, nullable | The full `PlanningRequest`, verbatim. |
| `master_data_row_counts` | JSON, nullable | Populated instead of the full snapshot when `Settings.persist_full_master_data_snapshot=False`. |
| `master_data_snapshot` | JSON, nullable | |
| `demand_forecast`, `inventory_analysis`, `supply_planning`, `allocation`, `cost_optimization`, `constraint_validation`, `fleet_assignment`, `route_planning`, `eta_prediction`, `decision_review`, `final_recommendation` | JSON, nullable | One column per pipeline stage — each stage's Pydantic result, `.model_dump(mode="json")`. The three Phase 2 columns are `NULL` whenever `Settings.fleet_module_enabled` was `False` for that run. |

```{important}
Every stage column is nullable because a **failed** run has no partial data
to store: the LangGraph compilation has no checkpointer configured, so when
a node raises, the exception propagates straight out with no partial state
returned. A failed row only ever gets scope/provider/error populated — this
is a deliberate, documented limitation, not an oversight. See
{doc}`../features/persistence-and-audit-trail`.
```

Indexed on `scope_key` alone (history browsing), `created_at` alone
(recency), and a composite `(scope_key, data_fingerprint, llm_provider,
llm_model)` — the hot lookup path hit on **every** `run_planning_workflow`
call for the idempotency cache check.

## Migrations

Four migrations to date, in order:

1. `0001_initial_schema` — the eight core tables.
2. `0002_planning_runs` — adds `planning_runs`.
3. `0003_planning_run_idempotency_and_objective` — adds `data_fingerprint`,
   `optimization_objective`, `master_data_row_counts`, and the composite
   cache-lookup index to `planning_runs`.
4. `0004_fleet_route_eta_and_shipment_links` — adds `shipments.vehicle_id`/
   `planning_run_id` (via Alembic batch mode — SQLite can't `ALTER` a
   foreign-key constraint onto an existing column directly) and
   `planning_runs.fleet_assignment`/`route_planning`/`eta_prediction`.

```bash
venv\Scripts\python.exe -m alembic upgrade head
venv\Scripts\python.exe -m alembic downgrade -1   # reverse one step
```

Alembic's `env.py` is async-aware and builds its engine from
`Settings.database_url` rather than a fixed URL in `alembic.ini`, so the
same migrations apply cleanly to both SQLite and Postgres.
