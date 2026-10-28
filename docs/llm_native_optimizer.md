# LLM-native allocation (development preview)

This branch adds an **opt-in experimental LLM allocation solver**. No OR-Tools, CBC, Gurobi, or Pyomo.

Set `LLM_NATIVE_OPTIMIZER_ENABLED=true` and optionally `LLM_OPTIMIZER_ITERATIONS=3` in your environment. The existing three Python allocation heuristics remain as baselines and the default behavior remains unchanged.

The LLM proposes full allocation quantities; Python independently rejects proposals that use unknown lanes, exceed terminal-product stock, or exceed store-product shortages. Accepted proposals join the existing cost optimization, constraint validation, and decision-review pipeline. The LLM gets objective feedback between bounded attempts.

**Important limitations:** This is an initial implementation, not a globally optimal solver. It does not yet implement a separate critic agent, persist cross-run best-solution memory, add fleet/route feasibility into the proposal loop, or perform full benchmark evaluation. The current objective feedback uses estimated allocation costs; final downstream costing and business validation remain authoritative. An invalid LLM proposal is discarded; the existing deterministic baselines remain available. LLM API errors are not silently suppressed.

## Testing

`pytest tests/test_llm_native_optimizer.py`

Run the existing suite before promoting this experimental mode. Do not enable for operational decisions without further validation.


## Critic-guided improvement (development)
The experimental solver now calls a separate structured-output Critic Agent between valid candidate attempts. Duplicate candidate fingerprints are detected and search stops after repeated stagnation. The existing deterministic allocation heuristics remain available as baselines.

## Benchmarking
`app/services/optimization_evaluator.py` reports each scenario's feasibility, source, fulfillment, priority coverage, estimated cost and delta against the priority-first baseline. It is a metric utility, not an automated end-to-end benchmark runner.

## Remaining work before the complete roadmap is delivered
- Real end-to-end tests and CI verification with mock LLMs and database fixtures.
- Stronger validator for shipment limits, store capacity, route feasibility and fleet constraints *before* candidate acceptance.
- Structured persistence of per-iteration proposals, critic feedback, feasibility and token/latency metrics.
- Robust multi-objective and uncertainty-aware optimization across forecast quantiles.
- LLM fleet and route proposals with independent operational validation.
- HITL approval and execution safeguards; do not persist recommendations as dispatched shipments.
- Event-triggered replanning, scenario simulation and control-tower visualization.
- Cache fingerprint must include optimizer configuration/prompt versions to avoid stale runs.
- True route optimization requires store-to-store distances; terminal-to-store distance sums are only proxies.

**Safety:** Experimental LLM proposals must not be automatically dispatched. No claim of global optimality is made.


## Additional development modules
- `app/services/uncertainty_simulation.py`: scenario demand stress tests with explicit multipliers (not calibrated Chronos quantiles).
- `app/services/replanning_events.py`: deterministic event trigger, magnitude threshold and cooldown (no queue consumer wired).
- `app/services/approval_workflow.py`: pure approval state machine requiring reviewer and reason (no persistent approval API yet).
- `app/agents/constraint_validation_agent.py`: now checks lane references and demand conservation, selects among feasible plans for the requested objective, and does not label an infeasible plan as final.
- `tests/test_supply_chain_decision_services.py`: targeted tests for these modules.

**Integration warning:** The new services are isolated primitives, not yet connected to persistent APIs, scheduling, authentication, or Streamlit. The broader roadmap is NOT fully delivered. Tests have been committed but not executed in this environment.


## New integrations
- Read-only Control Tower: `pip install -r requirements-control-tower.txt` then `streamlit run control_tower.py` while FastAPI runs locally.
- API endpoint: `GET /api/v1/planning-runs/{run_id}/benchmark` compares persisted allocation candidates.
- LLM fleet planner: `app/agents/llm_fleet_optimizer.py` proposes vehicle assignments and independently validates aggregate weight, volume, availability and source-terminal consistency. **It is not yet wired into the fleet LangGraph node.**
- Shipment creation is now disabled by default via `AUTO_CREATE_SHIPMENT_RECORDS=false`. This is a behavioral change from master; explicitly review legacy integrations. Even with the flag enabled, no shipment rows are created for plans with unresolved violations.

## Release gate
Do not merge until tests, lint, API smoke tests, database migrations and actual provider calls are verified. Approval decisions and event triggers remain pure functions without persistence/authentication/queue wiring. The Control Tower is read-only. Full LLM routing, calibrated demand uncertainty, and multi-run memory remain unfinished.


## Latest LangGraph integration
When both `LLM_NATIVE_OPTIMIZER_ENABLED=true` and `FLEET_MODULE_ENABLED=true`, Fleet Assignment now attempts an LLM-proposed full vehicle mapping. Independent Python checks vehicle availability, terminal match, total weight and volume; on invalid output or model failure, the deterministic packing algorithm is used. Route Planning likewise attempts LLM stop sequencing with exact stop-set validation, falling back to nearest-terminal-distance order.

The route's distance and cost remain **terminal-leg proxies**, not actual multi-stop road-network optimization, until inter-store distances are added. An updated fingerprint now includes optimizer settings and a manual planner revision to reduce stale cache reuse. Increment the revision on any future prompt/algorithm change.

## Operational status
These modules are committed but untested in the current execution environment: outbound git access could not resolve github.com. Do not treat code committed to GitHub as verified deployment. Approvals, event triggers, calibrated uncertainty, persistent optimization feedback, and fully secured APIs still need end-to-end integration.


## Persistent decision endpoints (development)
Run `alembic upgrade head` to create `plan_approvals` and `replanning_events`.
Set `SUPPLY_CHAIN_OPERATOR_TOKEN` to a high-entropy secret. Every endpoint below requires an `X-Operator-Token` header. With the secret unset, requests fail closed (403).

- `POST /api/v1/decisions/planning-runs/{run_id}/approval`: body `{"reviewer":"...","reason":"...","approve":true}`. Requires a completed run with a validated final strategy; duplicate decisions return 409.
- `GET /api/v1/decisions/planning-runs/{run_id}/approval`: read the persistent decision.
- `POST /api/v1/decisions/events`: accepts `SupplyChainEvent`, deduplicates by event ID, applies threshold and cooldown, and records an action of `queued` or `ignored`.

**Queue semantics:** `queued` means a durable database record, **not** an executing worker or message-broker enqueue. A worker with an explicit planning scope and transactional claim/acknowledgment must be implemented before automatic replanning is available. Approvals are audit decisions and do not dispatch shipments.

Security scope: this shared operator token protects only the new decision endpoints; other API endpoints still need production authentication, authorization, rate limiting, and audit review. A database uniqueness constraint handles duplicate event IDs, but simultaneous conflicting requests still need explicit integrity-error handling. Do not enable production event ingestion until those safeguards and tests are complete.
