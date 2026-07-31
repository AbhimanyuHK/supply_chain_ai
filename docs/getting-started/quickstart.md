# Quickstart

This walks through going from a fresh clone to a full end-to-end planning
run in five commands. It assumes you've completed
{doc}`installation` and {doc}`configuration`.

## 1. Run database migrations

Creates all core tables (`stores`, `terminals`, `products`, `inventory`,
`demand_history`, `fleet`, `shipments`, `distance_matrix`, `planning_runs`)
in `supply_chain.db`:

```bash
venv\Scripts\python.exe -m alembic upgrade head
```

Re-runnable any time; `alembic downgrade base` reverses it.

## 2. Seed sample data

Populates a realistic electronics-retail dataset — 6 stores, 3 distribution
terminals, 12 products (phones, laptops, TVs, etc.), inventory at every
location, 30 days of demand history, a small fleet per terminal, and a
terminal-to-store distance matrix:

```bash
venv\Scripts\python.exe scripts\seed_data.py
```

Safe to re-run — it wipes and re-inserts these tables' rows each time
(deterministic seeded random data, so the numbers are the same every run).

## 3. Run the planning workflow

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

This runs the complete nine-node LangGraph workflow: load master data →
forecast demand with Chronos → analyze inventory → plan supply for any
shortages → build and rank allocation scenarios → recompute real fleet-based
costs → validate against real constraints (looping back to replan if
nothing passes) → holistically score every valid scenario → synthesize a
final recommendation. It prints a snapshot summary, the forecast, shortages
found, candidate plans, allocation scenarios, the cost breakdown, each
scenario's validation status, the scored selection, and the full final
recommendation.

Optionally scope it to specific stores/products:

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py --store-ids 1 2 --product-ids 1 2 3
```

```{note}
The first run downloads the Chronos model (~30-40MB) from HuggingFace and
caches it locally (`~/.cache/huggingface`). If there are no shortages in
scope, zero LLM calls are made for that run — you don't need an API key to
verify the pipeline mechanically end to end.
```

```{tip}
Running the exact same scope again returns the identical prior result
instantly, with no new LLM calls — this is deliberate, not a caching bug.
See {doc}`../features/idempotency-and-caching`.
```

## 4. (Optional) Run the API

```bash
venv\Scripts\python.exe -m uvicorn app.api.main:app --reload --port 8000
```

```bash
curl http://127.0.0.1:8000/health
```

Expect `{"status": "ok", "dependencies": {"database": "ok"}}`. See
{doc}`../interfaces/rest-api` for what's actually wired up today versus
scaffolded.

## 5. (Optional) Run the Streamlit dashboard

Requires its own `venv-ui/` environment (see {doc}`installation`):

```bash
venv-ui\Scripts\streamlit.exe run streamlit_app.py
```

Open the URL it prints (default `http://localhost:8501`), pick a scope and
an optimization objective, and click **▶ Run planning workflow**. See
{doc}`../interfaces/streamlit-dashboard` for the full walkthrough.

## 6. Run the tests

```bash
venv\Scripts\python.exe -m pytest -v
```

100+ tests, covering config loading, ORM constraints, the repository layer,
every agent's deterministic logic, real end-to-end LangGraph runs, the
idempotency cache, and the scalability fixes. LLM-gated tests
auto-skip if no reasoning engine is configured — the full suite still runs
green with zero API keys set. See {doc}`../operations/testing`.

## What next

- Understand *why* the pipeline is built the way it is:
  {doc}`../architecture/overview` and {doc}`../architecture/planning-workflow`.
- Understand one specific agent in depth: {doc}`../agents/overview` links to
  all nine.
- Switch reasoning engines or understand the free-tier trade-offs:
  {doc}`../features/reasoning-engines`.
