"""The planning-workflow REST surface: trigger a run, browse the audit trail.

`POST /optimize` is synchronous - it directly awaits `run_planning_workflow`
and returns once the full run completes (or hits its idempotency cache).
This is deliberate for now: no task-queue infrastructure exists yet, and at
this platform's current scale a run takes single-digit-to-low-tens-of-seconds,
not minutes. See `docs/features/scalability.md` (Fix 6) for the documented
`BackgroundTasks` + `202` + polling upgrade this can move to later, once a
real need for it shows up (e.g. much larger scopes, or genuine concurrent
request volume) - not built speculatively now.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import run_planning_workflow
from app.core.exceptions import NotFoundError
from app.database.repositories import PlanningRunRepository
from app.database.session import get_db
from app.schemas.api import OptimizeResponse
from app.schemas.planning import PlanningRequest
from app.schemas.planning_run import PlanningRunRead, PlanningRunSummary

router = APIRouter(tags=["planning"])


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize(request: PlanningRequest, force_rerun: bool = False) -> OptimizeResponse:
    """Runs the full 9-node planning workflow for the given scope.

    Idempotent by default (see `app/agents/graph.py`): an identical prior
    scope + data + reasoning engine returns the cached result instantly with
    no new LLM calls. Pass `force_rerun=true` to bypass that.
    """
    state = await run_planning_workflow(request, force_rerun=force_rerun)
    return OptimizeResponse.from_state(state)


@router.get("/planning-runs", response_model=list[PlanningRunSummary])
async def list_planning_runs(
    limit: int = 50, db: AsyncSession = Depends(get_db)
) -> list[PlanningRunSummary]:
    """Recent planning runs across every scope, most recent first."""
    rows = await PlanningRunRepository(db).list_recent(limit)
    return [PlanningRunSummary.model_validate(row) for row in rows]


@router.get("/planning-runs/{run_id}", response_model=PlanningRunRead)
async def get_planning_run(run_id: int, db: AsyncSession = Depends(get_db)) -> PlanningRunRead:
    """One planning run's full audit record, including every stage's output."""
    row = await PlanningRunRepository(db).get_by_id(run_id)
    if row is None:
        raise NotFoundError(f"PlanningRun {run_id} not found", details={"run_id": run_id})
    return PlanningRunRead.model_validate(row)


@router.get("/planning-runs/{run_id}/benchmark")
async def get_planning_benchmark(run_id: int, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Compare LLM and heuristic candidates using persisted run data."""
    from app.schemas.allocation import AllocationResult
    from app.schemas.constraint_validation import ConstraintValidationResult
    from app.services.optimization_evaluator import benchmark_scenarios

    row = await PlanningRunRepository(db).get_by_id(run_id)
    if row is None:
        raise NotFoundError(f"PlanningRun {run_id} not found", details={"run_id": run_id})
    if not row.allocation:
        return []
    allocation = AllocationResult.model_validate(row.allocation)
    validation = ConstraintValidationResult.model_validate(row.constraint_validation) if row.constraint_validation else None
    valid = {
        v.strategy for v in validation.scenario_validations if v.is_valid
    } if validation else set()
    return [
        {
            "strategy": metric.strategy,
            "source": metric.source,
            "feasible": metric.feasible,
            "fulfillment_rate": metric.fulfillment_rate,
            "high_priority_fulfilled": metric.high_priority_fulfilled,
            "estimated_cost": metric.estimated_cost,
            "cost_delta_vs_baseline": metric.cost_delta_vs_baseline,
        }
        for metric in benchmark_scenarios(allocation.scenarios, valid)
    ]


@router.get("/planning-runs/{run_id}/stress-test")
async def get_planning_stress_test(
    run_id: int, multipliers: str = "0.8,1.0,1.2",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run transparent what-if demand stress tests against persisted allocations."""
    from fastapi import HTTPException
    from app.schemas.allocation import AllocationResult
    from app.schemas.inventory_analysis import InventoryAnalysisResult
    from app.services.uncertainty_simulation import stress_test

    row = await PlanningRunRepository(db).get_by_id(run_id)
    if row is None:
        raise NotFoundError(f"PlanningRun {run_id} not found", details={"run_id": run_id})
    if not row.allocation or not row.inventory_analysis:
        return {"run_id": run_id, "scenarios": []}
    try:
        values = tuple(float(value.strip()) for value in multipliers.split(","))
    except ValueError as exc:
        raise HTTPException(422, "multipliers must be comma-separated numbers") from exc
    if not values or len(values) > 10 or any(not (0 < value <= 5) for value in values):
        raise HTTPException(422, "Supply 1-10 demand multipliers between 0 and 5")
    allocation = AllocationResult.model_validate(row.allocation)
    shortages = InventoryAnalysisResult.model_validate(row.inventory_analysis).shortages
    return {
        "run_id": run_id,
        "note": "User-supplied stress multipliers; not calibrated forecast quantiles.",
        "scenarios": [
            {
                "strategy": scenario.strategy,
                "stress": [
                    {
                        "demand_multiplier": item.demand_multiplier,
                        "service_level": item.service_level,
                        "uncovered_units": item.uncovered_units,
                    }
                    for item in stress_test(scenario, shortages, values)
                ],
            }
            for scenario in allocation.scenarios
        ],
    }
