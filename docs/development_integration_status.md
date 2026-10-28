# Development integration notes

New API routes on the dev branch:

- GET /api/v1/planning-runs/{run_id}/stress-test?multipliers=0.8,1.0,1.2 returns demand-multiplier what-if coverage for persisted scenarios. Multipliers are not calibrated forecast intervals.
- POST /api/v1/decisions/events/{event_id}/execute runs the queued event against a supplied PlanningRequest after authenticating with X-Operator-Token. A compare-and-swap claim prevents concurrent execution of the same queued record.
- GET /api/v1/planning-runs/{run_id}/benchmark compares persisted allocation candidates.

The Control Tower displays benchmark and stress-test results. No autonomous event worker is implemented. Approval decisions are auditable but do not dispatch shipments.

Before release, run database migrations, unit tests, API integration tests, concurrent event tests, security review, and provider-backed smoke tests. Production authentication for planning endpoints, calibrated forecast intervals, actual store-to-store road distances, and queue-worker recovery remain incomplete. These changes are not production validated.
