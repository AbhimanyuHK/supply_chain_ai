"""Authenticated observed-outcome ingestion and forecast calibration."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.decisions import require_operator
from app.database.session import get_db
from app.models.entities import PlanningOutcome, PlanningRun
from app.services.outcome_evaluation import (
    conformal_margin, interval_diagnostics, outcome_summary,
)

router = APIRouter(prefix="/outcomes", tags=["outcomes"], dependencies=[Depends(require_operator)])


class OutcomeInput(BaseModel):
    external_reference: str = Field(min_length=1, max_length=128)
    planning_run_id: int = Field(gt=0)
    store_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    observation_date: date
    actual_demand_qty: float = Field(ge=0, allow_inf_nan=False)
    fulfilled_qty: float = Field(ge=0, allow_inf_nan=False)
    actual_cost: float = Field(ge=0, allow_inf_nan=False)


@router.post("")
async def ingest_outcome(body: OutcomeInput, db: AsyncSession = Depends(get_db)):
    if body.fulfilled_qty > body.actual_demand_qty:
        raise HTTPException(422, "fulfilled_qty cannot exceed actual_demand_qty")
    run = await db.get(PlanningRun, body.planning_run_id)
    if run is None:
        raise HTTPException(404, "Planning run not found")
    previous = await db.scalar(
        select(PlanningOutcome).where(PlanningOutcome.external_reference == body.external_reference)
    )
    if previous:
        raise HTTPException(409, "Outcome reference already ingested")
    db.add(PlanningOutcome(**body.model_dump()))
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Outcome duplicate or invalid reference") from exc
    return {"external_reference": body.external_reference, "status": "recorded"}


@router.get("/planning-runs/{run_id}/evaluation")
async def evaluate_outcomes(run_id: int, alpha: float = 0.1, db: AsyncSession = Depends(get_db)):
    if not 0 < alpha < 1:
        raise HTTPException(422, "alpha must be between 0 and 1")
    run = await db.get(PlanningRun, run_id)
    if run is None:
        raise HTTPException(404, "Planning run not found")
    rows = (await db.scalars(
        select(PlanningOutcome).where(PlanningOutcome.planning_run_id == run_id)
        .order_by(PlanningOutcome.observation_date, PlanningOutcome.id)
    )).all()
    observed = [
        {
            "store_id": row.store_id, "product_id": row.product_id,
            "observation_date": row.observation_date.isoformat(),
            "actual_demand_qty": float(row.actual_demand_qty),
            "fulfilled_qty": float(row.fulfilled_qty),
            "actual_cost": float(row.actual_cost),
        }
        for row in rows
    ]
    forecasts = (run.demand_forecast or {}).get("forecasts", [])
    diagnostics = interval_diagnostics(forecasts, observed)
    margin = conformal_margin(diagnostics.pop("interval_miss_residuals"), alpha)
    recommendation = run.final_recommendation or {}
    summary = outcome_summary(observed)
    expected_cost = recommendation.get("expected_total_cost")
    summary["expected_total_cost"] = expected_cost
    summary["actual_minus_expected_cost"] = (
        summary["actual_cost"] - float(expected_cost)
        if expected_cost is not None and observed else None
    )
    return {
        "run_id": run_id, "outcome": summary, "forecast": diagnostics,
        "conformal_alpha": alpha, "calibration_margin": margin,
        "note": "In-sample diagnostic only. Use held-out historical runs for valid forward calibration.",
    }
