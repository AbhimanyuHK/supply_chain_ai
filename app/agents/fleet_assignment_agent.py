"""Fleet Assignment Agent — first of three new Phase 2 nodes, gated behind
`Settings.fleet_module_enabled` (default `False`). Sits between Constraint
Validation and Route Planning: `validate_constraints -> assign_fleet ->
plan_route -> predict_eta -> review_decision`.

No LLM call: like Cost Optimization, this is bin-packing — an optimization
problem with an objectively better/worse answer from real data, not a
judgment call.

Cost Optimization already picks a vehicle *per line, independently* purely to
produce a costing estimate for scenario selection — it never checks whether
several lines assigned the same vehicle would actually fit together. This
agent does the real, binding, capacity-respecting assignment: for every
constraint-valid scenario, lines sharing a source terminal are grouped and
packed onto the fewest vehicles that can carry them (first-fit-decreasing by
weight), so its `vehicle_id` per line is authoritative and may legitimately
disagree with Cost Optimization's per-line proxy pick.

This agent is strictly read-only against `snapshot.fleet` — it never writes
back to `Fleet.status` (no such repository method exists, deliberately: an
"available" vehicle here is available for *planning* purposes, not reserved
for dispatch, which would be a real operational side effect belonging to a
future execution-tracking system, not this one-shot planning workflow).

A line whose weight or volume alone exceeds every available vehicle's
capacity at its terminal is flagged `unassignable` rather than split across
multiple vehicles — a documented limitation, not a silent drop.
"""

from collections import defaultdict

from loguru import logger

from app.agents.scenario_selection import select_reviewable_scenarios
from app.agents.state import PlanningState
from app.agents.llm_fleet_optimizer import propose_fleet_plan
from app.core.config import get_settings
from app.models.entities import VehicleStatus
from app.schemas.allocation import AllocationLine, AllocationScenario
from app.schemas.fleet_assignment import (
    AssignedLine,
    FleetAssignmentResult,
    ScenarioFleetAssignment,
    VehicleLoad,
)
from app.schemas.planning import MasterDataSnapshot


def _bin_pack_terminal_group(
    lines: list[AllocationLine], terminal_id: int, snapshot: MasterDataSnapshot
) -> tuple[list[VehicleLoad], list[AssignedLine]]:
    available = [
        f for f in snapshot.fleet if f.terminal_id == terminal_id and f.status == VehicleStatus.AVAILABLE
    ]
    product_by_id = {p.product_id: p for p in snapshot.products}

    def weight_of(line: AllocationLine) -> float:
        return float(product_by_id[line.product_id].weight) * line.quantity

    def volume_of(line: AllocationLine) -> float:
        return float(product_by_id[line.product_id].volume) * line.quantity

    sorted_lines = sorted(lines, key=weight_of, reverse=True)

    loads: list[VehicleLoad] = []
    used_vehicle_ids: set[int] = set()
    unassigned: list[AssignedLine] = []

    for line in sorted_lines:
        line_weight = weight_of(line)
        line_volume = volume_of(line)

        target = next(
            (
                load
                for load in loads
                if load.total_weight + line_weight <= load.capacity_weight
                and load.total_volume + line_volume <= load.capacity_volume
            ),
            None,
        )

        if target is None:
            candidate = next(
                (
                    f
                    for f in available
                    if f.vehicle_id not in used_vehicle_ids
                    and float(f.capacity_weight) >= line_weight
                    and float(f.capacity_volume) >= line_volume
                ),
                None,
            )
            if candidate is None:
                unassigned.append(
                    AssignedLine(
                        terminal_id=line.terminal_id, store_id=line.store_id, product_id=line.product_id,
                        quantity=line.quantity, vehicle_id=None, unassignable=True,
                    )
                )
                continue

            used_vehicle_ids.add(candidate.vehicle_id)
            target = VehicleLoad(
                vehicle_id=candidate.vehicle_id, terminal_id=terminal_id, lines=[],
                total_weight=0.0, total_volume=0.0,
                capacity_weight=float(candidate.capacity_weight), capacity_volume=float(candidate.capacity_volume),
            )
            loads.append(target)

        target.lines.append(
            AssignedLine(
                terminal_id=line.terminal_id, store_id=line.store_id, product_id=line.product_id,
                quantity=line.quantity, vehicle_id=target.vehicle_id, unassignable=False,
            )
        )
        target.total_weight += line_weight
        target.total_volume += line_volume

    return loads, unassigned


def _assign_scenario(scenario: AllocationScenario, snapshot: MasterDataSnapshot) -> ScenarioFleetAssignment:
    lines_by_terminal: dict[int, list[AllocationLine]] = defaultdict(list)
    for line in scenario.lines:
        lines_by_terminal[line.terminal_id].append(line)

    all_loads: list[VehicleLoad] = []
    all_unassigned: list[AssignedLine] = []
    for terminal_id, terminal_lines in lines_by_terminal.items():
        loads, unassigned = _bin_pack_terminal_group(terminal_lines, terminal_id, snapshot)
        all_loads.extend(loads)
        all_unassigned.extend(unassigned)

    return ScenarioFleetAssignment(strategy=scenario.strategy, vehicle_loads=all_loads, unassigned_lines=all_unassigned)


async def assign_fleet_node(state: PlanningState) -> dict:
    allocation = state["allocation"]

    if not allocation.scenarios:
        message = "No scenarios to assign fleet - skipped"
        logger.info(message)
        result = FleetAssignmentResult(scenario_assignments=[], fell_back=False)
        return {"fleet_assignment": result, "trace": [message]}

    scenarios, fell_back = select_reviewable_scenarios(allocation, state["constraint_validation"])
    snapshot = state["master_data"]

    scenario_assignments = []
    for scenario in scenarios:
        assignment = _assign_scenario(scenario, snapshot)
        if get_settings().llm_native_optimizer_enabled and scenario.lines:
            try:
                proposed = await propose_fleet_plan(scenario.lines, snapshot.fleet, snapshot.products)
                if proposed is not None:
                    vehicles = {v.vehicle_id: v for v in snapshot.fleet}
                    products = {p.product_id: p for p in snapshot.products}
                    loads = {}
                    for index, line in enumerate(scenario.lines):
                        vehicle = vehicles[proposed[index]]
                        if vehicle.vehicle_id not in loads:
                            loads[vehicle.vehicle_id] = VehicleLoad(
                                vehicle_id=vehicle.vehicle_id, terminal_id=vehicle.terminal_id,
                                lines=[], total_weight=0.0, total_volume=0.0,
                                capacity_weight=float(vehicle.capacity_weight),
                                capacity_volume=float(vehicle.capacity_volume),
                            )
                        load = loads[vehicle.vehicle_id]
                        load.lines.append(AssignedLine(
                            terminal_id=line.terminal_id, store_id=line.store_id,
                            product_id=line.product_id, quantity=line.quantity,
                            vehicle_id=vehicle.vehicle_id, unassignable=False,
                        ))
                        load.total_weight += float(products[line.product_id].weight) * line.quantity
                        load.total_volume += float(products[line.product_id].volume) * line.quantity
                    candidate = ScenarioFleetAssignment(
                        strategy=scenario.strategy, vehicle_loads=list(loads.values()), unassigned_lines=[]
                    )
                    if (assignment.unassigned_lines
                            or len(candidate.vehicle_loads) < len(assignment.vehicle_loads)):
                        assignment = candidate
            except Exception as exc:
                logger.warning("LLM fleet proposal failed; using baseline: {}", exc)
        scenario_assignments.append(assignment)
    total_unassigned = sum(len(sa.unassigned_lines) for sa in scenario_assignments)

    message = (
        f"Assigned fleet for {len(scenario_assignments)} scenario(s) "
        f"({total_unassigned} line(s) unassignable)"
    )
    logger.info(message)

    result = FleetAssignmentResult(scenario_assignments=scenario_assignments, fell_back=fell_back)
    return {"fleet_assignment": result, "trace": [message]}
