from pydantic import BaseModel


class ConstraintViolation(BaseModel):
    # One of: available_inventory, store_capacity, terminal_capacity, lead_time,
    # max_shipment_qty, min_shipment_qty, business_priority.
    constraint: str
    terminal_id: int | None = None
    store_id: int | None = None
    product_id: int | None = None
    message: str


class ScenarioValidation(BaseModel):
    strategy: str
    violations: list[ConstraintViolation]
    is_valid: bool


class ConstraintValidationResult(BaseModel):
    scenario_validations: list[ScenarioValidation]
    # The strategy actually carried forward: the recommended one if valid, else the
    # cheapest valid alternative, else the original recommendation best-effort.
    final_strategy: str | None
    unresolved_violations: list[ConstraintViolation]
    replanning_triggered: bool
