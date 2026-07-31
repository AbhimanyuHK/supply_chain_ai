# Route Planning Agent

The second of three new Phase 2 nodes: `assign_fleet → plan_route →
predict_eta`. Implemented in `app/agents/route_planning_agent.py`. **No
LLM call.**

## What it computes

For every vehicle load {doc}`fleet-assignment-agent` produced, this agent
sequences its stops and computes a route-level cost:

- **Stop order**: a vehicle's distinct destination stores (deduplicated —
  multiple product lines to the same store are one stop) are ordered by
  terminal-to-store distance ascending — a nearest-first dispatch
  heuristic.
- **`total_route_distance_km`**: the sum of each stop's terminal-to-store
  distance.
- **`route_transportation_cost`**: `vehicle.fixed_cost` counted **once**
  per route + `vehicle.cost_per_km * total_route_distance_km`.

```{important}
This corrects a real double-counting issue in
{doc}`cost-optimization-agent`'s proxy costing: when several lines
actually share one vehicle trip, charging each line its own full
`fixed_cost` overstates the true cost. `route_transportation_cost` is
**additional informational detail** — it does not retroactively change
`ScenarioCostSummary.total_cost`, which already drove scenario selection
earlier in the pipeline. Two different "cost" figures legitimately
coexist for the same scenario: one a per-line costing proxy computed
before routing existed, one a route-level operational figure computed
after.
```

## A real data limitation, stated plainly

There is no store-to-store distance anywhere in this platform's data
model — `DistanceMatrix` only has terminal↔store legs (see
{doc}`../architecture/database-schema`). True multi-stop routing needs
inter-stop legs that simply don't exist here. Rather than fabricate them,
this agent uses only data that's real: nearest-terminal-distance-first
ordering, and total route distance as the sum of each stop's
terminal-to-store distance — an explicit, documented **proxy** for a true
route length, not a claim of one. The same honesty pattern as
`estimated_transport_cost_per_km`'s existing proxy role in
{doc}`supply-planning-agent`/{doc}`allocation-agent`.

## Manual run

```bash
FLEET_MODULE_ENABLED=true venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints each vehicle's ordered stops, total route distance, and
route-level transportation cost.
