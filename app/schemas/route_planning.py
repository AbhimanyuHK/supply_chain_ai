from pydantic import BaseModel


class RouteStop(BaseModel):
    sequence: int
    store_id: int
    # This stop's own terminal->store DistanceMatrix values - no store-to-store
    # distance data exists anywhere in this platform's data model, so a route's
    # total distance below is the sum of these, not a true multi-leg route length.
    distance_km: float
    travel_time_hours: float


class VehicleRoute(BaseModel):
    vehicle_id: int
    terminal_id: int
    # Ordered nearest-terminal-distance-first, deduplicated to one stop per store.
    stops: list[RouteStop]
    total_route_distance_km: float
    # vehicle.fixed_cost counted ONCE per vehicle (not per line) + cost_per_km *
    # total_route_distance_km - corrects Cost Optimization's per-line proxy, which
    # double-counts fixed cost when several lines actually share one vehicle trip.
    # This is additional informational detail; it does not retroactively change
    # ScenarioCostSummary.total_cost, which already drove scenario selection
    # earlier in the pipeline.
    route_transportation_cost: float


class ScenarioRoutePlan(BaseModel):
    strategy: str
    vehicle_routes: list[VehicleRoute]


class RoutePlanningResult(BaseModel):
    scenario_routes: list[ScenarioRoutePlan]
