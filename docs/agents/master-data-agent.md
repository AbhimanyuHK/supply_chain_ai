# Master Data Agent

The first node (`START → load_master_data → ...`), implemented in
`app/agents/master_data_agent.py`. Pure data loading — no LLM reasoning,
no ML inference.

## What it does

Orchestrates the repository layer (`app/database/repositories/` — one
class per entity, each taking an `AsyncSession` via its constructor) into
a single `MasterDataSnapshot`, scoped to the incoming `PlanningRequest`:
specific store/product ids if given, or everything if unset; a *trailing
window* of demand history (`demand_history_window_days`) rather than full
history. This scoping matters directly at the platform's target scale —
a single planning run should never need to load millions of inventory
rows or years of demand history just to plan for five stores.

```{note}
When `request.store_ids` is set, terminals are no longer loaded
unconditionally — they're derived from which terminals actually have a
`distance_matrix` route to one of the scoped stores. See
{doc}`../features/scalability` (Fix 1) for the full reasoning and why this
is behavior-preserving, not just faster.
```

## Business rules

The original spec lists "Business Rules" as a category of master data to
load, but defines no database table for it. Rather than force business
rules into a schema that doesn't fit them well, they live in
`config/business_rules.yaml` + `app/core/business_rules.py` instead —
editable without a code change or a migration. See
{doc}`../operations/business-rules` for every field.

## Memoization within one run

`load_master_data_node` checks `state.get("master_data")` first: if
`run_planning_workflow` already loaded the snapshot standalone (to compute
the {doc}`idempotency fingerprint <../features/idempotency-and-caching>`
before deciding whether to run the graph at all), the node reuses it
instead of querying the database a second time — while still emitting its
normal trace line, so the graph's trace length stays consistent whether or
not this shortcut fired.

## `PlanningState`

`app/agents/state.py` defines the `TypedDict` this and every other node
reads from and writes to — see {doc}`../architecture/planning-workflow`
for the full shape, including the `trace`/`errors` accumulator fields
every node appends to via LangGraph's `operator.add` reducer.

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints the loaded snapshot summary (row counts per entity) before moving
on to the Demand Forecast agent's output.
