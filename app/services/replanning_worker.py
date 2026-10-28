"""Opt-in bounded replanning worker. No shipment dispatch."""
import asyncio
import os
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.agents.graph import run_planning_workflow
from app.database.session import AsyncSessionLocal
from app.models.entities import ReplanningEvent
from app.schemas.planning import PlanningRequest


async def process_one(event_id: str) -> str:
    async with AsyncSessionLocal() as db:
        event = await db.scalar(select(ReplanningEvent).where(ReplanningEvent.event_id == event_id))
        if event is None or event.action != "queued" or not event.planning_request:
            return "skipped"
        try:
            request = PlanningRequest.model_validate(event.planning_request)
        except ValueError:
            return "invalid_scope"
        if not request.store_ids or not request.product_ids:
            return "invalid_scope"
        attempt = (event.attempt_count or 0) + 1
        claimed = await db.execute(
            update(ReplanningEvent)
            .where(ReplanningEvent.id == event.id, ReplanningEvent.action == "queued")
            .values(action="processing", processing_started_at=datetime.now(timezone.utc),
                    attempt_count=ReplanningEvent.attempt_count + 1, last_error=None)
        )
        if claimed.rowcount != 1:
            return "claimed_elsewhere"
        event_pk = event.id
        await db.commit()

    error = None
    result = None
    try:
        result = await run_planning_workflow(request, force_rerun=True)
        if result.get("errors") or not result.get("planning_run_id"):
            error = "Planning failed or did not persist"
    except Exception as exc:
        error = str(exc)[:2000]

    async with AsyncSessionLocal() as db:
        values = {"action": "failed", "last_error": error} if error else {
            "action": "processed", "planning_run_id": result["planning_run_id"], "last_error": None
        }
        changed = await db.execute(
            update(ReplanningEvent)
            .where(ReplanningEvent.id == event_pk, ReplanningEvent.action == "processing",
                   ReplanningEvent.attempt_count == attempt)
            .values(**values, processing_started_at=None)
        )
        await db.commit()
        if changed.rowcount != 1:
            return "superseded"
        return "failed" if error else "processed"


async def run_batch(limit: int = 10) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    async with AsyncSessionLocal() as db:
        ids = (await db.scalars(
            select(ReplanningEvent.event_id)
            .where(ReplanningEvent.action == "queued", ReplanningEvent.planning_request.is_not(None))
            .order_by(ReplanningEvent.occurred_at, ReplanningEvent.id).limit(limit)
        )).all()
    outcomes = {}
    for event_id in ids:
        outcomes[event_id] = await process_one(event_id)
    return outcomes


if __name__ == "__main__":
    if os.getenv("ENABLE_REPLANNING_WORKER") != "1":
        raise SystemExit("Set ENABLE_REPLANNING_WORKER=1 to enable execution")
    print(asyncio.run(run_batch()))
