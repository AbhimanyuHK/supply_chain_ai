# Development integration notes

New API routes on the dev branch:

- GET /api/v1/planning-runs/{run_id}/stress-test?multipliers=0.8,1.0,1.2 returns demand-multiplier what-if coverage for persisted scenarios. Multipliers are not calibrated forecast intervals.
- POST /api/v1/decisions/events/{event_id}/execute runs the queued event against a supplied PlanningRequest after authenticating with X-Operator-Token. A compare-and-swap claim prevents concurrent execution of the same queued record.
- GET /api/v1/planning-runs/{run_id}/benchmark compares persisted allocation candidates.

The Control Tower displays benchmark and stress-test results. No autonomous event worker is implemented. Approval decisions are auditable but do not dispatch shipments.

Before release, run database migrations, unit tests, API integration tests, concurrent event tests, security review, and provider-backed smoke tests. Production authentication for planning endpoints, calibrated forecast intervals, actual store-to-store road distances, and queue-worker recovery remain incomplete. These changes are not production validated.


## Security and resilience follow-up
All planning routes, including optimize, run history, benchmark and stress-test, now require the same X-Operator-Token authentication as the decision routes. Set SUPPLY_CHAIN_OPERATOR_TOKEN before starting the API. The Streamlit Control Tower prompts for this token in its sidebar and sends it in a request header. The shared token is a development gate, not per-user RBAC or a complete production identity system.

Allocation now retains deterministic baseline scenarios if LLM candidate generation fails and applies deterministic objective ranking if the ranking model fails. The critic failure is isolated from already validated LLM plans. The original master branch remains unchanged.

Local test execution is blocked because this environment cannot resolve github.com for git clone; GitHub commits do not establish passing tests. Production release remains gated on verified migrations, auth, concurrency, event recovery and forecast calibration.


## Latest fleet and event safety changes
- LLM fleet assignments must pass the independent weight/volume/terminal/availability validator and now replace the deterministic baseline only when they reduce the vehicle count or eliminate unassigned lines.
- Explicit event execution requires non-null store_ids and product_ids to avoid accidentally replanning the entire supply chain from a loosely scoped event.
- CI runs on dev branch pushes. Check the GitHub Actions run conclusion; a workflow marked in_progress does not establish passing tests.


## Human approval gates shipment creation
- Planning runs no longer write Shipment rows, regardless of the legacy auto_create_shipment_records setting.
- After approving a valid plan, operators may call POST /api/v1/decisions/planning-runs/{run_id}/create-shipments with X-Operator-Token.
- The endpoint requires matching approved strategy and independently validated final strategy, refuses invalid fallback plans, and creates PLANNED shipment records only (not dispatch).
- A repeat request is rejected when shipments already exist for the planning run. This is a guard, not a full cross-database exactly-once guarantee; SQLite lacks SELECT FOR UPDATE semantics. Production requires a unique dispatch/request key or transaction-level lock.
- CI push and pull request triggers remain restricted to master. Do not enable dev CI until requested.


## Shipment creation concurrency hardening
Migration 0006_shipment_creation_claims adds a unique planning_run_id claim.
The approved-shipment endpoint inserts the claim and shipment lines in one transaction.
Concurrent duplicate claims return HTTP 409. Apply alembic upgrade head before using the endpoint.
This does not reserve inventory, dispatch vehicles, or guarantee exactly-once downstream fulfillment.


## Additional approval and replanning safety
- Approval rejects a recommendation whose selected_strategy differs from the independently validated final_strategy, and any recommendation flagged fell_back_to_invalid_scenario.
- Event execution rejects omitted or empty store_ids/product_ids and marks a run failed if the workflow returns errors or no planning_run_id.
- Added focused approval safety regression tests (not yet executed).
- Automatic CI is restricted to master; dev commits must not trigger CI.


## Control Tower visibility and focused tests
- Control Tower now displays the selected planning run's approval decision and the latest 50 replanning events, read-only.
- Added regression coverage for a successful matching approval and the unique shipment claim ORM metadata.
- These changes are committed to dev only and have not been validated by CI.


## Replanning recovery
Migration 0007 adds processing timestamps, attempt counts, last error and planning run linkage.
POST /api/v1/decisions/events/recover-stale?timeout_minutes=60 is operator authenticated and marks timed-out processing events failed for review.
Operators should verify the prior execution has stopped before retrying. Recovery never automatically retries an uncertain operation.
Conditional event completion updates protect against late workers overwriting a recovered status.
Apply alembic upgrade head before using these features. Autonomous queue processing remains pending.


## Opt-in replanning worker
Migration 0008 stores an optional planning_request on each event. The event intake API validates non-empty store_ids and product_ids before persisting that scope. Legacy events without a scope remain manual-only.
Set ENABLE_REPLANNING_WORKER=1 and run python -m app.services.replanning_worker to process up to 10 scoped queued events in one pass. An external scheduler may invoke this command periodically; it does not start automatically.
The worker uses database compare-and-swap claims and an attempt counter to fence late results. It never creates shipments or dispatches vehicles. Failed events require operator review and explicit retry.
Manual event execution also refuses requests that differ from the event's persisted scope.
Apply alembic upgrade head before using the worker. Full queue supervision, lease heartbeats, metrics and end-to-end integration tests remain pending.
CI remains restricted to master; dev changes are not automatically tested.


## Outcome feedback, calibration, security and monitoring (migration 0009)
Apply alembic upgrade head before using these endpoints.
- POST /api/v1/outcomes records observed store/product/day demand, fulfilled units and actual cost. external_reference is unique for duplicate protection.
- GET /api/v1/outcomes/planning-runs/{run_id}/evaluation reports observed service level, actual cost, forecast MAE, empirical interval coverage and a finite-sample interval-miss quantile. These are descriptive, in-sample diagnostics, NOT independently validated confidence guarantees. Use disjoint held-out calibration and evaluation periods before deploying calibrated bounds in optimization.
- GET /api/v1/operations/summary exposes authenticated counts of planning runs, replanning states and outcome records.
- Control Tower displays outcome evaluation and operational monitoring.
- POST approval now requires X-Approver-Token with SUPPLY_CHAIN_APPROVER_TOKEN. POST create-shipments requires X-Fulfillment-Token with SUPPLY_CHAIN_FULFILLMENT_TOKEN. Both fail closed when missing. Operator API access still requires X-Operator-Token. This is basic credential separation, NOT identity-aware RBAC, OIDC or a complete audit authorization system.
- New focused tests cover numerical calibration, feedback summaries and credential separation. They have NOT been run.
- CI remains master-only as requested; master has not been changed.
Outstanding: end-to-end database integration tests, worker crash recovery tests, independent held-out calibration, production identity and role integration, real tracing/alerts, and verified migrations.


## Consolidated completion pass and release gates
- Forecasts: retrospective date-split calibration is available at GET /api/v1/outcomes/planning-runs/{run_id}/heldout-evaluation?cutoff_date=YYYY-MM-DD. Calibration samples strictly precede the cutoff; evaluation samples are on or after it. A single planning run may have no usable cross-period data. This does not prove prospective calibration unless forecast issuance timestamps precede observed dates and training data cannot leak.
- Database test fixture cleanup now removes PlanningOutcome, PlanApproval, ShipmentCreationClaim and ReplanningEvent before PlanningRun.
- Added DB uniqueness integration tests for approval decisions, shipment claims and event IDs.
- Required release verification: alembic upgrade head against an isolated database; pytest; ruff check .; concurrent shipment-claim and replanning-worker tests against the production DB dialect; API auth negative tests; end-to-end UI and workflow smoke tests.
- Unfinished production hardening: replace shared tokens with enterprise OIDC identity and fine-grained authorization; trace and alert on worker failures; calibrate forecasts prospectively on independent time periods; prove recovery safety under worker termination and database failure.
- Do not describe this branch as production-ready before those release gates pass. Master-only CI policy is unchanged.
