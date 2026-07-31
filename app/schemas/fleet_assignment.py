from pydantic import BaseModel


class AssignedLine(BaseModel):
    terminal_id: int
    store_id: int
    product_id: int
    quantity: int
    # None if unassignable (no available vehicle at the terminal could carry it alone).
    vehicle_id: int | None
    unassignable: bool


class VehicleLoad(BaseModel):
    vehicle_id: int
    terminal_id: int
    lines: list[AssignedLine]
    total_weight: float
    total_volume: float
    capacity_weight: float
    capacity_volume: float


class ScenarioFleetAssignment(BaseModel):
    strategy: str
    vehicle_loads: list[VehicleLoad]
    # Lines whose weight/volume alone exceed every available vehicle's capacity at
    # that terminal - no splitting a single line across multiple vehicles in this
    # version, a documented limitation, not a silent drop.
    unassigned_lines: list[AssignedLine]


class FleetAssignmentResult(BaseModel):
    scenario_assignments: list[ScenarioFleetAssignment]
    # True if only Constraint Validation's single best-effort scenario was
    # processed (mirrors DecisionReviewResult.fell_back_to_invalid_scenario).
    fell_back: bool
