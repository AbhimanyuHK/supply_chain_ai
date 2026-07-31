"""Constraint Validation Agent — seventh LangGraph node, and the first with a
feedback loop.

Validates all three of Modules 6/7's allocation scenarios against real
constraints, then decides what carries forward:
  1. If Cost Optimization's recommended scenario is valid, use it.
  2. Else, if a *different* already-generated scenario happens to be valid,
     switch to the cheapest valid one rather than replanning from scratch.
  3. Else, send the violations back to the Supply Planning Agent for another
     attempt (up to `max_replanning_attempts`) — see
     `supply_planning_agent.py`'s handling of `state["constraint_validation"]`.
  4. Else (attempts exhausted), proceed best-effort with the recommended
     scenario, recording the unresolved violations (also appended to
     `state["errors"]`) for a future Exception Handling Agent.

Constraints implemented, grounded in real fields:
  - available_inventory: per (terminal, product), summed outbound quantity
    across all lines in a scenario must not exceed the terminal's actual
    available_qty.
  - store_capacity: per store, (current on-hand across all its products) +
    (incoming quantity from this scenario) must not exceed Store.capacity.
  - terminal_capacity: a terminal's current total on-hand (across all
    products) must not already exceed Terminal.capacity. In this
    outbound-only workflow shipping can only reduce a terminal's total, so
    this is a data-integrity check (catches a terminal that was already
    over capacity) rather than something a shipment itself could trigger.
  - lead_time / delivery_window: the spec lists these as separate
    constraints, but nothing in the data model distinguishes a "delivery
    window" from delivery time itself (no store operating-hours or delivery
    slot data exists), so both collapse into one check: estimated delivery
    time must not exceed `business_rules.max_lead_time_days`.
  - max_shipment_qty / min_shipment_qty: each line's quantity must fall
    within `business_rules.max_shipment_qty_per_product` /
    `min_shipment_qty` (Supply Planning only asks the LLM to respect these,
    it doesn't hard-clamp them — this is the actual enforcement point).
  - business_priority: a scenario is flagged if it doesn't fully satisfy
    every high-priority store's shortage.

Constraints explicitly NOT implemented, and why:
  - safety_stock: Module 4's shortage/reorder-point math is already exactly
    "how far below safety stock is this store," which is *why* a shipment
    exists at all. A second, separate "safety stock" check here would
    either restate that math or invent an unrelated threshold - neither is
    a real, distinct constraint given the current data model.
  - product_restrictions: no field anywhere (Product, Store, or otherwise)
    encodes which products can/can't ship to which stores. Nothing to check.
"""

from collections import defaultdict

from loguru import logger

from app.agents.state import PlanningState
from app.core.config import get_settings
from app.models.entities import LocationType
from app.schemas.allocation import AllocationScenario
from app.schemas.constraint_validation import (
    ConstraintValidationResult,
    ConstraintViolation,
    ScenarioValidation,
)
from app.schemas.cost_optimization import ScenarioCostSummary
from app.schemas.inventory_analysis import InventoryAnalysisRecord
from app.schemas.planning import MasterDataSnapshot


def _validate_scenario(
    scenario: AllocationScenario,
    cost_summary: ScenarioCostSummary,
    snapshot: MasterDataSnapshot,
    inventory_records: list[InventoryAnalysisRecord],
) -> ScenarioValidation:
    business_rules = snapshot.business_rules
    violations: list[ConstraintViolation] = []

    for line in scenario.lines:
        if line.quantity > business_rules.max_shipment_qty_per_product:
            violations.append(
                ConstraintViolation(
                    constraint="max_shipment_qty",
                    terminal_id=line.terminal_id,
                    store_id=line.store_id,
                    product_id=line.product_id,
                    message=(
                        f"Quantity {line.quantity} exceeds max_shipment_qty_per_product "
                        f"({business_rules.max_shipment_qty_per_product})."
                    ),
                )
            )
        if line.quantity < business_rules.min_shipment_qty:
            violations.append(
                ConstraintViolation(
                    constraint="min_shipment_qty",
                    terminal_id=line.terminal_id,
                    store_id=line.store_id,
                    product_id=line.product_id,
                    message=f"Quantity {line.quantity} is below min_shipment_qty ({business_rules.min_shipment_qty}).",
                )
            )
        max_hours = business_rules.max_lead_time_days * 24
        if line.estimated_delivery_hours > max_hours:
            violations.append(
                ConstraintViolation(
                    constraint="lead_time",
                    terminal_id=line.terminal_id,
                    store_id=line.store_id,
                    product_id=line.product_id,
                    message=(
                        f"Delivery time {line.estimated_delivery_hours:.1f}h exceeds max_lead_time_days "
                        f"({business_rules.max_lead_time_days}d = {max_hours}h)."
                    ),
                )
            )

    terminal_available = {
        (inv.location_id, inv.product_id): inv.available_qty
        for inv in snapshot.inventory
        if inv.location_type == LocationType.TERMINAL
    }
    outbound_by_terminal_product: dict[tuple[int, int], int] = defaultdict(int)
    for line in scenario.lines:
        outbound_by_terminal_product[(line.terminal_id, line.product_id)] += line.quantity
    for (terminal_id, product_id), total_qty in outbound_by_terminal_product.items():
        available = terminal_available.get((terminal_id, product_id), 0)
        if total_qty > available:
            violations.append(
                ConstraintViolation(
                    constraint="available_inventory",
                    terminal_id=terminal_id,
                    product_id=product_id,
                    message=(
                        f"Total outbound quantity {total_qty} exceeds terminal {terminal_id}'s available "
                        f"stock ({available}) for product {product_id}."
                    ),
                )
            )

    on_hand_by_store: dict[int, int] = defaultdict(int)
    for record in inventory_records:
        if record.location_type == LocationType.STORE:
            on_hand_by_store[record.location_id] += record.on_hand_qty
    incoming_by_store: dict[int, int] = defaultdict(int)
    for line in scenario.lines:
        incoming_by_store[line.store_id] += line.quantity
    store_capacity_by_id = {s.store_id: s.capacity for s in snapshot.stores}
    for store_id, incoming_qty in incoming_by_store.items():
        capacity = store_capacity_by_id.get(store_id)
        if capacity is None:
            continue
        projected = on_hand_by_store.get(store_id, 0) + incoming_qty
        if projected > capacity:
            violations.append(
                ConstraintViolation(
                    constraint="store_capacity",
                    store_id=store_id,
                    message=(
                        f"Projected on-hand quantity {projected} would exceed store {store_id}'s "
                        f"capacity ({capacity})."
                    ),
                )
            )

    on_hand_by_terminal: dict[int, int] = defaultdict(int)
    for record in inventory_records:
        if record.location_type == LocationType.TERMINAL:
            on_hand_by_terminal[record.location_id] += record.on_hand_qty
    terminal_capacity_by_id = {t.terminal_id: t.capacity for t in snapshot.terminals}
    for terminal_id in {line.terminal_id for line in scenario.lines}:
        capacity = terminal_capacity_by_id.get(terminal_id)
        if capacity is None:
            continue
        current_total = on_hand_by_terminal.get(terminal_id, 0)
        if current_total > capacity:
            violations.append(
                ConstraintViolation(
                    constraint="terminal_capacity",
                    terminal_id=terminal_id,
                    message=(
                        f"Terminal {terminal_id}'s current total inventory ({current_total}) already "
                        f"exceeds its capacity ({capacity})."
                    ),
                )
            )

    if not cost_summary.fully_satisfies_high_priority:
        violations.append(
            ConstraintViolation(
                constraint="business_priority",
                message=(
                    f"Only {cost_summary.high_priority_shortages_fulfilled}/"
                    f"{cost_summary.high_priority_shortages_total} high-priority shortages are fully covered."
                ),
            )
        )

    return ScenarioValidation(strategy=scenario.strategy, violations=violations, is_valid=not violations)


async def validate_constraints_node(state: PlanningState) -> dict:
    allocation = state["allocation"]
    cost_optimization = state["cost_optimization"]

    if not allocation.scenarios:
        message = "No allocation scenarios to validate - skipped"
        logger.info(message)
        result = ConstraintValidationResult(
            scenario_validations=[], final_strategy=None, unresolved_violations=[], replanning_triggered=False
        )
        return {"constraint_validation": result, "trace": [message]}

    snapshot = state["master_data"]
    inventory_records = state["inventory_analysis"].records
    cost_by_strategy = {s.strategy: s for s in cost_optimization.scenarios}
    cost_lookup = {s.strategy: s.total_cost for s in cost_optimization.scenarios}

    scenario_validations = [
        _validate_scenario(scenario, cost_by_strategy[scenario.strategy], snapshot, inventory_records)
        for scenario in allocation.scenarios
        if scenario.strategy in cost_by_strategy
    ]
    validation_by_strategy = {v.strategy: v for v in scenario_validations}

    recommended = cost_optimization.recommended_strategy
    recommended_validation = validation_by_strategy.get(recommended) if recommended else None
    replanning_attempts = state.get("replanning_attempts", 0)
    settings = get_settings()

    if recommended_validation is not None and recommended_validation.is_valid:
        final_strategy = recommended
        unresolved: list[ConstraintViolation] = []
        replanning_triggered = False
        message = f"'{recommended}' passed constraint validation; carrying it forward."
    else:
        valid_alternatives = [v for v in scenario_validations if v.is_valid and v.strategy != recommended]
        if valid_alternatives:
            best_alternative = min(valid_alternatives, key=lambda v: cost_lookup.get(v.strategy, float("inf")))
            final_strategy = best_alternative.strategy
            unresolved = []
            replanning_triggered = False
            violation_count = len(recommended_validation.violations) if recommended_validation else 0
            message = (
                f"'{recommended}' failed validation ({violation_count} violation(s)); switched to valid "
                f"alternative '{final_strategy}' instead."
            )
        elif replanning_attempts < settings.max_replanning_attempts:
            final_strategy = recommended
            unresolved = recommended_validation.violations if recommended_validation else []
            replanning_triggered = True
            message = (
                f"No scenario passed validation; sending {len(unresolved)} violation(s) back to Supply "
                f"Planning for replanning (attempt {replanning_attempts + 1}/{settings.max_replanning_attempts})."
            )
        else:
            final_strategy = recommended
            unresolved = recommended_validation.violations if recommended_validation else []
            replanning_triggered = False
            message = (
                f"No scenario passed validation after {settings.max_replanning_attempts} replanning "
                f"attempt(s); proceeding best-effort with '{final_strategy}' ({len(unresolved)} unresolved "
                "violation(s))."
            )

    result = ConstraintValidationResult(
        scenario_validations=scenario_validations,
        final_strategy=final_strategy,
        unresolved_violations=unresolved,
        replanning_triggered=replanning_triggered,
    )
    logger.info(message)

    update: dict = {"constraint_validation": result, "trace": [message]}
    if replanning_triggered:
        update["replanning_attempts"] = replanning_attempts + 1
    if unresolved and not replanning_triggered:
        update["errors"] = [
            f"Unresolved constraint violations on final plan '{final_strategy}': "
            + "; ".join(v.message for v in unresolved)
        ]
    return update


def route_after_validation(state: PlanningState) -> str:
    validation = state.get("constraint_validation")
    if validation is None or not validation.replanning_triggered:
        return "end"
    return "replan"
