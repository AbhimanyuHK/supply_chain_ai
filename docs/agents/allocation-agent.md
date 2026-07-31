# Allocation Agent

The fifth node (`plan_supply → allocate → ...`), implemented in
`app/agents/allocation_agent.py`. The **second** node to call a reasoning
engine, via its own cached `with_structured_output` client.

## Why this agent exists

Supply Planning generated candidate plans *independently* per shortage —
it has no visibility into two different stores' shortages both wanting
the same scarce terminal stock. This agent resolves that by building
three complete, mutually-exclusive allocation scenarios, each respecting
shared terminal stock as a real constraint:

- **`priority_first`** — highest-priority stores (lowest `priority`
  number) drain shared stock first, in order, each taking its
  best-scored Supply Planning candidate first.
- **`score_first`** — globally greedy by Supply Planning's candidate
  score across *all* shortages at once, ignoring store priority entirely.
  A baseline for comparison against the other two.
- **`balanced`** — when multiple shortages contest the same `(terminal,
  product)` stock and it can't cover all of them, splits it
  proportionally to each shortage's size rather than letting
  first-come-first-served starve the rest.

These three directly answer the spec's own allocation questions — "Should
high-priority stores receive inventory first?" (`priority_first`),
"Should inventory be split across multiple terminals?" (`balanced`).

## Deterministic math, not LLM math

All three strategies (`_priority_first_lines`, `_score_first_lines`,
`_balanced_lines`) are plain Python functions that track remaining stock
per `(terminal, product)` and never over-allocate it. Conserving scarce
stock across many shipment lines without ever going negative is exactly
the kind of exact, multi-step arithmetic LLMs are unreliable at — so it
isn't delegated to one, applying the same "LLM judges, code decides"
principle at scenario granularity that Supply Planning applies at the
per-candidate level.

Quantities are capped with `math.ceil(shortage_qty)` per shortage (you
can't ship a fractional unit), which is why `fulfillment_rate` can read
slightly over 100% for a scenario — expected, not a bug.

## The LLM's one job here

Rank the three finished scenario summaries (fulfillment rate, total cost,
high-priority-shortages-fulfilled count) best-to-worst with a rationale
per scenario — comparing already-finished proposals, never computing
them.

Zero shortages produces zero scenarios and zero LLM calls — the same
short-circuit pattern used in Supply Planning.

## Scope boundary

This agent ranks scenarios. It doesn't pick one to run with (that's the
{doc}`Decision Review Agent <decision-review-agent>`, after
{doc}`Cost Optimization <cost-optimization-agent>` and
{doc}`Constraint Validation <constraint-validation-agent>` have had their
say), refine costs beyond the rough per-km proxy, or validate against
business constraints.

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints all three ranked allocation scenarios with rationale and a
recommended strategy.
