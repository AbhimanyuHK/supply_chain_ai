"""Database integration coverage for approval, event and outcome constraints."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.entities import (
    PlanApproval, PlanningOutcome, PlanningRun, PlanningRunStatus,
    ReplanningEvent, ShipmentCreationClaim,
)


def _run():
    return PlanningRun(
        planning_date=date(2026, 10, 28),
        demand_history_window_days=30,
        scope_key="integration-test-scope",
        llm_provider="test",
        llm_model="stub",
        status=PlanningRunStatus.SUCCESS,
        optimization_objective="minimize_cost",
    )


@pytest.mark.asyncio
async def test_duplicate_shipment_claim_rejected(db_session):
    run = _run()
    db_session.add(run)
    await db_session.flush()
    db_session.add(ShipmentCreationClaim(planning_run_id=run.id))
    await db_session.flush()
    db_session.add(ShipmentCreationClaim(planning_run_id=run.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_duplicate_approval_rejected(db_session):
    run = _run()
    db_session.add(run)
    await db_session.flush()
    db_session.add(PlanApproval(
        planning_run_id=run.id, strategy="priority_first",
        status="approved", reviewer="tester", reason="reviewed"
    ))
    await db_session.flush()
    db_session.add(PlanApproval(
        planning_run_id=run.id, strategy="priority_first",
        status="rejected", reviewer="tester", reason="duplicate"
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_duplicate_event_id_rejected(db_session):
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    kwargs = dict(
        event_id="integration-event", kind="demand_spike",
        entity_id="store-1", occurred_at=now, magnitude=0.5,
        action="queued", planning_request={"store_ids": [1], "product_ids": [1]},
    )
    db_session.add(ReplanningEvent(**kwargs))
    await db_session.flush()
    db_session.add(ReplanningEvent(**kwargs))
    with pytest.raises(IntegrityError):
        await db_session.flush()


def test_outcome_model_has_unique_reference_and_fk():
    table = PlanningOutcome.__table__
    assert any(
        column.unique for column in table.columns if column.name == "external_reference"
    )
    assert "planning_run_id" in table.columns
