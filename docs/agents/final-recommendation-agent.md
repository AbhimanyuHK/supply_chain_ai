# Final Recommendation Agent

The ninth and **last Phase 1 node** (`review_decision → recommend_final →
END`), implemented in `app/agents/final_recommendation_agent.py`. The
**fourth** and final node to call a reasoning engine. Completes every
agent in the spec's Phase 1 agent list.

## Deterministic synthesis

Everything except the narrative fields is computed by plain, independently
testable functions — precisely so the shipment plan itself can be
verified without a live LLM call:

- **`_build_shipment_plan`** — the selected scenario's lines, with real
  per-line costs from Cost Optimization's `CostedLine`s, and each line's
  `explanation` **reused from Supply Planning's own rationale** for that
  exact `(terminal, store, product)` candidate — not a fresh LLM call per
  line. If no matching Supply Planning candidate exists (shouldn't
  normally happen), it falls back to a generic sentence rather than
  fabricating a specific-sounding one. When `Settings.fleet_module_enabled`
  is `True`, each line also gets `vehicle_id`/`route_sequence`/
  `predicted_eta_hours` from {doc}`fleet-assignment-agent`/
  {doc}`route-planning-agent`/{doc}`eta-prediction-agent` (all `None`
  otherwise) — this `vehicle_id` is the authoritative, binding one,
  distinct from Cost Optimization's own per-line proxy pick.
- **`_compute_expected_inventory`** — plain arithmetic: terminals decrease
  by shipped quantity, stores increase, against the master data
  snapshot's current stock.
- **`_build_alternatives`** — the other scenarios Decision Review already
  scored, each with a one-line deterministic reason (lower score than the
  selected one) for why it wasn't picked.
- `expected_service_level` = the selected scenario's `fulfillment_rate`;
  `expected_total_cost` = its real total from Cost Optimization. No new
  computation needed for either.

## The one genuine synthesis task

Turning those real, already-computed metrics into a coherent business
explanation, risk assessment, contingency actions, and a calibrated 0-100
confidence score is the one thing actually delegated to the LLM. It's
given the selected scenario's overall score, fulfillment rate, priority
coverage, balance/risk metrics, cost, whether Constraint Validation had to
fall back to a constraint-violating plan, and counts of unresolved
violations/unfulfillable shortages. The prompt explicitly instructs the
confidence score to drop noticeably when any of those red flags are
present — a run with real problems should never read as confidently as a
clean one. When the fleet module is enabled, the prompt also names how
many shipment lines {doc}`eta-prediction-agent` flagged at elevated
delivery risk — one more real signal for the same narrative and
confidence score, rather than a competing 5th LLM call.

This agent also writes real `Shipment` rows — see
{doc}`../features/persistence-and-audit-trail` and
{doc}`../architecture/database-schema` for where and how.

`_build_prompt` also names which
{doc}`optimization objective <../features/cost-objectives>` drove the
scenario selection, for narrative consistency with what Cost Optimization
actually optimized for.

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints the full final recommendation: shipment plan with per-line
explanations, expected inventory, business explanation, risk assessment,
contingency actions, confidence score, and alternatives.
