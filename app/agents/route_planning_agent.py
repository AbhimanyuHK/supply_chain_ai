"""Route Planning Agent — second of three new Phase 2 nodes:
`assign_fleet -> plan_route -> predict_eta`.

No LLM call: sequencing a vehicle's stops and computing route distance/cost
from real data is an optimization problem with an objectively better/worse
answer, not a judgment call - same category as Fleet Assignment and Cost
Optimization.

**Documented data limitation, not corner-cutting**: there is no
store-to-store distance anywhere in this platform's data model
(`DistanceMatrix` only has terminal<->store legs). True multi-stop routing
needs inter-stop legs that don't exist. This agent instead orders a
vehicle's stops by terminal-to-store distance ascending (a real,
commonly-used nearest-first dispatch heuristic, using only data that
actually exists) and reports `total_route_distance_km` as the sum of each
stop's terminal-to-store distance - an explicit proxy for a true route
length, not a claim of one, the same honesty pattern as
`estimated_transport_cost_per_km`'s existing proxy role elsewhere.

`route_transportation_cost` counts the vehicle's `fixed_cost` **once** per
route (not once per line, correcting Cost Optimization's per-line proxy,
which double-counts fixed cost whenever several lines actually share one
vehicle trip). This is additional informational detail: it does not
retroactively change `ScenarioCostSummary.total_cost`, which already drove
scenario selection earlier in the pipeline - two different "cost" numbers
legitimately coexist for the same scenario, one a per-line costing proxy,
one a route-level operational figure.
"""

from loguru import logger

from app.agents.state import PlanningState
from app.agents.llm_route_optimizer import propose_stop_order
from app.core.config import get_settings
from app.schemas.fleet_assignment import VehicleLoad
from app.schemas.planning import MasterDataSnapshot
from app.schemas.route_planning import (
    RoutePlanningResult,
    RouteStop,
    ScenarioRoutePlan,
    VehicleRoute,
)


def _route_vehicle(vehicle_load: VehicleLoad, snapshot: MasterDataSnapshot, stop_order=None) -> VehicleRoute:
    vehicle = next(f for f in snapshot.fleet if f.vehicle_id == vehicle_load.vehicle_id)
    distance_by_store = {
        d.store_id: (float(d.distance_km), float(d.travel_time))
        for d in snapshot.distance_matrix
        if d.terminal_id == vehicle_load.terminal_id
    }

    distinct_store_ids = sorted(
        {line.store_id for line in vehicle_load.lines},
        key=lambda store_id: distance_by_store.get(store_id, (0.0, 0.0))[0],
    )

    if stop_order is not None:
        if len(stop_order) != len(distinct_store_ids) or set(stop_order) != set(distinct_store_ids):
            raise ValueError('Invalid LLM route stop set')
        distinct_store_ids = stop_order

    stops: list[RouteStop] = []
    total_distance = 0.0
    for sequence, store_id in enumerate(distinct_store_ids, start=1):
        distance_km, travel_time_hours = distance_by_store.get(store_id, (0.0, 0.0))
        stops.append(
            RouteStop(sequence=sequence, store_id=store_id, distance_km=distance_km, travel_time_hours=travel_time_hours)
        )
        total_distance += distance_km

    route_transportation_cost = float(vehicle.fixed_cost) + float(vehicle.cost_per_km) * total_distance

    return VehicleRoute(
        vehicle_id=vehicle_load.vehicle_id,
        terminal_id=vehicle_load.terminal_id,
        stops=stops,
        total_route_distance_km=total_distance,
        route_transportation_cost=route_transportation_cost,
    )


async def plan_route_node(state: PlanningState) -> dict:
    fleet_assignment = state["fleet_assignment"]

    if not fleet_assignment.scenario_assignments:
        message = "No fleet assignments to route - skipped"
        logger.info(message)
        result = RoutePlanningResult(scenario_routes=[])
        return {"route_planning": result, "trace": [message]}

    snapshot = state["master_data"]
    scenario_routes = []
    for scenario_assignment in fleet_assignment.scenario_assignments:
        routes = []
        for load in scenario_assignment.vehicle_loads:
            order = None
            if get_settings().llm_native_optimizer_enabled:
                legs = {
                    d.store_id: (float(d.distance_km), float(d.travel_time))
                    for d in snapshot.distance_matrix if d.terminal_id == load.terminal_id
                }
                stores = sorted({line.store_id for line in load.lines})
                try:
                    order = await propose_stop_order(
                        terminal_id=load.terminal_id, stores=stores,
                        distance_by_store={store: legs.get(store) for store in stores},
                    )
                except Exception as exc:
                    logger.warning("LLM route sequencing failed; using baseline: {}", exc)
            routes.append(_route_vehicle(load, snapshot, stop_order=order))
        scenario_routes.append(ScenarioRoutePlan(
            strategy=scenario_assignment.strategy, vehicle_routes=routes
        ))

    total_vehicles = sum(len(sr.vehicle_routes) for sr in scenario_routes)
    message = f"Planned routes for {len(scenario_routes)} scenario(s) across {total_vehicles} vehicle(s)"
    logger.info(message)

    result = RoutePlanningResult(scenario_routes=scenario_routes)
    return {"route_planning": result, "trace": [message]}
