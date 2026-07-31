# Business Rules

The original spec lists "Business Rules" as a category of master data to
load, but defines no database table for it. Rather than force it into a
schema that doesn't fit, business rules live in a plain, editable config
file — `config/business_rules.yaml` — loaded by `app/core/business_rules.py`'s
`get_business_rules()` (process-wide `@lru_cache`'d, same pattern as
`Settings`).

## Why a YAML file instead of a database table

Business rules are cross-run policy — the same for every planning
request — not per-run scope data, so a table with rows keyed by
"planning request" wouldn't make sense. And unlike per-run choices such
as {doc}`the optimization objective <../features/cost-objectives>`, they
genuinely are global, so a file editable without a code change or a
migration is the right fit.

## Every field

```{list-table}
:header-rows: 1

* - Field
  - Default
  - Used by
* - `default_safety_stock_days`
  - `7`
  - {doc}`../agents/inventory-analysis-agent` (safety stock), {doc}`../agents/cost-optimization-agent` (holding cost period)
* - `default_lead_time_days`
  - `2`
  - {doc}`../agents/inventory-analysis-agent` (reorder point), {doc}`../agents/cost-optimization-agent` (delay penalty threshold — soft/target)
* - `min_shipment_qty`
  - `1`
  - {doc}`../agents/supply-planning-agent` (prompted, not hard-clamped — enforced by {doc}`../agents/constraint-validation-agent`)
* - `max_shipment_qty_per_product`
  - `5000`
  - Same as above
* - `reorder_point_multiplier`
  - `1.5`
  - {doc}`../agents/inventory-analysis-agent`'s reorder point formula
* - `high_priority_store_threshold`
  - `2`
  - Stores with `priority <= this` count as high-priority for coverage checks
* - `estimated_transport_cost_per_km`
  - `50.0`
  - {doc}`../agents/supply-planning-agent`/{doc}`../agents/allocation-agent`'s rough cost proxy; {doc}`../agents/cost-optimization-agent`'s fallback when a terminal has no fleet
* - `warehouse_handling_cost_per_unit`
  - `5.0`
  - {doc}`../agents/cost-optimization-agent` — combined loading + unloading (the data model doesn't separate them)
* - `inventory_holding_cost_rate`
  - `0.0005`
  - {doc}`../agents/cost-optimization-agent` — fraction of unit cost per day
* - `delay_penalty_per_hour`
  - `20.0`
  - {doc}`../agents/cost-optimization-agent` — applied only past `default_lead_time_days`
* - `max_lead_time_days`
  - `5`
  - {doc}`../agents/constraint-validation-agent` — a **hard cap**, distinct from `default_lead_time_days`'s soft/target threshold. Exceeding this rejects a plan outright; exceeding the soft threshold only adds a cost penalty.
```

## Editing

Change `config/business_rules.yaml` directly and restart whichever
process reads it — like `Settings`, `get_business_rules()` is
process-wide cached, so a running process won't pick up a mid-session
edit.

```yaml
default_safety_stock_days: 7
default_lead_time_days: 2
min_shipment_qty: 1
max_shipment_qty_per_product: 5000
reorder_point_multiplier: 1.5
high_priority_store_threshold: 2
estimated_transport_cost_per_km: 50.0
warehouse_handling_cost_per_unit: 5.0
inventory_holding_cost_rate: 0.0005
delay_penalty_per_hour: 20.0
max_lead_time_days: 5
```
