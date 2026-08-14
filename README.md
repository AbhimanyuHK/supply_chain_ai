# AI-Powered Supply Chain Planning Platform

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Enterprise supply chain planning system: demand forecasting, inventory analysis, supply
allocation, cost optimization, and constraint validation, orchestrated by a LangGraph
agent workflow reasoning through Groq, Gemini, or a local Ollama model (see step 3a) with
a Streamlit demo dashboard (step 8) and GitHub Actions CI (step 11) testing all three
engines. See the full documentation site under [`docs/`](docs/index.md) (build it locally
with `sphinx-build`, or host it on Read the Docs) for the module layout, every agent's
design decisions, and operational guidance.

> **Status: all 13 agents in the original spec are built** (Phase 1's 10 + Phase 2's Fleet
> Assignment/Route Planning/ETA Prediction), tagged `v1.2.0`. The LangGraph workflow runs
> Master Data → Demand Forecast (real HuggingFace Chronos) → Inventory Analysis → Supply
> Planning (Groq) → Allocation (Groq) → Cost Optimization (real fleet-based costing) →
> Constraint Validation (rejects invalid plans, loops back to Supply Planning for
> replanning) → **[optional] Fleet Assignment → Route Planning → ETA Prediction** →
> Decision Review (Groq) → Final Recommendation (Groq) end to end, producing a full
> shipment plan with business explanation, risk assessment, alternatives, confidence
> score, and expected inventory/service level. The bracketed Phase 2 stage is gated behind
> `FLEET_MODULE_ENABLED` (default `false`, reproducing the original 9-node graph
> byte-for-byte; `true` adds those 3 nodes and starts writing real `Shipment` rows with
> vehicle assignments — see step 3). Every Groq call can be swapped for a local Ollama
> model with one `.env` change (step 3a). See the "Current status" section at the bottom
> for exactly what's built vs. still open (a handful of REST endpoints, a couple of
> explicitly out-of-scope constraints) — and note the **no-authentication** gap called out
> there before using this for anything beyond an internal/trusted-network demo.

---

<img width="1536" height="1024" alt="ChatGPT Image Aug 14, 2026, 01_27_58 PM" src="https://github.com/user-attachments/assets/0c6600e1-4e18-4a43-a0e0-13c774d08675" />


---

## 1. Prerequisites

- Python 3.12 recommended (3.10+ works for this module; some later modules may need 3.12).
- No Docker required for local development — the app defaults to a local SQLite file.
- Docker + Docker Compose only if you want to run against Postgres (the production-shaped
  path) instead of SQLite.

## 2. Set up the virtual environment

```bash
cd D:\AI\suuply_chain_ai
python -m venv venv
```

Activate it, then install dependencies:

```bash
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes `ruff` (pinned), the lint tool CI enforces as a
hard-blocking job (step 11). Run it locally the same way CI does:

```bash
venv\Scripts\python.exe -m ruff check .
```

## 3. Configure environment variables

A `.env` is already present, pointed at local SQLite:

```
DATABASE_URL=sqlite+aiosqlite:///./supply_chain.db
GROQ_API_KEY=
FLEET_MODULE_ENABLED=false
```

See [`.env.example`](.env.example) for every available setting, including the
`postgresql+asyncpg://...` URL to use once you switch to Docker/Postgres (step 7).

`FLEET_MODULE_ENABLED=true` turns on Phase 2 (Fleet Assignment/Route Planning/ETA
Prediction) — adds 3 nodes to the graph between Constraint Validation and Decision
Review, and starts writing real `Shipment` rows with vehicle assignments on every
successful run. Default `false` reproduces the original 9-node Phase 1 graph unchanged.

**You need a real `GROQ_API_KEY` starting with Module 5** (Supply Planning Agent) — it's
the first node that calls an LLM. Modules 6, 9, and 10 (Allocation, Decision Review, Final
Recommendation) each make their own Groq call too — four Groq calls total per full run.
Module 8 (Constraint Validation) can loop back to Module 5, which re-calls Groq each time
it does (up to `max_replanning_attempts`, default 2). Get a free key at
[console.groq.com](https://console.groq.com) and set it in `.env`:

```
GROQ_API_KEY=gsk_...
```

Modules 1-4 (master data, Chronos forecasting, inventory analysis) need no API key at all.

**Free-tier rate limit note**: Groq's free tier has a daily token cap (100,000 TPD as of
this writing). Running the full test suite plus a few manual workflow runs in the same day
can exhaust it — you'll see `groq.RateLimitError` (429). This is an external quota, not a
bug; it clears after the daily window resets (the error message includes a retry-after
estimate).

### 3a. Switching reasoning engines: Groq vs. Gemini vs. local Ollama

Every LLM-calling agent (Supply Planning, Allocation, Decision Review, Final
Recommendation) goes through one factory, `app/core/llm.py`, so which reasoning engine
they use is a one-line `.env` change, not a code change. This exists specifically so a
Groq quota outage (see above) doesn't block you — switch to a free-tier cloud
alternative or a fully local model and keep working:

```
# .env
LLM_PROVIDER=groq   # default: cloud, needs GROQ_API_KEY
# LLM_PROVIDER=gemini   # free-tier cloud alternative, needs GEMINI_API_KEY
# LLM_PROVIDER=ollama   # fully local, no API key/quota - needs `ollama serve` running

GEMINI_API_KEY=gsk_...           # free key at https://aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TEMPERATURE=0.1

OLLAMA_MODEL=mistral            # must already be pulled (`ollama pull mistral`) and
                                 # support tool-calling (check with `ollama show <model>`)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TEMPERATURE=0.1
```

**Gemini** (Google AI Studio) is a free-tier cloud alternative: get a free key at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey), set `GEMINI_API_KEY`
and `LLM_PROVIDER=gemini`. Its free tier is rate-limited **per minute rather than per
day** — but that limit is tight: only **5 requests/minute** on Flash models (2.5 and
3.5), confirmed via Google AI Studio's own usage dashboard. Since every shortage costs 4
LLM calls (Supply Planning, Allocation, Decision Review, Final Recommendation), a single
shortage can bump into that ceiling, and a run with several shortages almost certainly
will (a `429 RESOURCE_EXHAUSTED` with a ~47s `retry_delay` is expected in that case, not
a bug). Gemini works well for quick single-shortage test runs; for anything heavier,
prefer Groq (higher throughput, just a daily rather than per-minute cap) or Ollama (no
limit at all, just much slower).

To use **Ollama** instead: install [Ollama](https://ollama.com), run `ollama serve` (or
let the desktop app run it), pull a tool-calling-capable model (`ollama pull mistral`),
then set `LLM_PROVIDER=ollama` in `.env`. Local inference is much slower than either
cloud option (minutes, not seconds, per LLM call) but has no quota at all.

Every trace/log line names the actual model that ran (e.g. `via ollama/mistral` vs
`via gemini/gemini-2.5-flash` vs `via llama-3.3-70b-versatile`), so output never
misattributes which engine produced it.

## 4. Run database migrations

Creates all 8 tables (`stores`, `terminals`, `products`, `inventory`, `demand_history`,
`fleet`, `shipments`, `distance_matrix`) in `supply_chain.db`:

```bash
venv\Scripts\python.exe -m alembic upgrade head
```

Re-runnable any time; `alembic downgrade base` reverses it.

## 5. Seed sample data

Populates the database with a realistic electronics-retail dataset — 6 stores, 3
distribution terminals, 12 electronic products (phones, laptops, TVs, etc.), inventory at
every location, 30 days of demand history, a small fleet per terminal, and a
terminal-to-store distance matrix:

```bash
venv\Scripts\python.exe scripts\seed_data.py
```

Safe to re-run — it wipes and re-inserts these 8 tables' rows each time (deterministic,
seeded random data, so the numbers are the same every run).

## 6. Run the planning workflow (full pipeline)

Runs the complete LangGraph workflow — load master data, forecast demand with Chronos,
analyze inventory (safety stock / reorder point / shortages), plan supply for any
shortages via Groq, build and rank allocation scenarios via a second Groq call, recompute
real fleet-based costs for each scenario (no Groq call), validate all three scenarios
against real constraints (looping back to Supply Planning, with the actual violation
reasons, if none pass), optionally assign fleet/plan routes/predict ETA risk (Phase 2,
if `FLEET_MODULE_ENABLED=true`), holistically score every *valid* scenario via a third
Groq call, then synthesize a final recommendation via a fourth Groq call — and prints a
snapshot summary, a forecast sample, shortages found, ranked candidate shipment plans,
ranked allocation scenarios, a real cost breakdown, each scenario's validation status,
the multi-dimension-scored selection, and the final recommendation (shipment plan with
per-line explanations, business explanation, risk assessment, contingency actions,
confidence score, expected inventory after shipment, and alternatives):

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Optionally scope it to specific stores/products:

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py --store-ids 1 2 --product-ids 1 2 3
```

The first run downloads the Chronos model (`amazon/chronos-t5-tiny`, ~30-40MB) from
HuggingFace and caches it locally (`~/.cache/huggingface`); subsequent runs reuse the
cache. If there are no shortages in the scope you ran, all four Groq-calling nodes make
zero calls (and Cost Optimization/Constraint Validation have nothing to cost/validate) —
`GROQ_API_KEY` isn't needed for that run. If Constraint Validation loops back to Supply
Planning, expect to see "Planned supply..." appear more than once in the trace, and
additional Groq calls each time.

Note: on Windows you may see a harmless `RuntimeError: Event loop is closed` printed
*after* all output, during interpreter shutdown — it's a known cosmetic artifact of async
HTTP clients on Windows' proactor event loop, not a bug in this code (exit code is still 0).

## 7. Run the API

```bash
venv\Scripts\python.exe -m uvicorn app.api.main:app --reload --port 8000
```

Check it's alive:

```bash
curl http://127.0.0.1:8000/health
```

Expect `{"status": "ok", "dependencies": {"database": "ok"}}`.

## 8. Run the Streamlit demo dashboard

A read-only dashboard for demoing the full pipeline to business stakeholders — shows the
input master data, every intermediate agent output (forecast, shortages, candidate plans,
allocation scenarios, cost breakdown, constraint validation status), and the final
recommendation, all in one place.

It has its own virtual environment (`venv-ui/`), separate from the API's `venv/`. This is
required, not just tidiness: `fastapi==0.115.6` (used by the API) pins `starlette<0.42`,
while Streamlit 1.60's dashboard code needs a starlette new enough to export
`DEFAULT_EXCLUDED_CONTENT_TYPES` from `starlette.middleware.gzip` — a symbol added well
after 0.42. The two constraints can't be satisfied in one environment, so
`requirements-ui.txt` installs its own dependency set (deliberately *not* `-r
requirements.txt`) into a dedicated venv:

```bash
python -m venv venv-ui
venv-ui\Scripts\python.exe -m pip install --upgrade pip
venv-ui\Scripts\python.exe -m pip install -r requirements-ui.txt
```

Then run it (uses whichever `LLM_PROVIDER` is set in `.env`, same as the CLI script):

```bash
venv-ui\Scripts\streamlit.exe run streamlit_app.py
```

Open the URL it prints (default `http://localhost:8501`), pick a scope (or leave it
empty for "all stores/products") and an **optimization objective** (minimize cost, or
maximize service level) in the sidebar, and click **Run planning workflow**. Three tabs
show the results: **Input Data** (master data snapshot), **Intermediate Data** (forecast
→ shortages → candidate plans → allocation scenarios → cost breakdown → constraint
validation, one section per pipeline stage), and **Final Plan** (decision review scores,
the selected recommendation, shipment plan, expected inventory, and alternatives). A
workflow failure (e.g. Groq quota exhausted) is caught and shown as an error banner
rather than crashing the app — switch `LLM_PROVIDER=ollama` in `.env` and rerun if that
happens.

### 8a. Run history and traceability

Every call to `run_planning_workflow` — from this dashboard, the CLI script, or a test —
is persisted as a `planning_runs` row: the full input scope (including which
optimization objective was used), which reasoning engine/model produced it, a
success/failure status (with the error message on failure), and every intermediate
stage's real output. This is unconditional and automatic, not something you opt into —
it exists so an AI-generated plan can always be traced back to exactly what produced it
(standard practice for auditable AI-decision systems, not unique to this project).

The dashboard surfaces this two ways:
- **Pick a scope that's already been run** (same stores/products/window/date/objective,
  any engine) and a "N previous run(s) for this exact scope" panel appears in the
  sidebar — select one to view its 3 tabs instantly, with **no LLM call made**.
- **🕘 Run history (all scopes)** in the sidebar browses the last 20 runs regardless of
  scope.

A caption at the top of the results area always says whether you're looking at a live
run or a specific historical one (with its timestamp and model). Selecting a *failed*
historical run shows its error message the same way a live failure would — there's no
stage data to render for a run that didn't complete.

### 8b. Idempotency: "Run" reuses results by default

Clicking **▶ Run planning workflow** doesn't always recompute — if the exact same scope
(stores/products/window/date/objective) has already succeeded against the *same
underlying data* with the *same reasoning engine*, it instantly returns that prior
result instead: no new LLM calls, no wasted quota, and the guarantee that re-running
"the same thing" never produces a different answer just because an LLM sampled
differently. This is checked by fingerprinting the actual loaded data (not just the
request), so if inventory has genuinely changed since the last run, a fresh computation
happens correctly rather than serving a stale plan.

Check **🔁 Force re-run (ignore cached result)** to bypass this and compute fresh
regardless — e.g. if you suspect a stale hit, or just want to compare timing/output
against a fresh call.

Note: `Settings` is cached per-process, so switching `LLM_PROVIDER` in `.env` requires
restarting the Streamlit process — an already-running dashboard won't pick up the change
just from re-clicking around.

## 9. (Optional) Switch to Postgres via Docker

If you have Docker installed:

```bash
docker compose up -d
```

This starts Postgres 16 and builds/runs the app container (which runs
`alembic upgrade head` automatically on startup, then seed manually the same way as
step 5 but pointed at the container's Postgres). To point your local `venv` at the
Postgres container instead of SQLite, change `DATABASE_URL` in `.env` to:

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/supply_chain
```

## 10. Run the tests

```bash
venv\Scripts\python.exe -m pytest -v
```

127 tests covering config loading, ORM model CRUD + constraint enforcement, the `/health`
endpoint, the REST API (`/optimize`, `/planning-runs`), the repository layer,
`MasterDataService` scoping, the Chronos forecaster wrapper, inventory analysis math
(safety stock/reorder point/shortage, store-vs-terminal scoping), Supply Planning
candidate generation, Allocation's three strategies (including a deliberately
scarce-stock scenario that forces them to genuinely diverge), Cost Optimization's vehicle
selection/costing math (including a deliberately-wrong allocation cost estimate to prove
it gets recomputed, not trusted), Constraint Validation's checks (one deliberate
violation per constraint) and its replanning decision tree, an end-to-end test that
forces every scenario to fail validation and confirms the graph loops back to Supply
Planning exactly `max_replanning_attempts + 1` times before giving up, Decision Review's
evaluation math and its "only review valid scenarios" rule, Final Recommendation's
shipment-plan/expected-inventory/alternatives construction (each its own testable
function, independent of the Groq synthesis call), Phase 2's Fleet Assignment/Route
Planning/ETA Prediction agents (bin-packing, route sequencing, risk-flagging, all
deterministic, zero LLM calls) with both the flag-off (9-node) and flag-on (12-node,
real `Shipment` row writes) graph shapes, and other end-to-end LangGraph runs — all
against a real (SQLite) database, the real Chronos model, and (where relevant) real Groq
calls, nothing is mocked.

**Tests that call an LLM are automatically skipped unless a reasoning engine is actually
configured** (`tests/conftest.py::requires_llm_configured` — true when `GROQ_API_KEY` or
`GEMINI_API_KEY` is set, or `LLM_PROVIDER=ollama` with a local server running), so the
full suite still runs with none of those — you'll just see a handful of `SKIPPED`
instead of `PASSED`. Set `LLM_PROVIDER=gemini`/`ollama` to have those same tests exercise
that engine instead of Groq — this is exactly how CI's Gemini/Ollama jobs (see below) get
real coverage without a Groq key. With a key set and quota available, all 127 run for real
against Groq, though running the full suite repeatedly in one day can trip Groq's
free-tier daily token cap (see the rate-limit note in step 3) — a `RateLimitError` there
is an external quota, not a test failure; the deterministic logic each LLM-calling agent
depends on is covered by separate non-LLM tests, so a quota outage only blocks the
handful of tests that need a live LLM response, not verification of the surrounding
logic. First test run pays the same one-time Chronos model download/load cost as step 6.

## 11. Continuous Integration

`.github/workflows/ci.yml` runs on every push/PR to `master` (and on manual dispatch), as
4 jobs — a hard-blocking lint job plus three independent test jobs so every supported
reasoning engine gets real coverage:

- **Lint** — installs `requirements-dev.txt` and runs `ruff check .`; fails the build on
  any finding (see step 2).
- **Tests (Groq)** — installs `requirements-dev.txt` and runs `pytest` with
  `GROQ_API_KEY` from a repository secret of the same name. If the secret isn't set, the
  Groq-gated tests just skip (see step 10) — the job doesn't fail.
- **Tests (Gemini)** — same, but with `GEMINI_API_KEY` from a repository secret and
  `LLM_PROVIDER=gemini`. Missing secret → skips the same way.
- **Tests (Ollama, local)** — installs Ollama on the runner itself, starts `ollama
  serve`, pulls `mistral`, sets `LLM_PROVIDER=ollama`, and runs the same `pytest` suite —
  no secret needed, since it's fully local, matching how you'd run it on your own machine
  during a Groq/Gemini outage.

To enable the Groq/Gemini jobs' real coverage, add repository secrets named
`GROQ_API_KEY` and/or `GEMINI_API_KEY` (Settings → Secrets and variables → Actions).
Nothing else needs configuring — the workflow has no other secrets or external
dependencies.

---

## Current status vs. the full spec

**All 13 agents in the original spec are built** — Phase 1's 10 plus Phase 2's Fleet
Assignment/Route Planning/ETA Prediction:

- **Module 1**: clean-architecture scaffold, config/logging/error handling, all 8 core
  tables + Alembic migration, FastAPI app + `/health`, sample electronics dataset seeder
- **Module 2**: repository layer (DI via constructor-injected session) for all 7 read
  entities, business rules config, `PlanningRequest`/`MasterDataSnapshot` schemas,
  `MasterDataService` (scoped master-data loading), the LangGraph `PlanningState` +
  Master Data Agent node
- **Module 3**: real HuggingFace Chronos zero-shot demand forecasting per store/product,
  batched/chunked for scale, wired as the graph's second node
- **Module 4**: safety stock / reorder point / shortage detection for store inventory
  (using Module 3's forecast as the demand signal), plus raw on-hand/available/
  reserved/incoming reporting for every location, wired as the graph's third node
- **Module 5**: Supply Planning Agent — first real Groq reasoning. For every shortage,
  finds candidate terminals from real inventory + distance-matrix data, asks Groq to
  propose and score alternative candidate plans (quantity/rationale/score only — cost,
  distance, and delivery time are always computed from real data, never from the LLM),
  wired as the graph's fourth node
- **Module 6**: Allocation Agent — second Groq call. Builds three deterministic allocation
  scenarios (`priority_first`, `score_first`, `balanced`) that treat shared terminal stock
  as a real constraint across *all* shortages at once (Module 5's candidates were generated
  independently per shortage, so two stores could otherwise double-book the same stock),
  then asks Groq to rank the finished scenarios with rationale, wired as the graph's fifth
  node
- **Module 7**: Cost Optimization Agent — no Groq call. Recomputes a real cost breakdown
  for each of Module 6's scenarios (actual fleet vehicle selection by weight/volume
  capacity, warehouse handling, inventory holding, delay penalties — replacing the earlier
  flat per-km proxy), then deterministically recommends the cheapest scenario that still
  fully covers every high-priority shortage, wired as the graph's sixth node
- **Module 8**: Constraint Validation Agent — no Groq call, but the workflow's **first
  feedback loop**. Validates all three scenarios against real constraints (available
  inventory, store/terminal capacity, lead time, min/max shipment quantity, high-priority
  coverage); if the recommended scenario fails, switches to a valid alternative if one
  exists, else sends the actual violation reasons back to Supply Planning for a real
  correction attempt (not a blind retry) — capped at `max_replanning_attempts` (default 2)
  — else proceeds best-effort with the violations flagged in `errors`. Wired as the
  graph's seventh node, with a conditional edge back to `plan_supply`.
- **Module 9**: Decision Review Agent — third Groq call. Adds the spec's remaining
  evaluation dimensions (inventory balance, transportation distance, future inventory
  risk) to Modules 6/7's fulfillment/cost/priority metrics, computed from real data; Groq
  scores each *valid* (constraint-passing) scenario 0-100 holistically, and the final
  selection is `argmax(score)` in code, not an LLM declaration. Falls back to reviewing
  Module 8's single best-effort scenario alone (and says so) if nothing validated. Wired
  as the graph's eighth node.
- **Module 10**: Final Recommendation Agent — fourth Groq call, the **last Phase 1 agent**.
  Assembles the final shipment plan (real per-line costs from Module 7, each line's
  explanation reused from Module 5's own rationale — not a fresh LLM call per line),
  expected inventory after shipment, expected service level, and alternative
  recommendations, all deterministically from data already computed. The one genuine
  synthesis task — a business explanation, risk assessment, contingency actions, and a
  calibrated confidence score (which drops noticeably if Module 8 had to fall back to a
  constraint-violating plan) — is Groq's job, given those real metrics. Wired as the
  graph's ninth node when Phase 2 is off, or precedes Decision Review as the tenth when
  it's on.
- **Phase 2 (optional, `FLEET_MODULE_ENABLED=true`)**: three more deterministic
  agents/nodes, no new LLM calls, inserted between Constraint Validation and Decision
  Review:
  - **Fleet Assignment** — bin-packs each scenario's shipment lines onto available
    vehicles per terminal (first-fit-decreasing by weight), flagging any line that can't
    fit any available vehicle as unassignable.
  - **Route Planning** — orders each vehicle's stops by terminal→store distance
    (nearest-first; no store-to-store distance data exists in this schema, so this is an
    explicit, documented proxy for true multi-stop routing) and computes a real route
    cost (fixed cost once per vehicle + cost-per-km × total distance).
  - **ETA Prediction** — predicts each stop's ETA from cumulative real travel time plus a
    variance buffer, flagging stops at risk of a lead-time breach, a vehicle capacity
    overflow, or a replanning-triggered run, with a deterministic suggested contingency
    per risk reason.
  - Decision Review and Final Recommendation both fold in this real data (risk counts,
    vehicle/route/ETA per shipment line); Final Recommendation's existing fourth Groq call
    gets one more real signal, not a new LLM call. On every successful run (flag on), a
    real `Shipment` row is written per shipment line with its vehicle assignment — this is
    unconditional, not gated on any future "approval" step.
- 127 passing tests (LLM-dependent ones auto-skip unless Groq or Ollama is configured;
  each LLM-calling agent's deterministic logic has its own separately-testable,
  non-LLM-dependent coverage)
- A manual run script (`scripts/run_planning_workflow.py`) exercising the full pipeline
  end to end, either shape

**Not yet built** (a few explicitly out-of-scope/deferred gaps):

- The `/forecast`, `/inventory` (POST), `/fleet/assign`, `/route/optimize`, `/simulate`
  endpoints (`/optimize` and the `/planning-runs` audit endpoints are built — see
  `docs/interfaces/rest-api.md`; `/shipments` is populated automatically by Phase 2, not
  exposed as its own read endpoint yet)
- A forward-looking promotions/holiday calendar (the Demand Forecast Agent has no such
  input to work from — see `docs/agents/demand-forecast-agent.md`)
- Two of the spec's nine listed constraints (safety stock as a separate check, product
  restrictions) are explicitly out of scope — no distinct/real data to check them against,
  see `docs/agents/constraint-validation-agent.md`
- **No authentication anywhere** — the REST API and the Streamlit dashboard are both
  unauthenticated, and CORS defaults to `["*"]`. Fine for an internal/trusted-network
  demo; treat this as a hard blocker before exposing either to an untrusted network. See
  `docs/operations/deployment.md`'s production checklist.

See `docs/reference/roadmap.md` for the full, up-to-date list of what's built and what's
next.

So today you can stand up the database, seed realistic data, and run the entire pipeline
end to end: a scoped master-data snapshot, a real per-store/per-product demand forecast,
a shortage report for store inventory, several real Groq-reasoned candidate shipment
plans per shortage, three ranked allocation scenarios across all shortages at once, a
real fleet-based cost breakdown, a constraint-validated set of scenarios (with automatic
replanning if nothing passed), optionally real vehicle assignment/route planning/ETA risk
flagging, a holistically-scored final selection, and a complete final recommendation —
shipment plan, business explanation, risk assessment, contingency actions, confidence
score, expected inventory, expected service level, and alternatives. It can also be
triggered over HTTP via `POST /api/v1/optimize` (see `docs/interfaces/rest-api.md`), not
just the CLI script.
