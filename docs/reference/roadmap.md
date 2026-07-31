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

## Phase 2 — not started

The original spec's remaining three agents, gated behind
`Settings.fleet_module_enabled` (currently `false`):

- **Fleet Assignment Agent** — assign specific vehicles to shipment
  lines ahead of dispatch (today, {doc}`../agents/cost-optimization-agent`
  only picks a vehicle for *costing* purposes, not a binding assignment).
- **Route Planning Agent** — multi-stop route optimization across
  shipments, rather than the current point-to-point terminal→store model.
- **ETA Prediction / Exception Handling Agent** — predict realistic
  delivery times accounting for real-world variability, and handle
  in-flight exceptions (delays, damage, cancellations) against the
  currently-unused `Shipment` table (see
  {doc}`../architecture/database-schema`).

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
2. Insert `Shipment` rows from an approved `FinalRecommendation` — the
   natural bridge from an AI-generated plan to an operational shipment
   record (see {doc}`../architecture/database-schema`).
3. Add RPM-aware pacing to the Supply Planning batch scheduler if Gemini
   (or another tightly-capped provider) becomes a primary path rather
   than a fallback.
4. Begin Phase 2 (Fleet Assignment first — the other two build on it).
