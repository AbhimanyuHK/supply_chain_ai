# Cost Optimization Agent

The sixth node (`allocate → optimize_cost → ...`), implemented in
`app/agents/cost_optimization_agent.py`. **No LLM call.**

Recomputes a detailed, real cost breakdown for each of the Allocation
agent's three scenarios, replacing their flat per-km cost proxy with
actual figures, then recommends one scenario according to the run's
{doc}`optimization objective <../features/cost-objectives>`.

## Cost components, per shipment line

- **Transportation**: picks the cheapest *capable* `AVAILABLE` vehicle at
  the source terminal — `Fleet.capacity_weight`/`capacity_volume` must
  both cover `Product.weight`/`volume × quantity`. Cost =
  `vehicle.fixed_cost + vehicle.cost_per_km * distance_km`. If no vehicle
  at that terminal can actually carry the shipment, falls back to the
  largest available vehicle there and sets `vehicle_capacity_exceeded =
  True` (informational only — this agent doesn't reject plans; that's the
  {doc}`Constraint Validation Agent <constraint-validation-agent>`'s job).
  If there's no fleet at the terminal at all, falls back to
  `business_rules.estimated_transport_cost_per_km` so a total is still
  produced.
- **Warehouse handling**:
  `business_rules.warehouse_handling_cost_per_unit * quantity` (combined
  loading + unloading — neither the spec nor the data model separates
  them).
- **Inventory holding**:
  `quantity * product.cost * business_rules.inventory_holding_cost_rate *
  business_rules.default_safety_stock_days` — the expected cost of
  capital/warehousing tied up for a representative holding period.
- **Delay penalty**:
  `max(0, travel_time_hours - default_lead_time_days*24) *
  business_rules.delay_penalty_per_hour` — zero unless delivery exceeds
  the acceptable lead time.

## Why no LLM call

Unlike Supply Planning and Allocation, this step is pure arithmetic (real
fleet/product/business-rules data) plus a deterministic selection rule —
there's no genuine judgment call here worth delegating.

## Selection rule

`_recommend(scenarios, objective)` branches on
`PlanningRequest.optimization_objective`:

- **`minimize_cost`** (default) — cheapest scenario among those where
  `high_priority_shortages_fulfilled == high_priority_shortages_total`,
  falling back to best high-priority coverage then lowest cost if none
  fully qualify.
- **`maximize_service_level`** — highest `fulfillment_rate`
  (`ScenarioCostSummary.fulfillment_rate`, copied straight from the
  source `AllocationScenario`), using total cost only as a tiebreaker.

See {doc}`../features/cost-objectives` for the full rationale and how
this choice threads through the two downstream narrative agents.

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints each scenario's real cost breakdown and the recommended scenario
under the active objective.
