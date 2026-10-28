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
