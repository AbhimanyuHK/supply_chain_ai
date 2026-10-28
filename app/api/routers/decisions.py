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
from sqlalchemy.exc import IntegrityError
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
    if not body.request.store_ids or not body.request.product_ids:
        raise HTTPException(422, "Non-empty store_ids and product_ids are required for event execution")
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
    if result.get("errors") or not result.get("planning_run_id"):
        row.action = "failed"
        await db.commit()
        raise HTTPException(502, "Replanning did not complete successfully")
    row.action = "processed"
    await db.commit()
    return {"event_id": event_id, "action": row.action,
            "planning_run_id": result.get("planning_run_id")}


from app.schemas.planning import PlanningRequest
ExecuteEventInput.model_rebuild()


@router.get("/events", dependencies=[Depends(require_operator)])
async def list_events(
    status: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Operator event queue inspection, including failed and stuck processing."""
    if limit < 1 or limit > 500:
        raise HTTPException(422, "limit must be between 1 and 500")
    if status is not None and status not in {
        "queued", "processing", "processed", "failed", "ignored"
    }:
        raise HTTPException(422, "Unknown event status")
    statement = select(ReplanningEvent).order_by(
        ReplanningEvent.created_at.desc()
    ).limit(limit)
    if status is not None:
        statement = statement.where(ReplanningEvent.action == status)
    rows = (await db.scalars(statement)).all()
    return [
        {
            "event_id": item.event_id,
            "kind": item.kind,
            "entity_id": item.entity_id,
            "occurred_at": item.occurred_at.isoformat(),
            "action": item.action,
        }
        for item in rows
    ]


@router.post("/events/{event_id}/retry", dependencies=[Depends(require_operator)])
async def retry_failed_event(event_id: str, db: AsyncSession = Depends(get_db)):
    """Manually requeue failed events; never silently retry in-flight work."""
    changed = await db.execute(
        update(ReplanningEvent)
        .where(ReplanningEvent.event_id == event_id, ReplanningEvent.action == "failed")
        .values(action="queued")
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "Only failed events can be retried")
    await db.flush()
    return {"event_id": event_id, "action": "queued"}


@router.post("/planning-runs/{run_id}/create-shipments", dependencies=[Depends(require_operator)])
async def create_approved_shipments(run_id: int, db: AsyncSession = Depends(get_db)):
    """Create PLANNED records only after approval; does not dispatch vehicles.

    Uses a row lock where supported and refuses to duplicate an existing run.
    """
    from app.models.entities import Shipment, ShipmentCreationClaim, PlanningRunStatus
    run = await db.scalar(
        select(PlanningRun).where(PlanningRun.id == run_id).with_for_update()
    )
    if run is None:
        raise HTTPException(404, "Planning run not found")
    approval = await db.scalar(
        select(PlanApproval).where(PlanApproval.planning_run_id == run_id)
    )
    validation = run.constraint_validation or {}
    recommendation = run.final_recommendation or {}
    if (
        run.status != PlanningRunStatus.SUCCESS
        or approval is None or approval.status != "approved"
        or not validation.get("final_strategy")
        or approval.strategy != validation.get("final_strategy")
        or recommendation.get("selected_strategy") != approval.strategy
        or validation.get("unresolved_violations")
        or validation.get("replanning_triggered")
        or recommendation.get("fell_back_to_invalid_scenario")
    ):
        raise HTTPException(409, "Run is not eligible for shipment creation")
    existing = await db.scalar(
        select(Shipment.shipment_id).where(Shipment.planning_run_id == run_id).limit(1)
    )
    if existing is not None:
        raise HTTPException(409, "Shipment records already exist for this run")
    lines = recommendation.get("shipment_plan") or []
    if not lines:
        raise HTTPException(409, "Approved plan contains no shipment lines")
    for line in lines:
        if (
            not isinstance(line, dict)
            or not all(isinstance(line.get(key), int) and line[key] > 0
                       for key in ("terminal_id", "store_id", "product_id", "quantity"))
        ):
            raise HTTPException(409, "Approved plan has invalid shipment lines")
    # A UNIQUE planning_run_id claim makes concurrent requests conflict at the DB level.
    # Claim and shipment inserts share the same transaction.
    db.add(ShipmentCreationClaim(planning_run_id=run_id))
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Shipment creation already claimed") from exc
    for line in lines:
        db.add(Shipment(
            terminal_id=line["terminal_id"],
            store_id=line["store_id"],
            product_id=line["product_id"],
            quantity=line["quantity"],
            shipment_date=run.planning_date,
            vehicle_id=line.get("vehicle_id"),
            planning_run_id=run_id,
        ))
    await db.flush()
    return {"run_id": run_id, "status": "planned", "shipments_created": len(lines)}
