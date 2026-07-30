# Architecture — Modules 1-10 (Phase 1 complete)

## Layout

```
app/
  core/          config.py (Settings), logging.py (loguru setup), exceptions.py,
                 business_rules.py (loads config/business_rules.yaml)
  database/      base.py (declarative Base), session.py (async engine/session/get_db)
    repositories/  one per entity (store, terminal, product, inventory, demand_history,
                   fleet, distance_matrix) — session injected via constructor (DI)
  models/        entities.py — SQLAlchemy models: Store, Terminal, Product, Inventory,
                 DemandHistory, Fleet, Shipment, DistanceMatrix
  schemas/       Pydantic Create/Read schemas, one module per entity, plus planning.py
                 (PlanningRequest, MasterDataSnapshot), forecast.py (DemandForecastPoint,
                 DemandForecastResult, StoreProductRef), inventory_analysis.py
                 (InventoryAnalysisRecord, InventoryAnalysisResult), supply_planning.py
                 (CandidatePlan, SupplyPlanningResult), allocation.py (AllocationLine,
                 AllocationScenario, AllocationResult), cost_optimization.py (CostedLine,
                 ScenarioCostSummary, CostOptimizationResult), constraint_validation.py
                 (ConstraintViolation, ScenarioValidation, ConstraintValidationResult),
                 decision_review.py (ScenarioEvaluation, DecisionReviewResult), and
                 final_recommendation.py (ShipmentPlanLine, InventoryProjection,
                 AlternativeRecommendation, FinalRecommendation)
  services/      master_data_service.py — orchestrates repositories into a snapshot
  agents/        state.py (LangGraph state), master_data_agent.py, demand_forecast_agent.py,
                 inventory_analysis_agent.py, supply_planning_agent.py, allocation_agent.py,
                 cost_optimization_agent.py, constraint_validation_agent.py,
                 decision_review_agent.py, final_recommendation_agent.py, graph.py
                 (StateGraph wiring + run_planning_workflow entry point)
  api/           main.py (app factory), routers/health.py
  optimizer/     still empty — nothing left in the spec's Phase 1 agent list needs it;
                 Phase 2's Route Planning Agent is the next likely occupant
  forecast/      chronos_forecaster.py — HuggingFace Chronos pipeline wrapper
config/          business_rules.yaml — editable business rules (no DB table for these)
alembic/         env.py (async-aware), versions/0001_initial_schema.py
scripts/         seed_data.py, run_planning_workflow.py
tests/           conftest.py + test_config, test_models, test_health_api, test_repositories,
                 test_master_data_service, test_agents_graph, test_chronos_forecaster,
                 test_inventory_analysis_agent, test_supply_planning_agent,
                 test_allocation_agent, test_cost_optimization_agent,
                 test_constraint_validation_agent, test_decision_review_agent,
                 test_final_recommendation_agent
```

## Database

Two supported `DATABASE_URL` targets, switched purely by the connection string:

- **Local dev / tests (default)**: `sqlite+aiosqlite:///./supply_chain.db` — zero external
  services required. Foreign keys are enforced via a `PRAGMA foreign_keys=ON` connect-event
  listener (`app/database/session.py`), since SQLite has them off by default.
- **Docker / staging / production**: `postgresql+asyncpg://...`, provisioned by
  `docker-compose.yml` (`postgres:16` + the `app` service). Pool sizing
  (`DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW`) only applies on this path.

Alembic's `env.py` builds an async engine from `Settings.database_url` (not a fixed URL in
`alembic.ini`), so `alembic upgrade head` works unmodified against either backend.

## Why SQLite locally

This dev environment has no Docker/Postgres available. Rather than block Module 1 on
external infrastructure, the default `DATABASE_URL` points at SQLite so the schema, ORM
models, and constraints can be built and verified immediately. The Postgres path is fully
wired (`docker-compose.yml`, `asyncpg` driver, pool settings) and is what should be used
once Docker is available — switching is a one-line `.env` change, nothing in `app/` differs
per backend.

## Configuration

`app/core/config.py` exposes a single cached `Settings` (pydantic-settings) object read from
`.env`. Notable fields: `groq_api_key`/`groq_model` (first used in Module 5's Supply
Planning Agent), `fleet_module_enabled` (gates the Phase 2 fleet/route agents later in the
LangGraph graph).

## Error handling

`app/core/exceptions.py` defines a `DomainError` hierarchy (`NotFoundError`,
`ValidationError`, `ConstraintViolationError`, `ExternalServiceError`) with FastAPI handlers
returning a consistent `{error_code, message, details}` JSON body. `ConstraintViolationError`
is intentionally reusable by the future Constraint Validation Agent.

## Caching (not yet added)

The original spec lists Redis for caching. It was removed from Module 1 — nothing here
consumes it yet, so keeping it wired up (config fields, a client, a docker-compose service,
a health check dependency) was premature. Re-add it in whichever later module first needs
to cache something (e.g. Demand Forecast or Cost Optimization Agent results).

## Module 2: Master Data Agent

The first LangGraph node (`START -> load_master_data -> ...`). Pure data loading, no LLM
reasoning.

- **Repository layer** (`app/database/repositories/`): one class per entity, each taking
  an `AsyncSession` via its constructor (dependency injection, not a global session), so
  they're testable against any session including a per-test rollback transaction.
- **`MasterDataService`** (`app/services/master_data_service.py`): orchestrates the
  repositories into a single `MasterDataSnapshot`, scoped to a `PlanningRequest`
  (specific store/product IDs, or all if unset; a trailing demand-history window rather
  than full history). This scoping matters at the spec's target scale — a planning run
  should not need to load millions of inventory rows or years of demand history at once.
  All terminals are always in scope, since any of them could supply the requested stores.
- **Business rules**: the spec lists "Business Rules" as master data to load but defines
  no database table for it. `config/business_rules.yaml` + `app/core/business_rules.py`
  hold it instead — editable without a code change or migration.
- **`app/agents/state.py`**: the `PlanningState` TypedDict threaded through the graph.
  `trace`/`errors` use the `operator.add` reducer so each future node appends to them
  rather than overwriting the previous node's contribution.

## Module 3: Demand Forecast Agent

The second node (`load_master_data -> forecast_demand -> ...`). Still no Groq
call — this agent is pure ML inference via HuggingFace Chronos, a zero-shot time series
foundation model (`app/forecast/chronos_forecaster.py`, model cached process-wide via
`lru_cache` since loading it costs ~10s).

- For every (store, product) pair in the master data snapshot, its historical `sales_qty`
  series (sorted by date) is fed to Chronos, which returns 10th/50th/90th percentile
  forecasts for `forecast_horizon_days` (default 14) ahead. Pairs with zero history are
  recorded in `skipped_pairs` rather than guessed at.
- Series are batched through Chronos in chunks of `forecast_batch_size` (default 256) to
  bound memory at scale, rather than one call per series or one giant call for everything.
- **Scope limitation, stated plainly**: the spec lists Promotions/Holiday/Weather as
  forecast inputs. Chronos has no covariate mechanism for "this future date is a
  promotion" — it forecasts purely from the historical series shape (which already
  reflects past promo/holiday spikes and weekly seasonality). There is no forward-looking
  promotion/holiday calendar table in the data model, so this agent does not fabricate one;
  weather is out of scope entirely (no data source anywhere). See the docstring in
  `app/agents/demand_forecast_agent.py` for where to layer a future promotions calendar in,
  if one gets added.
- Model choice: `amazon/chronos-t5-tiny` by default (fast, CPU-friendly, ~30-40MB
  download). `chronos_model_name` in `Settings` can be bumped to `chronos-t5-small/base`
  for better accuracy once GPU/production infra is available — no code change needed.
- **Manual run**: `scripts/run_planning_workflow.py` runs the graph end-to-end and prints
  both the master data snapshot and a forecast sample — see the README.

## Module 4: Inventory Analysis Agent

The third node (`forecast_demand -> analyze_inventory -> END` for now). Still no Groq call.

- For every (location, product) row in the master data snapshot, reports the raw picture:
  `on_hand_qty` (available + reserved + damaged), `available_qty`, `reserved_qty`,
  `incoming_qty`, `damaged_qty`.
- **Safety stock / reorder point / shortage are computed for STORE locations only**, using
  Module 3's forecast as the demand signal:
  - `avg_daily_demand` = mean of the forecast's median values over the horizon
  - `safety_stock` = `avg_daily_demand * business_rules.default_safety_stock_days`
  - `reorder_point` = `avg_daily_demand * default_lead_time_days * reorder_point_multiplier
    + safety_stock`
  - `shortage_qty` = `max(0, reorder_point - (available_qty + incoming_qty))`
  - **Why not terminals too**: terminals don't sell to consumers, so they have no demand
    forecast of their own — a terminal's real "demand" is the sum of the stores it
    supplies, which is the Allocation Agent's job (a later module), not this one's.
    Applying the store formula to a terminal would mean inventing a number nothing backs.
  - Store/product pairs with no forecast (e.g. brand-new products with no sales history)
    get `avg_daily_demand=None` and no shortage math, rather than a guessed value.
- `InventoryAnalysisResult.shortages` is a convenience subset (`shortage_qty > 0`) for the
  Supply Planning Agent to consume directly once it lands.

## Module 5: Supply Planning Agent

The fourth node (`analyze_inventory -> plan_supply -> END` for now). **First node to call
Groq** (`app/agents/supply_planning_agent.py`, via `langchain-groq`'s
`ChatGroq(...).with_structured_output(...)`, cached process-wide like the Chronos
pipeline).

- For every shortage from Module 4, candidate supplying terminals are found from real
  master data: terminal inventory rows for that product with stock > 0, joined against the
  distance matrix for (terminal, store). Terminals with no distance-matrix entry are
  skipped (no basis to estimate cost/delivery). Candidates are sorted by distance and
  capped at `supply_planning_max_candidate_terminals` (default 5) to bound prompt size at
  scale (10,000+ terminals).
- **Division of labor with the LLM, deliberately narrow**: Groq is prompted to propose one
  alternative candidate plan per candidate terminal, each with a `quantity`, a one-sentence
  `rationale`, and a `score` (0-100). It does **not** decide `estimated_transport_cost` or
  `estimated_delivery_hours` — those are computed here from the real distance matrix and
  `business_rules.estimated_transport_cost_per_km` (a rough proxy rate; real fleet-based
  costing is the future Cost Optimization Agent's job), then attached to whichever terminal
  the LLM picked. The LLM cannot hallucinate a distance or cost number into existence.
- The agent clamps each returned `quantity` to `[0, terminal.available_qty]` — the only
  validation it does on the first pass. It deliberately does **not** hard-enforce other
  business/capacity constraints (lead time, store/terminal capacity, max shipment qty) here
  — per the spec's own agent breakdown, that's the **Constraint Validation Agent**'s job
  (Module 8), which rejects invalid plans and sends them back here for replanning (see that
  module's section for how this agent uses that feedback on a retry). It also doesn't
  arbitrate cross-store priority trade-offs when terminal stock is scarce across many
  stores — that's the **Allocation Agent**'s job (Module 6).
- Shortages with zero candidate terminals go to `unresolved_shortages` without any LLM call.
- **Manual run**: `scripts/run_planning_workflow.py` now also prints ranked candidate
  plans with rationale — see the README. Needs `GROQ_API_KEY` set; the first four nodes
  don't.

## Module 6: Allocation Agent

The fifth node (`plan_supply -> allocate -> END` for now). **Second Groq call**
(`app/agents/allocation_agent.py`, its own cached `with_structured_output` client).

Module 5 generated candidate plans *independently* per shortage — it has no visibility
into two different stores' shortages both wanting the same scarce terminal stock. This
agent resolves that with three complete, mutually-exclusive allocation scenarios, each
respecting shared terminal stock as a real constraint:

- **`priority_first`**: highest-priority stores (lowest `priority` number) drain shared
  stock first, in order, each taking its best-Module-5-scored candidate first.
- **`score_first`**: globally greedy by Module 5's candidate score across *all* shortages
  at once, ignoring store priority entirely — a baseline for comparison.
- **`balanced`**: when multiple shortages contest the same (terminal, product) stock and
  it can't cover all of them, splits it proportionally to each shortage's size rather than
  letting first-come starve the rest.

These three directly answer the spec's own allocation questions: "Should high-priority
stores receive inventory first?" (`priority_first`), "Should inventory be split across
multiple terminals?" (`balanced`).

- **Deterministic math, not LLM math**: all three strategies are plain Python functions
  (`_priority_first_lines`, `_score_first_lines`, `_balanced_lines`) that track remaining
  stock per (terminal, product) and never over-allocate it. Conservation of stock across
  many shipment lines is exactly the kind of exact multi-step arithmetic LLMs are
  unreliable at, so it isn't delegated to one — same principle as Module 5's cost/distance
  numbers, applied at scenario granularity instead of per-line.
- **Groq's one job here**: rank the three finished scenario summaries (fulfillment rate,
  total cost, high-priority-shortages-fulfilled count) best-to-worst with a rationale per
  scenario — comparing finished proposals, not computing them.
- Quantities are capped with `math.ceil(shortage_qty)` per shortage (can't ship a
  fractional unit), which is why `fulfillment_rate` can read slightly over 100% — that's
  expected, not a bug.
- Zero shortages -> zero scenarios generated, zero Groq calls (same short-circuit pattern
  as Module 5).
- Scope boundary: this agent ranks scenarios; it doesn't pick one, refine costs (the future
  Cost Optimization Agent's job), or validate against business constraints (the future
  Constraint Validation Agent's job).
- **Manual run**: `scripts/run_planning_workflow.py` now also prints ranked allocation
  scenarios with rationale and a recommended strategy — see the README.

## Module 7: Cost Optimization Agent

The sixth node (`allocate -> optimize_cost -> END` for now). **No Groq call.**

Recomputes a detailed, real cost breakdown for each of Module 6's three scenarios,
replacing their flat per-km cost proxy with actual figures, then recommends the cheapest
scenario that still fully covers every high-priority shortage:

- **Transportation**: for each shipment line, picks the cheapest *capable* `AVAILABLE`
  vehicle at the source terminal (`Fleet.capacity_weight`/`capacity_volume` must both cover
  `Product.weight`/`volume` × quantity), cost = `vehicle.fixed_cost + vehicle.cost_per_km *
  distance_km`. If no vehicle at that terminal can actually carry the shipment, falls back
  to the largest available vehicle there and sets `vehicle_capacity_exceeded=True`
  (informational — this agent doesn't reject plans, that's the future Constraint Validation
  Agent's job); if there's no fleet at the terminal at all, falls back to
  `business_rules.estimated_transport_cost_per_km` so a total is still produced.
- **Warehouse handling**: `business_rules.warehouse_handling_cost_per_unit * quantity`
  (combined loading + unloading, since neither the spec nor the data model separates them).
- **Inventory holding**: `quantity * product.cost * business_rules.inventory_holding_cost_rate
  * business_rules.default_safety_stock_days` — the expected cost of capital/warehousing
  tied up for a representative holding period.
- **Delay penalty**: `max(0, travel_time_hours - default_lead_time_days*24) *
  business_rules.delay_penalty_per_hour` — 0 unless delivery exceeds the acceptable
  lead time.
- **Why no Groq call**: unlike Modules 5-6, this step is pure arithmetic (real fleet/
  product/business-rules data) plus a deterministic selection rule — argmin total cost
  among scenarios where `high_priority_shortages_fulfilled == high_priority_shortages_total`
  (falling back to best high-priority coverage, then lowest cost, if none fully qualify).
  There's no genuine judgment call here to delegate to an LLM.
- **Manual run**: `scripts/run_planning_workflow.py` now also prints each scenario's real
  cost breakdown and the cost-optimal recommendation — see the README.

## Module 8: Constraint Validation Agent

The seventh node, and **the first with a feedback loop** (`optimize_cost ->
validate_constraints ->` either `END` or back to `plan_supply`, via
`graph.add_conditional_edges` + `route_after_validation`). No Groq call — validation
against real data plus a deterministic decision tree, not a judgment call.

**Decision tree** (`validate_constraints_node`), evaluated after validating all three
scenarios:
1. Cost Optimization's recommended scenario is valid → carry it forward as-is.
2. It isn't, but a *different* already-generated scenario is valid → switch to the
   cheapest valid alternative. No replanning needed; one of the 3 already worked.
3. None are valid, and `replanning_attempts < max_replanning_attempts` (default 2) →
   route back to `plan_supply` with the violations attached to
   `state["constraint_validation"]`, incrementing `replanning_attempts`.
4. None are valid and attempts are exhausted → proceed best-effort with the recommended
   scenario, append the unresolved violations to `state["errors"]`, and set them on the
   result for a future Exception Handling Agent to pick up.

**Closing the loop for real**: `supply_planning_agent.py`'s
`_prior_violation_messages_by_shortage` reads `state["constraint_validation"]` when
`replanning_triggered` is true, groups violation messages by `(store_id, product_id)`, and
folds them into that shortage's Groq prompt ("a previous proposal was rejected for these
reasons: ... adjust accordingly"). Without this, looping back would just re-ask the same
question and likely get the same answer — this is what makes the retry an actual
correction attempt.

**Constraints implemented**, each grounded in a real field:
- `available_inventory`: per (terminal, product), summed outbound quantity across all
  lines in a scenario must not exceed the terminal's real `available_qty`.
- `store_capacity` / `terminal_capacity`: `Store.capacity`/`Terminal.capacity` fields exist
  in the spec's schema and are used directly — current total on-hand (all products) plus
  incoming quantity must not exceed a store's capacity; a terminal's current total on-hand
  must not already exceed its own capacity (in this outbound-only flow, shipping can only
  reduce a terminal's total, so this specific check is really a data-integrity check for a
  terminal that was already over capacity, not something a shipment itself triggers).
- `lead_time` (also covers "delivery window"): the spec lists these as two constraints,
  but nothing in the data model distinguishes a delivery window from delivery time itself
  (no store operating-hours/delivery-slot data exists anywhere), so they collapse into one
  check against `business_rules.max_lead_time_days` — a hard cap, distinct from
  `default_lead_time_days` (Module 7's soft/target threshold for cost penalties).
- `max_shipment_qty` / `min_shipment_qty`: Module 5 only *asks* Groq to respect
  `business_rules.max_shipment_qty_per_product`/`min_shipment_qty` in its prompt — it never
  hard-clamps them. This is the actual enforcement point.
- `business_priority`: flags a scenario that doesn't fully satisfy every high-priority
  store's shortage.

**Constraints explicitly NOT implemented, and why** (same honesty pattern as Module 3's
promotions-calendar gap):
- `safety_stock`: Module 4's shortage/reorder-point math already *is* "how far below
  safety stock is this store" — the reason the shipment exists at all. A second, separate
  check here would either restate that math or invent an unrelated threshold; neither is a
  genuine additional constraint given the current data model.
- `product_restrictions`: no field anywhere (Product, Store, or otherwise) encodes which
  products can or can't ship to which stores. Nothing to check.

**Manual run**: `scripts/run_planning_workflow.py` now also prints each scenario's
validation status, any violations, the final strategy, and replanning attempts used — see
the README.

## Module 9: Decision Review Agent

The eighth node (`validate_constraints -> review_decision -> END`, on the "end" branch of
Module 8's conditional edge). **Third Groq call** — its own cached `with_structured_output`
client.

Modules 6 and 8 already ranked and validated the scenarios, but only on fulfillment rate,
cost, and high-priority coverage. This agent adds the spec's remaining evaluation
dimensions, computed from real data:
- **Inventory balance**: `1 - stdev(shipped_qty / available_qty across each (terminal,
  product) pair involved)`, clamped to ≥0. Higher means stock was drawn down evenly across
  locations rather than draining one terminal while barely touching another.
- **Transportation distance**: sum of `distance_matrix.distance_km` across every line.
- **Demand fulfillment**: the scenario's `fulfillment_rate` (from Module 6).
- **Future inventory risk**: fraction of involved (terminal, product) pairs left below
  `decision_review_critical_stock_threshold` (default 10%) of their pre-shipment stock —
  did this scenario drain any terminal to a critical level for unrelated future demand?
- **Cost**: the scenario's real `total_cost` (from Module 7).
- **Business priorities**: `high_priority_shortages_fulfilled`/`total` (carried through).

**Only scenarios that passed Constraint Validation are ever reviewed** — an invalid plan
can't win no matter how well it scores on these dimensions. Groq gets all six real metrics
per valid scenario and returns one holistic 0-100 `overall_score` + rationale each; the
actual selection is `argmax(overall_score)` **in code**, not something the LLM declares —
same "LLM scores, code picks" split used everywhere else in this codebase.

**Why a fresh Groq call instead of reusing Module 6's ranking**: Module 6 ranked using only
its own rough proxy cost and fulfillment rate, computed before Module 7's real costing and
before Module 8 filtered out invalid options — genuinely different (and more refined) inputs
than what's available here, plus three entirely new dimensions (balance, distance, risk)
Module 6 never saw.

**If nothing passed Constraint Validation** (replanning attempts exhausted, Module 8
proceeded best-effort): this agent reviews only that single fallback scenario, sets
`fell_back_to_invalid_scenario=True`, and says so plainly in the rationale rather than
implying a confident choice was made among alternatives.

**Manual run**: `scripts/run_planning_workflow.py` now also prints each scenario's full
evaluation (all six metrics + score + rationale) and the final selection — see the README.

## Module 10: Final Recommendation Agent

The ninth and **last Phase 1 node** (`review_decision -> recommend_final -> END`). Fourth
Groq call. This completes every agent in the spec's 13-agent list except Phase 2's Fleet
Assignment, Route Planning, and ETA Prediction/Exception Handling.

Synthesizes the earlier eight nodes' output into the spec's exact requested shape.
Everything except the narrative fields is deterministic and lives in its own testable
function (`app/agents/final_recommendation_agent.py`), precisely so it can be verified
without a live Groq call:
- **`_build_shipment_plan`**: the selected scenario's lines, with real per-line costs from
  Module 7's `CostedLine`s, and each line's `explanation` **reused from Module 5's own
  rationale** for that exact (terminal, store, product) candidate — not a fresh LLM call
  per line. If no matching Module 5 candidate exists (shouldn't normally happen), falls back
  to a generic sentence rather than fabricating a specific-sounding one.
- **`_compute_expected_inventory`**: plain arithmetic — terminals decrease by shipped
  quantity, stores increase, against the master data snapshot's current stock.
- **`_build_alternatives`**: the other scenarios Module 9 already scored, each with a
  one-line deterministic reason (lower score than the selected one) for why it wasn't
  picked.
- `expected_service_level` = the selected scenario's `fulfillment_rate`; `expected_total_cost`
  = its real Module 7 total. No new computation needed for either.

**The one genuine synthesis task** — turning those real metrics into a coherent business
explanation, risk assessment, contingency actions, and a calibrated 0-100 confidence score
— goes to Groq, given the selected scenario's overall score, fulfillment rate, priority
coverage, balance/risk metrics, cost, whether Module 8 had to fall back to a
constraint-violating plan, and counts of unresolved violations/unfulfillable shortages. The
prompt explicitly instructs the confidence score to drop noticeably when any of those red
flags are present.

**Manual run**: `scripts/run_planning_workflow.py` now prints the full final
recommendation — shipment plan with per-line explanations, expected inventory, business
explanation, risk assessment, contingency actions, confidence score, and alternatives —
see the README.

## Phase 1 complete

Modules 2 through 10 implement all ten Phase 1 agents from the spec's original 13-agent
list (the 13th list's remaining 3 — Fleet Assignment, Route Planning, ETA Prediction — are
Phase 2, gated behind `Settings.fleet_module_enabled`, not started). The graph now runs
Load Master Data → Demand Forecast → Inventory Analysis → Supply Planning → Allocation →
Cost Optimization → Constraint Validation (with a replanning loop back to Supply Planning)
→ Decision Review → Final Recommendation, calling Groq four times (Supply Planning,
Allocation, Decision Review, Final Recommendation) and HuggingFace Chronos once (Demand
Forecast), with every other step pure deterministic computation against real data.
