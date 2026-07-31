# ETA Prediction / Exception Handling Agent

The third and last of the new Phase 2 nodes: `assign_fleet → plan_route →
predict_eta → review_decision`. Implemented in
`app/agents/eta_prediction_agent.py`. **No LLM call.**

## Scope: planning-time risk flagging, not reactive exception handling

The original spec's "Exception Handling" was deliberately scoped, per an
explicit decision, to **predicting risk at planning time** — computed
once, during this planning run, alongside everything else. It is *not* a
real-time reactive system that watches an actual shipment for delays,
damage, or cancellations after dispatch — that would need genuinely new
infrastructure this platform doesn't have (shipment execution tracking,
an event intake endpoint, a background worker), a much larger, separate
undertaking than a single LangGraph node.

## Three real risk signals

Every stop in a vehicle's route gets a `predicted_eta_hours` (cumulative
real `travel_time_hours` along the route, plus a real-world variability
buffer, `business_rules.eta_variance_buffer_pct`, default 15%) and is
flagged `at_risk` if any of these fire:

| Signal | Why it's real, not fabricated |
|---|---|
| Predicted ETA exceeds `business_rules.max_lead_time_days * 24` | {doc}`constraint-validation-agent` only ever checked a single leg's time — a stop late in a multi-drop route can breach this hard cap in a way Constraint Validation had no way to see, since routing didn't exist yet when it ran. |
| The assigned vehicle was flagged `vehicle_capacity_exceeded` by {doc}`cost-optimization-agent` | Matched by `vehicle_id` — an approximate signal, since Cost Optimization's `vehicle_id` is a per-line costing proxy that may legitimately differ from {doc}`fleet-assignment-agent`'s real, binding assignment. Still a real, meaningful correlation worth flagging. |
| This scenario needed at least one replanning attempt (`constraint_validation.replanning_triggered`) | Already borderline once — a genuine prior signal, not invented. |

Each flagged stop gets a short, deterministic `suggested_contingency`
string keyed off whichever reason fired (e.g. "Split shipment across an
additional vehicle" for a capacity issue, "Expedite or re-source from a
closer terminal" for a lead-time breach) — no LLM call.

## Where this feeds into the rest of the pipeline

No new LLM call is added for this. Instead:

- {doc}`decision-review-agent`'s `ScenarioEvaluation` gains
  `at_risk_stops_count` (alongside Fleet Assignment's
  `unassigned_lines_count`) as **passthrough metrics** — real data
  captured, but not yet fed into Decision Review's LLM prompt or its
  `argmax` selection. A deliberate, documented follow-up, not an
  oversight.
- {doc}`final-recommendation-agent`'s *existing* 4th LLM call is enriched
  with the winning scenario's `at_risk_count` as one more real data point
  for its business narrative and contingency actions — rather than
  adding a competing 5th LLM call here.

## Manual run

```bash
FLEET_MODULE_ENABLED=true venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints each stop's predicted ETA, risk flag, and any triggered reasons.
