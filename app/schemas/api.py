"""Response schemas for the REST API layer (`app/api/routers/`).

`OptimizeResponse` mirrors `app.schemas.planning_run.PlanningRunRead`'s
per-stage-optional-field shape, but for the *live*, in-memory `PlanningState`
a fresh `/optimize` call returns - not a row already persisted to the
database. Keeping the same shape means a client sees an identical response
contract whether it just triggered a run or is fetching one historically via
`GET /planning-runs/{id}`.
"""

from pydantic import BaseModel

from app.schemas.allocation import AllocationResult
from app.schemas.constraint_validation import ConstraintValidationResult
from app.schemas.cost_optimization import CostOptimizationResult
from app.schemas.decision_review import DecisionReviewResult
from app.schemas.eta_prediction import ETAPredictionResult
from app.schemas.final_recommendation import FinalRecommendation
from app.schemas.fleet_assignment import FleetAssignmentResult
from app.schemas.forecast import DemandForecastResult
from app.schemas.inventory_analysis import InventoryAnalysisResult
from app.schemas.planning import MasterDataSnapshot
from app.schemas.route_planning import RoutePlanningResult
from app.schemas.supply_planning import SupplyPlanningResult


class OptimizeResponse(BaseModel):
    """The result of one `run_planning_workflow()` invocation.

    Every stage field is optional: a run with no shortages short-circuits
    several downstream stages (see each agent's own module docstring), and
    a `master_data`-only snapshot is possible when
    `Settings.persist_full_master_data_snapshot=False` produced a cache hit
    with no full snapshot stored.
    """

    planning_run_id: int | None
    trace: list[str]
    errors: list[str]
    replanning_attempts: int
    master_data: MasterDataSnapshot | None = None
    demand_forecast: DemandForecastResult | None = None
    inventory_analysis: InventoryAnalysisResult | None = None
    supply_planning: SupplyPlanningResult | None = None
    allocation: AllocationResult | None = None
    cost_optimization: CostOptimizationResult | None = None
    constraint_validation: ConstraintValidationResult | None = None
    # Phase 2 (only populated when Settings.fleet_module_enabled is True):
    fleet_assignment: FleetAssignmentResult | None = None
    route_planning: RoutePlanningResult | None = None
    eta_prediction: ETAPredictionResult | None = None
    decision_review: DecisionReviewResult | None = None
    final_recommendation: FinalRecommendation | None = None

    @classmethod
    def from_state(cls, state: dict) -> "OptimizeResponse":
        return cls(
            planning_run_id=state.get("planning_run_id"),
            trace=state.get("trace", []),
            errors=state.get("errors", []),
            replanning_attempts=state.get("replanning_attempts", 0),
            master_data=state.get("master_data"),
            demand_forecast=state.get("demand_forecast"),
            inventory_analysis=state.get("inventory_analysis"),
            supply_planning=state.get("supply_planning"),
            allocation=state.get("allocation"),
            cost_optimization=state.get("cost_optimization"),
            constraint_validation=state.get("constraint_validation"),
            fleet_assignment=state.get("fleet_assignment"),
            route_planning=state.get("route_planning"),
            eta_prediction=state.get("eta_prediction"),
            decision_review=state.get("decision_review"),
            final_recommendation=state.get("final_recommendation"),
        )
