"""Schemas for a persisted `PlanningRun` row (see `app/models/entities.py`) -
the audit-trail record of one `run_planning_workflow()` invocation.

`PlanningRunRead.to_state_dict()` reconstructs a dict shaped exactly like
`app.agents.state.PlanningState`, so a historical run can be handed to
`streamlit_app.py`'s existing render functions with zero changes to them -
they don't know or care whether the data came from a live run or the database.
"""

import datetime

from pydantic import BaseModel, ConfigDict

from app.models.entities import PlanningRunStatus
from app.schemas.allocation import AllocationResult
from app.schemas.constraint_validation import ConstraintValidationResult
from app.schemas.cost_optimization import CostOptimizationResult
from app.schemas.decision_review import DecisionReviewResult
from app.schemas.final_recommendation import FinalRecommendation
from app.schemas.forecast import DemandForecastResult
from app.schemas.inventory_analysis import InventoryAnalysisResult
from app.schemas.planning import MasterDataSnapshot
from app.schemas.supply_planning import SupplyPlanningResult


class PlanningRunSummary(BaseModel):
    """Lightweight fields for a history-list row - no stage payloads."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime.datetime
    planning_date: datetime.date
    store_ids: list[int] | None
    product_ids: list[int] | None
    demand_history_window_days: int
    llm_provider: str
    llm_model: str
    status: PlanningRunStatus
    error_message: str | None
    replanning_attempts: int


class PlanningRunRead(PlanningRunSummary):
    """Full row, 1:1 with the ORM model."""

    scope_key: str
    trace: list[str]
    errors: list[str]
    request_payload: dict | None
    master_data_snapshot: dict | None
    demand_forecast: dict | None
    inventory_analysis: dict | None
    supply_planning: dict | None
    allocation: dict | None
    cost_optimization: dict | None
    constraint_validation: dict | None
    decision_review: dict | None
    final_recommendation: dict | None

    def to_state_dict(self) -> dict:
        """Rebuilds a `PlanningState`-shaped dict from the stored JSON columns.

        Only non-null stage columns are reconstructed (a failed run has no
        stage data beyond scope/provider/error - see `PlanningRun`'s docstring).
        """
        state: dict = {
            "trace": self.trace,
            "errors": self.errors,
            "replanning_attempts": self.replanning_attempts,
        }

        stage_schemas = {
            "master_data": (self.master_data_snapshot, MasterDataSnapshot),
            "demand_forecast": (self.demand_forecast, DemandForecastResult),
            "inventory_analysis": (self.inventory_analysis, InventoryAnalysisResult),
            "supply_planning": (self.supply_planning, SupplyPlanningResult),
            "allocation": (self.allocation, AllocationResult),
            "cost_optimization": (self.cost_optimization, CostOptimizationResult),
            "constraint_validation": (self.constraint_validation, ConstraintValidationResult),
            "decision_review": (self.decision_review, DecisionReviewResult),
            "final_recommendation": (self.final_recommendation, FinalRecommendation),
        }
        for key, (payload, schema) in stage_schemas.items():
            if payload is not None:
                state[key] = schema.model_validate(payload)

        return state
