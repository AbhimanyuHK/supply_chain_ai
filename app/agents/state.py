"""Shared state threaded through the LangGraph planning workflow.

Each agent module (Demand Forecast, Inventory Analysis, Supply Planning, ...)
adds its own field here as it lands, plus a corresponding entry to `trace`.
`trace`/`errors` use the `operator.add` reducer so each node's contribution is
appended rather than overwriting the previous node's.

`replanning_attempts` is a plain (non-reducer) field: the Constraint
Validation Agent explicitly sets its new value each time rather than
accumulating it via a reducer, since it needs to both read and overwrite the
count within the same node.
"""

import operator
from typing import Annotated, TypedDict

from app.schemas.allocation import AllocationResult
from app.schemas.constraint_validation import ConstraintValidationResult
from app.schemas.cost_optimization import CostOptimizationResult
from app.schemas.decision_review import DecisionReviewResult
from app.schemas.final_recommendation import FinalRecommendation
from app.schemas.forecast import DemandForecastResult
from app.schemas.inventory_analysis import InventoryAnalysisResult
from app.schemas.planning import MasterDataSnapshot, PlanningRequest
from app.schemas.supply_planning import SupplyPlanningResult


class PlanningState(TypedDict, total=False):
    request: PlanningRequest
    master_data: MasterDataSnapshot
    demand_forecast: DemandForecastResult
    inventory_analysis: InventoryAnalysisResult
    supply_planning: SupplyPlanningResult
    allocation: AllocationResult
    cost_optimization: CostOptimizationResult
    constraint_validation: ConstraintValidationResult
    decision_review: DecisionReviewResult
    final_recommendation: FinalRecommendation
    replanning_attempts: int
    trace: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
