# Inventory Analysis Agent

The third node (`forecast_demand → analyze_inventory → ...`), implemented
in `app/agents/inventory_analysis_agent.py`. No LLM call — pure
arithmetic against real inventory and forecast data.

## What every location gets

For every `(location, product)` row in the master data snapshot, this
agent reports the raw picture regardless of location type: `on_hand_qty`
(`available + reserved + damaged`), `available_qty`, `reserved_qty`,
`incoming_qty`, `damaged_qty`.

## Shortage math — stores only

Safety stock, reorder point, and shortage quantity are computed **only
for store locations**, using the Demand Forecast agent's output as the
demand signal:

```text
avg_daily_demand = mean(forecast.median values over the horizon)
safety_stock     = avg_daily_demand * business_rules.default_safety_stock_days
reorder_point    = avg_daily_demand * default_lead_time_days
                    * reorder_point_multiplier + safety_stock
shortage_qty     = max(0, reorder_point - (available_qty + incoming_qty))
```

Store/product pairs with no forecast (e.g. a brand-new product with no
sales history at all) get `avg_daily_demand=None` and no shortage math
computed — never a guessed value standing in for missing data.

### Why not terminals too

Terminals don't sell to consumers, so they have no demand forecast of
their own. A terminal's real "demand" is the sum of the stores it
supplies — computing that is the {doc}`Allocation Agent <allocation-agent>`'s
job, once shortages exist to allocate against, not this agent's.
Applying the store formula to a terminal directly would mean inventing a
number nothing in the data actually backs.

## Output

`InventoryAnalysisResult.shortages` is a convenience subset — every
record with `shortage_qty > 0` — which the
{doc}`Supply Planning Agent <supply-planning-agent>` consumes directly as
its unit of work.

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints the inventory picture per location plus the identified shortage
list, before Supply Planning attempts to resolve them.
