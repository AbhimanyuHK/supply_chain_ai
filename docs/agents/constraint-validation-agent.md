# Constraint Validation Agent

The seventh node, and **the first with a feedback loop**
(`optimize_cost → validate_constraints →` either `review_decision` or back
to `plan_supply`, via `graph.add_conditional_edges(...,
route_after_validation)`). Implemented in
`app/agents/constraint_validation_agent.py`. No LLM call — validation
against real data plus a deterministic decision tree, not a judgment call.

## Decision tree

Evaluated after validating all three scenarios (`validate_constraints_node`):

1. Cost Optimization's recommended scenario is valid → carry it forward
   as-is.
2. It isn't, but a *different* already-generated scenario is valid →
   switch to the cheapest valid alternative. No replanning needed — one
   of the three already worked.
3. None are valid, and `replanning_attempts < Settings.max_replanning_attempts`
   (default 2) → route back to `plan_supply` with the violations attached
   to `state["constraint_validation"]`, incrementing
   `replanning_attempts`.
4. None are valid and attempts are exhausted → proceed best-effort with
   the recommended scenario, append the unresolved violations to
   `state["errors"]`, and set them on the result for a future Exception
   Handling agent (Phase 2, not yet built) to pick up.

## Closing the loop

`supply_planning_agent.py`'s `_prior_violation_messages_by_shortage`
reads `state["constraint_validation"]` on the next pass through Supply
Planning, groups violation messages by `(store_id, product_id)`, and folds
them into that shortage's next prompt. See
{doc}`supply-planning-agent` for the other side of this loop — without it,
a retry would just re-ask the identical question.

## Constraints implemented

Every constraint here is grounded in a real field — nothing is invented:

| Constraint | Rule |
|---|---|
| `available_inventory` | Per `(terminal, product)`, summed outbound quantity across all lines in a scenario must not exceed the terminal's real `available_qty`. |
| `store_capacity` / `terminal_capacity` | `Store.capacity`/`Terminal.capacity` are used directly — current total on-hand plus incoming must not exceed a store's capacity; a terminal's current total on-hand must not already exceed its own capacity (in this outbound-only flow, this is really a data-integrity check, since shipping can only reduce a terminal's total). |
| `lead_time` (also covers "delivery window") | The spec lists these as two constraints, but nothing in the data model distinguishes a delivery window from delivery time itself, so they collapse into one check against `business_rules.max_lead_time_days` — a hard cap, distinct from `default_lead_time_days` (Cost Optimization's soft/target threshold for delay penalties). |
| `max_shipment_qty` / `min_shipment_qty` | Supply Planning only *asks* the LLM to respect these in its prompt — it never hard-clamps them. This is the actual enforcement point. |
| `business_priority` | Flags a scenario that doesn't fully satisfy every high-priority store's shortage. |

## Constraints explicitly not implemented, and why

- **`safety_stock`** — Inventory Analysis's shortage/reorder-point math
  already *is* "how far below safety stock is this store," which is the
  reason the shipment exists at all. A second, separate check here would
  either restate that math or invent an unrelated threshold; neither is a
  genuine additional constraint given the current data model.
- **`product_restrictions`** — no field anywhere (`Product`, `Store`, or
  otherwise) encodes which products can or can't ship to which stores.
  There is nothing to check.

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints each scenario's validation status, any violations, the final
strategy chosen, and how many replanning attempts were used.
