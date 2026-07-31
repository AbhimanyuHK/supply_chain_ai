# Fleet Assignment Agent

The first of three new Phase 2 nodes, gated behind
`Settings.fleet_module_enabled` (default `False`): `validate_constraints →
assign_fleet → plan_route → predict_eta → review_decision`. Implemented in
`app/agents/fleet_assignment_agent.py`. **No LLM call.**

## Why this agent exists

{doc}`cost-optimization-agent` already picks a vehicle per shipment line —
but only as a costing proxy, independently per line, with no check that
several lines sharing the same vehicle would actually fit together. This
agent does the real, binding assignment: for every scenario that passed
{doc}`constraint-validation-agent`, lines sharing a source terminal are
grouped and packed onto the fewest vehicles that can actually carry them.

```{important}
`ShipmentPlanLine.vehicle_id` in the final output comes from **this**
agent, not Cost Optimization's `CostedLine.vehicle_id` — the two may
legitimately disagree, since Cost Optimization never checks cross-line
capacity sharing. This agent's assignment is authoritative.
```

## Algorithm

A deterministic first-fit-decreasing bin-pack, per `(scenario, terminal)`
group of allocation lines:

1. Sort the group's lines by `product.weight * quantity` descending.
2. Greedily place each line into the first already-opened vehicle (at that
   terminal) with enough remaining weight *and* volume capacity.
3. If none of the opened vehicles fit, open the next `AVAILABLE` vehicle at
   that terminal with enough capacity for this line alone.
4. If no available vehicle — opened or not — can carry the line alone,
   it's flagged `unassignable` rather than split across multiple vehicles.
   No line-splitting in this version — a documented limitation, not a
   silent drop; every unassignable line is surfaced in
   `ScenarioFleetAssignment.unassigned_lines`.

Only vehicles with `status == AVAILABLE` are ever considered — the same
filter {doc}`cost-optimization-agent`'s `_pick_vehicle` already uses.

## What this agent never does

It is strictly **read-only** against the master data snapshot's fleet
list. It never writes back to `Fleet.status` — no such repository method
exists, deliberately. An "available" vehicle here is available for
*planning* purposes only, not reserved for dispatch; reserving a real
vehicle for an actual trip is an operational side effect that belongs to
a future execution-tracking system, not this one-shot planning workflow.

## Manual run

```bash
FLEET_MODULE_ENABLED=true venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints, per scenario, every vehicle load (which lines, total weight/volume
vs. capacity) and any unassignable lines.
