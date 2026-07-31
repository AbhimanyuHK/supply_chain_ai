# Decision Review Agent

The eighth node (`validate_constraints → review_decision → ...`, on the
"proceed" branch of the Constraint Validation agent's conditional edge).
Implemented in `app/agents/decision_review_agent.py`. The **third** node
to call a reasoning engine, via its own cached
`with_structured_output` client.

## Why this agent exists

Allocation and Constraint Validation already ranked and validated the
scenarios, but only on fulfillment rate, cost, and high-priority coverage.
This agent adds the spec's remaining evaluation dimensions, every one
computed from real data:

| Dimension | How it's computed |
|---|---|
| Inventory balance | `1 - stdev(shipped_qty / available_qty)` across each involved `(terminal, product)` pair, clamped to ≥ 0. Higher means stock was drawn down evenly rather than draining one terminal while barely touching another. |
| Transportation distance | Sum of `distance_matrix.distance_km` across every line in the scenario. |
| Demand fulfillment | The scenario's `fulfillment_rate`, carried through from Allocation. |
| Future inventory risk | Fraction of involved `(terminal, product)` pairs left below `Settings.decision_review_critical_stock_threshold` (default 10%) of their pre-shipment stock. |
| Cost | The scenario's real `total_cost`, from Cost Optimization. |
| Business priorities | `high_priority_shortages_fulfilled` / `total`, carried through. |

## Only valid scenarios are reviewed

An invalid plan can't win no matter how well it scores on these
dimensions — only scenarios that passed
{doc}`Constraint Validation <constraint-validation-agent>` are ever
reviewed. The reasoning engine receives all six real metrics per valid
scenario and returns one holistic 0-100 `overall_score` + rationale each;
the actual selection is `argmax(overall_score)` **in code**, never
something the LLM declares directly — the same "LLM scores, code picks"
split used throughout this codebase.

## Why a fresh LLM call instead of reusing Allocation's ranking

Allocation ranked using only its own rough proxy cost and fulfillment
rate, computed *before* Cost Optimization's real costing and *before*
Constraint Validation filtered out invalid options — genuinely different
(and more refined) inputs than what's available here, plus three entirely
new dimensions (balance, distance, risk) Allocation never saw.

## Phase 2 passthrough metrics (real data, not yet weighed)

When `Settings.fleet_module_enabled` is `True`, `ScenarioEvaluation` also
carries `unassigned_lines_count` (from {doc}`fleet-assignment-agent`) and
`at_risk_stops_count` (from {doc}`eta-prediction-agent`) for each scenario
— both default to `0` when the fleet module is off. This is a deliberate,
documented follow-up: the data is captured and visible in the output/audit
trail, but it is **not yet** fed into the LLM prompt's weighing text or
the `argmax` selection above. A scenario with many unassigned lines or
high delivery risk isn't penalized here today — see
{doc}`../reference/roadmap` for the planned next step.

## Fallback case

If nothing passed Constraint Validation (replanning attempts exhausted,
that agent proceeded best-effort), this agent reviews only that single
fallback scenario, sets `fell_back_to_invalid_scenario = True`, and says
so plainly in the rationale rather than implying a confident choice was
made among alternatives that don't exist.

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints each valid scenario's full evaluation (all six metrics + score +
rationale) and the final selection.
