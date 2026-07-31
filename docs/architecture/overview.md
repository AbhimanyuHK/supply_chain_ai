# Architecture Overview

## Design principles

Two principles run through every module in this codebase:

**"LLM judges, code decides."** Every agent that calls an LLM uses it only
for judgment on real, code-computed data — scoring, ranking, quantity
proposals, or narrative synthesis. It never computes arithmetic, distance,
cost, or the final selection. Those are always deterministic Python
(`argmax`/`argmin`/plain formulas) operating on real data already loaded
from the database. See {doc}`../agents/overview` for how this plays out
agent by agent, and why it matters for trust and testability.

**Clean architecture / dependency injection.** Repositories take an
`AsyncSession` via their constructor, not a global session — this makes
every layer trivially testable against any session, including a per-test
rollback transaction. Services orchestrate repositories; agents orchestrate
services; the graph orchestrates agents. Nothing reaches sideways past its
own layer.

## Directory layout

```text
app/
  core/          config.py (Settings), logging.py, exceptions.py,
                 business_rules.py, llm.py (reasoning-engine factory)
  database/      base.py (declarative Base), session.py (async engine/session)
    repositories/  one per entity - session injected via constructor (DI)
  models/        entities.py - every SQLAlchemy model
  schemas/       Pydantic Create/Read schemas, one module per entity/agent stage
  services/      master_data_service.py - orchestrates repositories into a snapshot
  agents/        state.py (LangGraph state) + one module per agent + graph.py
                 (StateGraph wiring + run_planning_workflow entry point)
  api/           main.py (app factory), routers/health.py
  forecast/      chronos_forecaster.py - HuggingFace Chronos wrapper
  optimizer/     still empty - nothing in Phase 1 needs it
config/          business_rules.yaml - editable business rules
alembic/         migrations
scripts/         seed_data.py, run_planning_workflow.py
tests/           conftest.py + one test module per component
streamlit_app.py Demo dashboard (own venv-ui/ - see the Streamlit page)
.github/
  workflows/     ci.yml
```

## Cross-cutting concerns

### Configuration

`app/core/config.py` exposes a single cached `Settings` (pydantic-settings)
object read from `.env`. See {doc}`../getting-started/configuration` for
every field.

### Logging

Loguru, configured for console output plus a rotating file sink under
`logs/`, with an optional structured-JSON mode for production log
aggregation (`LOG_JSON=true`).

### Error handling

`app/core/exceptions.py` defines a `DomainError` hierarchy (`NotFoundError`,
`ValidationError`, `ConstraintViolationError`, `ExternalServiceError`) with
FastAPI exception handlers returning a consistent
`{error_code, message, details}` JSON body. `ConstraintViolationError` is
deliberately reused by the Constraint Validation Agent's own domain logic,
not just the API layer.

### Why no Redis / caching layer

The original spec listed Redis for caching. It was removed entirely rather
than kept "just in case" — nothing in this codebase consumes it yet, and
speculative infrastructure with no consumer is a maintenance cost with no
payoff. If a future module genuinely needs a cache (e.g. forecast or
cost-optimization result memoization at very high request volume), add it
then, scoped to that actual need. This same reasoning is why
{doc}`../features/scalability`'s "no task queue" gap is documented rather
than pre-emptively solved with a broker nothing yet requires.

## Why SQLite locally, Postgres in production

Two supported `DATABASE_URL` targets, switched purely by the connection
string — nothing in `app/` differs per backend:

- **Local dev / tests (default)**: `sqlite+aiosqlite:///./supply_chain.db`
  — zero external services required. Foreign keys are enforced via a
  `PRAGMA foreign_keys=ON` connect-event listener (`app/database/session.py`),
  since SQLite has them off by default.
- **Staging / production**: `postgresql+asyncpg://...`, provisioned by
  `docker-compose.yml` (`postgres:16` + the `app` service). Pool sizing
  (`DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW`) only applies here.

Alembic's `env.py` builds an async engine from `Settings.database_url` (not
a fixed URL in `alembic.ini`), so `alembic upgrade head` works unmodified
against either backend. See {doc}`../operations/deployment` for the
production checklist.

## What Phase 1 covers vs. what's still open

**Built (Phase 1, all nine agents):** Master Data → Demand Forecast →
Inventory Analysis → Supply Planning → Allocation → Cost Optimization →
Constraint Validation (with a replanning feedback loop) → Decision Review →
Final Recommendation. See {doc}`planning-workflow` for the full graph and
{doc}`../agents/overview` for each agent's individual page.

**Not yet built (Phase 2 and known gaps):**

- Fleet Assignment, Route Planning, and ETA Prediction/Exception Handling
  agents — gated behind `Settings.fleet_module_enabled`, not started.
- The `/forecast`, `/inventory` (POST), `/optimize`, `/fleet/assign`,
  `/route/optimize`, `/simulate`, `/shipments` REST endpoints — only routing
  scaffolding exists; see {doc}`../interfaces/rest-api`.
- A forward-looking promotions/holiday calendar for demand forecasting (no
  data source exists in the model — see {doc}`../agents/demand-forecast-agent`).
- Two of the original spec's nine listed constraints (`safety_stock` as a
  separate check, `product_restrictions`) — no distinct real data to check
  them against; see {doc}`../agents/constraint-validation-agent`.
