# Roadmap

## Phase 1 — complete

All ten of the original spec's Phase 1 agents are built, tested, and
wired into one LangGraph workflow: Master Data, Demand Forecast,
Inventory Analysis, Supply Planning, Allocation, Cost Optimization,
Constraint Validation (with a replanning loop), Decision Review, Final
Recommendation. See {doc}`../agents/overview` and
{doc}`../architecture/planning-workflow`.

On top of the core pipeline, several cross-cutting features are also
shipped: a three-provider reasoning-engine abstraction
({doc}`../features/reasoning-engines`), a Streamlit demo dashboard
({doc}`../interfaces/streamlit-dashboard`), a REST API for triggering runs
and browsing the audit trail ({doc}`../interfaces/rest-api`), full
planning-run persistence and audit trail
({doc}`../features/persistence-and-audit-trail`), idempotent/cached runs
({doc}`../features/idempotency-and-caching`), a configurable cost
objective ({doc}`../features/cost-objectives`), six scalability fixes
validated against the platform's real target scale
({doc}`../features/scalability`), and enforced lint standards
(`ruff`, {doc}`../operations/ci-cd`).

## Phase 2 — complete

The original spec's remaining three agents are built, tested, and wired
into the graph behind `Settings.fleet_module_enabled` (default `false` —
opt-in, since they add real complexity and the default 9-node graph
behavior must stay byte-identical to before Phase 2 existed):

- **{doc}`../agents/fleet-assignment-agent`** — a deterministic
  first-fit-decreasing bin-pack assigning specific, capacity-respecting
  vehicles to shipment lines (the real, binding assignment — Cost
  Optimization's own per-line vehicle pick is only a costing proxy).
- **{doc}`../agents/route-planning-agent`** — sequences each vehicle's
  stops nearest-first and computes a corrected, fixed-cost-counted-once
  route transportation cost (an explicit, documented proxy — no
  store-to-store distance data exists anywhere in this platform's model).
- **{doc}`../agents/eta-prediction-agent`** — predicts each stop's
  delivery ETA and flags real, threshold-based delivery risk. Scoped, per
  an explicit decision, to **planning-time risk flagging**, not real-time
  reactive exception handling (that would need genuinely new
  infrastructure — execution tracking, an event intake endpoint, a
  background worker — this platform doesn't have).

All three are deterministic (no new LLM calls); the real risk signal ETA
Prediction computes feeds Final Recommendation's *existing* 4th LLM call
instead. A completed run now also writes real `Shipment` rows,
unconditionally, finally activating that previously-unused table — see
{doc}`../architecture/database-schema`.

**Known limitation, deliberately deferred**: Decision Review gained two
passthrough metrics (`unassigned_lines_count`, `at_risk_stops_count`) —
real data captured from the new agents, but not yet fed into its LLM
prompt or `argmax` selection. A documented follow-up, not an oversight.

## Known gaps in Phase 1 itself

Documented deliberately, not hidden:

- **REST API surface** — `/health`, `/optimize`, and the `/planning-runs`
  audit endpoints are implemented; `/forecast`, `/inventory`,
  `/fleet/assign`, `/route/optimize`, `/simulate`, `/shipments` are not.
  See {doc}`../interfaces/rest-api` for what's built and why the rest
  isn't yet. `/optimize` itself is synchronous for now — see the next
  point.
- **No forward-looking promotions/holiday calendar** — Chronos forecasts
  from historical series shape alone; there's no data source for a
  future promotion or holiday flag. See
  {doc}`../agents/demand-forecast-agent`.
- **Two constraints not implemented** — `safety_stock` as a distinct
  check (redundant with Inventory Analysis's existing shortage math) and
  `product_restrictions` (no field anywhere encodes which products can
  ship to which stores). See {doc}`../agents/constraint-validation-agent`.
- **`/optimize` is synchronous, no task queue for concurrent runs** — fine
  today at this platform's scale (single-digit-to-low-tens-of-seconds
  runs); the recommended upgrade (`BackgroundTasks` + a `PENDING` status +
  polling) is documented in {doc}`../features/scalability` (Fix 6), not
  built.
- **RPM pacing for LLM batches** — the current fix bounds *simultaneity*
  (a semaphore), not requests-per-minute. Not an issue for Groq, but
  Gemini's tight per-minute cap can still be exceeded across sequential
  batches. See {doc}`../features/scalability` (Fix 4).
- **Idempotency fingerprint doesn't capture code/prompt version** — a
  stale cache hit could theoretically serve a plan computed under
  different application logic if the app was redeployed between two
  identical-scope calls. See {doc}`../features/idempotency-and-caching`.
- **No authentication anywhere** — both the REST API and the Streamlit
  dashboard are unauthenticated; see {doc}`../operations/deployment`'s
  production checklist.

## Natural next steps, roughly in priority order

1. Upgrade `/optimize` to the `BackgroundTasks` + `202` + polling pattern
   if request volume or scope size ever makes the current synchronous
   response too slow (see {doc}`../features/scalability`, Fix 6).
2. Feed Decision Review's new `unassigned_lines_count`/`at_risk_stops_count`
   passthrough metrics into its LLM prompt and scoring, now that real data
   for them exists (see {doc}`../agents/decision-review-agent`).
3. Add RPM-aware pacing to the Supply Planning batch scheduler if Gemini
   (or another tightly-capped provider) becomes a primary path rather
   than a fallback.
4. Consider real store-to-store distance data if Route Planning's
   nearest-first/sum-of-legs proxy ever needs to become true multi-stop
   routing (see {doc}`../agents/route-planning-agent`).
