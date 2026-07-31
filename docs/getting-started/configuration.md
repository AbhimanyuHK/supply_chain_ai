# Configuration

All configuration lives in `app/core/config.py`'s `Settings` class
(`pydantic-settings`), loaded from environment variables or a `.env` file in
the project root. Field names map 1:1 to environment variable names
(case-insensitive) — e.g. `Settings.groq_api_key` ↔ `GROQ_API_KEY`.

Copy `.env.example` to `.env` and fill in what you need:

```bash
copy .env.example .env
```

`Settings` is cached process-wide via `@lru_cache` — **any `.env` change
requires restarting whichever process reads it** (the CLI script, the API
server, or the Streamlit dashboard). Re-clicking around in an already-running
Streamlit session will not pick up a changed `.env`.

## Application

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | One of `development`, `staging`, `production`, `test`. Tests force this to `test` via `tests/conftest.py`. |
| `APP_NAME` | `Supply Chain Planning Platform` | Cosmetic. |
| `API_V1_PREFIX` | `/api/v1` | FastAPI route prefix. |
| `LOG_LEVEL` | `INFO` | One of `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LOG_DIR` | `logs` | Rotating file sink location. |
| `LOG_JSON` | `false` | Structured JSON logging for production log aggregation. |
| `CORS_ALLOW_ORIGINS` | `["*"]` | JSON list. |

## Database

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./supply_chain.db` | See {doc}`../architecture/database-schema` for the SQLite ↔ Postgres switch. |
| `DATABASE_POOL_SIZE` | `20` | Postgres only — ignored for SQLite. |
| `DATABASE_MAX_OVERFLOW` | `10` | Postgres only. |
| `DATABASE_ECHO` | `false` | Log every SQL statement (verbose — debugging only). |

## Reasoning engine

Full detail in {doc}`../features/reasoning-engines`; summary here.

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `groq` | One of `groq`, `gemini`, `ollama`. |
| `GROQ_API_KEY` | *(empty)* | Required when `LLM_PROVIDER=groq`. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | |
| `GROQ_TEMPERATURE` | `0.0` | Lowered from an earlier `0.1` default for determinism — see {doc}`../features/idempotency-and-caching`. |
| `GROQ_MAX_RETRIES` | `3` | |
| `GEMINI_API_KEY` | *(empty)* | Required when `LLM_PROVIDER=gemini`. Get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). |
| `GEMINI_MODEL` | `gemini-2.5-flash` | |
| `GEMINI_TEMPERATURE` | `0.0` | |
| `OLLAMA_MODEL` | `mistral` | Must already be pulled locally (`ollama pull mistral`) and support tool-calling. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `OLLAMA_TEMPERATURE` | `0.0` | |

```{warning}
Gemini's free tier caps Flash models at **5 requests/minute** (confirmed via
Google AI Studio's own usage dashboard) — since each shortage in a planning
run costs 4 LLM calls, even a single shortage can approach this ceiling and
a scope with several shortages almost certainly will. This is an external
quota, not a bug in the platform. See {doc}`../features/reasoning-engines`.
```

## LLM call batching and concurrency

Introduced to keep the pipeline usable at scale — see
{doc}`../features/scalability`.

| Variable | Default | Notes |
|---|---|---|
| `SUPPLY_PLANNING_BATCH_SIZE` | `25` | Shortages grouped into one LLM prompt per batch, instead of one call per shortage. |
| `LLM_MAX_CONCURRENT_REQUESTS` | `3` | Bounds simultaneous in-flight LLM calls. Gemini free-tier users should lower this to `1`. |
| `SUPPLY_PLANNING_MAX_CANDIDATE_TERMINALS` | `5` | Candidate terminals (nearest by distance) considered per shortage — bounds prompt size at scale. |

## Forecasting

| Variable | Default | Notes |
|---|---|---|
| `CHRONOS_MODEL_NAME` | `amazon/chronos-t5-tiny` | Bump to `chronos-t5-small`/`base` for better accuracy once GPU infra is available. |
| `CHRONOS_DEVICE` | `cpu` | `cpu` or `cuda`. |
| `FORECAST_HORIZON_DAYS` | `14` | Days ahead the Demand Forecast Agent predicts. |
| `FORECAST_BATCH_SIZE` | `256` | Store/product series per Chronos inference call. |
| `CHRONOS_RANDOM_SEED` | `42` | Seeds torch's RNG before every Chronos `predict()` call so identical historical data always produces the identical forecast — see {doc}`../features/idempotency-and-caching`. |

## Planning behavior

| Variable | Default | Notes |
|---|---|---|
| `MAX_REPLANNING_ATTEMPTS` | `2` | How many times Constraint Validation sends violations back to Supply Planning before giving up. |
| `DECISION_REVIEW_CRITICAL_STOCK_THRESHOLD` | `0.1` | Fraction of pre-shipment stock below which a (terminal, product) counts as a future-inventory risk. |
| `PERSIST_FULL_MASTER_DATA_SNAPSHOT` | `true` | Set `false` at real scale to store only row counts, not the full input snapshot, per `PlanningRun`. See {doc}`../features/scalability`. |

## Phase 2 (Fleet Assignment / Route Planning / ETA Prediction)

| Variable | Default | Notes |
|---|---|---|
| `FLEET_MODULE_ENABLED` | `false` | Adds 3 nodes to the graph between Constraint Validation and Decision Review, and starts writing real `Shipment` rows with vehicle assignments on every successful run. Default `false` reproduces the original 9-node Phase 1 graph unchanged. |

## Per-run options that are *not* environment variables

Some behavior is a per-planning-run choice, not a global setting, and is
instead a field on `PlanningRequest` (passed by whichever caller triggers a
run — the CLI script, Streamlit, or a future API endpoint):

- `optimization_objective` (`"minimize_cost"` or `"maximize_service_level"`)
  — see {doc}`../features/cost-objectives`.
- `store_ids` / `product_ids` / `demand_history_window_days` / `planning_date`
  — the request's scope.

These are deliberately *not* environment variables: `get_business_rules()`
and `get_settings()` are both process-wide `@lru_cache`d, so anything that
should vary per concurrent run (once a REST API exists) cannot live there
without leaking across requests.
