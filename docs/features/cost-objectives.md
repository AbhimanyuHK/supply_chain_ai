# Cost Objective Toggle

`PlanningRequest.optimization_objective`
(`"minimize_cost"` default, or `"maximize_service_level"`) makes explicit
a choice the system previously made implicitly and unconditionally:
should a plan minimize total cost, or maximize how much demand actually
gets fulfilled?

## Why a per-run field, not a global setting

This is a per-request field on `PlanningRequest`, not a global policy in
`config/business_rules.yaml`. `get_business_rules()` (like `get_settings()`)
is process-wide `@lru_cache`'d — a global toggle would leak across
concurrent runs once the deferred `/optimize` REST endpoint exists, and
different runs may legitimately want different trade-offs (a holiday rush
scope wanting maximum service level, a routine restock wanting minimum
cost) at the same time. See {doc}`../getting-started/configuration` for
the full list of what's an environment variable versus a per-request
field, and why.

## What each objective actually changes

`app/agents/cost_optimization_agent.py::_recommend(scenarios, objective)`
is the single decision point:

- **`minimize_cost`** — keeps the platform's original rule: the cheapest
  scenario among those that fully satisfy every high-priority shortage
  (`high_priority_shortages_fulfilled == high_priority_shortages_total`).
- **`maximize_service_level`** — picks the scenario with the highest
  `fulfillment_rate` (now copied onto `ScenarioCostSummary` from the
  source `AllocationScenario` specifically to support this), using cost
  only as a tiebreaker between otherwise-equal fulfillment rates.

See {doc}`../agents/cost-optimization-agent` for where this sits in that
agent's overall responsibility.

## Downstream narrative consistency

Two later agents adjust their prompts to stay consistent with whichever
objective actually drove the selection — otherwise the LLM-authored
narrative could describe a rationale that doesn't match what was actually
optimized for:

- {doc}`../agents/decision-review-agent`'s `_build_prompt` rewords its
  stated weighing-order sentence to match (cost moves earlier in the
  stated priority order for `minimize_cost`).
- {doc}`../agents/final-recommendation-agent`'s `_build_prompt` names
  which objective drove the selection directly, in the synthesized
  business explanation.

## Interaction with idempotency

`optimization_objective` is folded into `PlanningRequest.scope_key()` —
see {doc}`idempotency-and-caching`. A different objective is a genuinely
different desired plan, so it's correctly treated as a cache miss rather
than an equivalent request to the same scope.

## Using it

From the Streamlit dashboard, an "Optimization objective" selectbox sets
this field directly for the run about to execute — see
{doc}`../interfaces/streamlit-dashboard`. From a script or a future API
call, set it directly on the `PlanningRequest`:

```python
request = PlanningRequest(
    store_ids=[1, 2],
    optimization_objective="maximize_service_level",
)
```
