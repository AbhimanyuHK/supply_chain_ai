# REST API

`app/api/main.py::create_app()` — a FastAPI application factory. `/health`
stays unprefixed (the standard convention: infra/load-balancer probes
expect a stable, unversioned path); the planning endpoints are mounted
under `Settings.api_v1_prefix` (`/api/v1` by default).

## What exists today

```{list-table}
:header-rows: 1

* - Endpoint
  - Method
  - Status
* - `/health`
  - GET
  - Implemented
* - `/api/v1/optimize`
  - POST
  - Implemented
* - `/api/v1/planning-runs`
  - GET
  - Implemented
* - `/api/v1/planning-runs/{run_id}`
  - GET
  - Implemented
```

### `GET /health`

`app/api/routers/health.py` checks database connectivity via
`check_database_connection()`:

```json
{"status": "ok", "dependencies": {"database": "ok"}}
```

HTTP 200, or `"status": "degraded"` / `"dependencies.database":
"unavailable"` with HTTP 503 if the database is unreachable.

### `POST /api/v1/optimize`

Runs the full nine-node planning workflow (`app/api/routers/planning.py`)
for the given scope, and returns the complete result — the same
`run_planning_workflow()` every other caller (the CLI script, Streamlit)
goes through.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/optimize \
  -H "Content-Type: application/json" \
  -d '{"store_ids": [1, 2], "optimization_objective": "minimize_cost"}'
```

Request body is a `PlanningRequest` (see {doc}`../getting-started/configuration`
for every field); `force_rerun` is a query parameter (`?force_rerun=true`)
to bypass the {doc}`idempotency cache <../features/idempotency-and-caching>`.
Response is an `OptimizeResponse` (`app/schemas/api.py`) — every pipeline
stage's real output, plus `planning_run_id` for looking the run up later:

```json
{
  "planning_run_id": 8,
  "trace": ["Loaded master data: ...", "..."],
  "errors": [],
  "replanning_attempts": 0,
  "master_data": { "...": "..." },
  "demand_forecast": { "...": "..." },
  "final_recommendation": { "...": "..." }
}
```

```{important}
**This endpoint is synchronous** — the HTTP request stays open for the
whole run (a few seconds to low tens of seconds at this platform's current
scale: `chronos-t5-tiny` inference plus up to 4 LLM calls). This is a
deliberate choice, not an oversight: no task-queue infrastructure exists
yet, and building the previously-considered `BackgroundTasks` + `202` +
polling pattern properly would require a new `PENDING` `PlanningRunStatus`
and restructuring the persistence hook to create-then-update a row instead
of always creating fresh — real surgery on the core, fully-tested
idempotency/persistence logic in `app/agents/graph.py`, for a benefit this
deployment doesn't need yet. See {doc}`../features/scalability` (Fix 6)
for the upgrade path this can move to if request volume or scope size ever
requires it.
```

### `GET /api/v1/planning-runs`

Lists recent planning runs across every scope, most recent first
(`?limit=50` by default) — wraps
`PlanningRunRepository.list_recent()`, returning lightweight
`PlanningRunSummary` rows (no stage payloads).

### `GET /api/v1/planning-runs/{run_id}`

The full audit record for one run — every stage's real output, exactly
what {doc}`../features/persistence-and-audit-trail` describes — or a `404`
with the standard error body if the id doesn't exist:

```json
{"error_code": "not_found", "message": "PlanningRun 999999 not found", "details": {"run_id": 999999}}
```

## Cross-cutting API infrastructure

- **CORS**: `Settings.cors_allow_origins` (default `["*"]`), configured
  once in `create_app()`.
- **Error handling**: `app/core/exceptions.py::register_exception_handlers`
  wires the `DomainError` hierarchy (`NotFoundError`, `ValidationError`,
  `ConstraintViolationError`, `ExternalServiceError`) to consistent
  `{error_code, message, details}` JSON error bodies — every route above
  gets this behavior for free, no per-endpoint error handling written.
- **App metadata**: title/version come from `Settings.app_name` and a
  fixed `"0.1.0"`.

## Endpoints still not built, and why

The original spec also calls for `/forecast`, `/inventory` (POST),
`/fleet/assign`, `/route/optimize`, `/simulate`, and `/shipments`. Each is
deliberately out of scope for now:

- **`/fleet/assign`, `/route/optimize`** — depend on the Phase 2 Fleet
  Assignment/Route Planning agents, which don't exist yet (gated behind
  `Settings.fleet_module_enabled`, currently `False`).
- **`/shipments`** — the `Shipment` table is deliberately unused today
  (see {doc}`../architecture/database-schema`); there's no approval
  workflow yet that would turn a `FinalRecommendation` into real shipment
  rows to expose.
- **`/forecast`** — would need a new code path calling
  `forecast_demand_node` directly, bypassing the full graph — a separate,
  not-yet-designed feature, not a small addition to what's built.
- **`/inventory` (POST)** — basic CRUD on the `Inventory` table; not
  built because the spec doesn't clearly scope it apart from every other
  entity's CRUD (why `/inventory` specifically and not stores/products/
  terminals too), and this platform's value is the planning workflow, not
  a general data-management API.

See {doc}`../reference/roadmap` for the full, up-to-date list.

## Testing

`tests/test_health_api.py` and `tests/test_planning_api.py` cover every
implemented endpoint using `httpx.AsyncClient` against the FastAPI app
directly (no running server needed) — the same pattern this section
described before any endpoint beyond `/health` existed. See
{doc}`../operations/testing`.
