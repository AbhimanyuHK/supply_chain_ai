"""Authenticated planning approvals and event intake.

Approvals are auditable decisions only; they do not dispatch shipments.
Events are durably recorded and marked for replanning; a worker must execute
the actual run with a scope-specific PlanningRequest.
"""
import os
import secrets
from datetime import timezone
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.models.entities import PlanApproval, PlanningRun, ReplanningEvent
from app.services.replanning_events import SupplyChainEvent, should_replan

router = APIRouter(prefix="/decisions", tags=["decisions"])


def require_operator(x_operator_token: str | None = Header(default=None)):
    secret = os.getenv("SUPPLY_CHAIN_OPERATOR_TOKEN")
    if not secret or not x_operator_token or not secrets.compare_digest(x_operator_token, secret):
        raise HTTPException(status_code=403, detail="Operator authentication required")


class ApprovalInput(BaseModel):
    reviewer: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    approve: bool


@router.post("/planning-runs/{run_id}/approval", dependencies=[Depends(require_operator)])
async def approve_run(run_id: int, body: ApprovalInput, db: AsyncSession = Depends(get_db)):
    run = await db.get(PlanningRun, run_id)
    if run is None:
        raise HTTPException(404, "Planning run not found")
    validation = run.constraint_validation or {}
    strategy = validation.get("final_strategy")
    if (run.status.value != "success" or not strategy
            or validation.get("unresolved_violations") or validation.get("replanning_triggered")):
        raise HTTPException(409, "Run has no validated final strategy")
    existing = await db.scalar(select(PlanApproval).where(PlanApproval.planning_run_id == run_id))
    if existing:
        raise HTTPException(409, "Run has already received an approval decision")
    status = "approved" if body.approve else "rejected"
    row = PlanApproval(
        planning_run_id=run_id, strategy=strategy, status=status,
        reviewer=body.reviewer, reason=body.reason,
    )
    db.add(row)
    await db.flush()
    return {"run_id": run_id, "strategy": strategy, "status": status}


@router.get("/planning-runs/{run_id}/approval", dependencies=[Depends(require_operator)])
async def get_approval(run_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(PlanApproval).where(PlanApproval.planning_run_id == run_id))
    if row is None:
        raise HTTPException(404, "Approval not found")
    return {"run_id": row.planning_run_id, "strategy": row.strategy,
            "status": row.status, "reviewer": row.reviewer, "reason": row.reason}


@router.post("/events", dependencies=[Depends(require_operator)])
async def ingest_event(event: SupplyChainEvent, db: AsyncSession = Depends(get_db)):
    if event.occurred_at.tzinfo is None:
        raise HTTPException(422, "occurred_at must include timezone")
    previous = await db.scalar(select(ReplanningEvent).where(ReplanningEvent.event_id == event.event_id))
    if previous is not None:
        return {"event_id": event.event_id, "action": previous.action, "duplicate": True}
    last = await db.scalar(
        select(ReplanningEvent)
        .where(ReplanningEvent.entity_id == event.entity_id, ReplanningEvent.action == "queued")
        .order_by(ReplanningEvent.occurred_at.desc()).limit(1)
    )
    last_time = last.occurred_at if last else None
    if last_time is not None and last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    occurred = event.occurred_at.astimezone(timezone.utc)
    action = "queued" if should_replan(
        event.model_copy(update={"occurred_at": occurred}), last_planned_at=last_time,
    ) else "ignored"
    db.add(ReplanningEvent(
        event_id=event.event_id, kind=event.kind, entity_id=event.entity_id,
        occurred_at=occurred, magnitude=event.magnitude, action=action,
    ))
    await db.flush()
    return {"event_id": event.event_id, "action": action, "duplicate": False}


class ExecuteEventInput(BaseModel):
    request: "PlanningRequest"


@router.post("/events/{event_id}/execute", dependencies=[Depends(require_operator)])
async def execute_replanning_event(
    event_id: str, body: ExecuteEventInput, db: AsyncSession = Depends(get_db),
):
    """Explicitly execute a queued event for a supplied planning scope.

    This endpoint is synchronous and operator-triggered, not a queue worker.
    Do not execute untrusted event scopes without operator review.
    """
    from app.agents.graph import run_planning_workflow
    row = await db.scalar(select(ReplanningEvent).where(ReplanningEvent.event_id == event_id))
    if row is None:
        raise HTTPException(404, "Event not found")
    if row.action != "queued":
        raise HTTPException(409, "Event is not queued")
    # Compare-and-swap claim prevents two workers processing the same event.
    claimed = await db.execute(
        update(ReplanningEvent)
        .where(ReplanningEvent.id == row.id, ReplanningEvent.action == "queued")
        .values(action="processing")
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Event was claimed by another worker")
    await db.commit()
    try:
        result = await run_planning_workflow(body.request, force_rerun=True)
    except Exception:
        row.action = "failed"
        await db.commit()
        raise
    row.action = "processed"
    await db.commit()
    return {"event_id": event_id, "action": row.action,
            "planning_run_id": result.get("planning_run_id")}


from app.schemas.planning import PlanningRequest
ExecuteEventInput.model_rebuild()
