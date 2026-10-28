"""Read-only operator metrics for planning and replanning health."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.decisions import require_operator
from app.database.session import get_db
from app.models.entities import PlanningOutcome, PlanningRun, ReplanningEvent

router = APIRouter(prefix="/operations", tags=["operations"], dependencies=[Depends(require_operator)])


@router.get("/summary")
async def operations_summary(db: AsyncSession = Depends(get_db)):
    runs = (await db.execute(
        select(PlanningRun.status, func.count(PlanningRun.id)).group_by(PlanningRun.status)
    )).all()
    events = (await db.execute(
        select(ReplanningEvent.action, func.count(ReplanningEvent.id))
        .group_by(ReplanningEvent.action)
    )).all()
    total_outcomes = await db.scalar(select(func.count(PlanningOutcome.id)))
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)
    stale_processing = await db.scalar(
        select(func.count(ReplanningEvent.id)).where(
            ReplanningEvent.action == "processing",
            ReplanningEvent.processing_started_at < stale_cutoff,
        )
    )
    return {
        "planning_runs": {str(getattr(status, "value", status)): count for status, count in runs},
        "replanning_events": {str(status): count for status, count in events},
        "observed_outcomes": total_outcomes or 0,
        "stale_processing_events_over_60m": stale_processing or 0,
        "requires_attention": bool((stale_processing or 0) > 0 or any(
            status == "failed" and count > 0 for status, count in events
        )),
        "note": "Database counts; not a substitute for distributed traces or worker heartbeats.",
    }
