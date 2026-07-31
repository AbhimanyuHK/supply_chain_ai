# REST API

`app/api/main.py::create_app()` — a FastAPI application factory. This is
the thinnest of the three interfaces (script, Streamlit, API) today: only
the health check is actually wired up. Everything else is a documented
gap, not a hidden one.

## What exists today

```{list-table}
:header-rows: 1

* - Endpoint
  - Method
  - Status
* - `/health`
  - GET
  - Implemented
```

`GET /health` (`app/api/routers/health.py`) checks database connectivity
via `check_database_connection()` and returns:

```json
{"status": "ok", "dependencies": {"database": "ok"}}
```

with HTTP 200, or `"status": "degraded"` / `"dependencies.database":
"unavailable"` with HTTP 503 if the database is unreachable.

```bash
venv\Scripts\python.exe -m uvicorn app.api.main:app --reload --port 8000
curl http://127.0.0.1:8000/health
```

## Cross-cutting API infrastructure (already built, ready for new routers)

- **CORS**: `Settings.cors_allow_origins` (default `["*"]`), configured
  once in `create_app()`.
- **Error handling**: `app/core/exceptions.py::register_exception_handlers`
  wires the `DomainError` hierarchy (`NotFoundError`, `ValidationError`,
  `ConstraintViolationError`, `ExternalServiceError`) to consistent
  `{error_code, message, details}` JSON error bodies — any future router
  raising one of these gets this behavior for free.
- **App metadata**: title/version come from `Settings.app_name` and a
  fixed `"0.1.0"`.

## Endpoints not yet built

The original spec calls for `/forecast`, `/inventory` (POST),
`/optimize`, `/fleet/assign`, `/route/optimize`, `/simulate`, and
`/shipments`. None exist yet — only routing scaffolding
(the comment in `create_app()` marking where future routers register).

The natural shape for the highest-value one, `/optimize`, given
everything already built:

1. Accept a `PlanningRequest` body.
2. Kick off `run_planning_workflow(request)` via FastAPI
   `BackgroundTasks`, returning `202 Accepted` with the eventual
   `PlanningRun.id` immediately — the workflow can take several seconds
   (LLM calls, Chronos inference), too long for a synchronous response at
   scale.
3. Client polls `GET /planning-runs/{id}` for status —
   `PlanningRunRepository.get_by_id` already exists and `PlanningRun`
   already tracks `status` (`success`/`failed`), so this needs no new
   persistence infrastructure, only the route itself. See
   {doc}`../features/scalability` (Fix 6) for the full reasoning behind
   this design, including why a real task queue isn't needed yet.

## Testing

`tests/test_health_api.py` covers the one implemented endpoint using
`httpx.AsyncClient` against the FastAPI app directly (no running server
needed). See {doc}`../operations/testing`.
