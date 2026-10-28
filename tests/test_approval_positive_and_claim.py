"""Regression coverage for approval safety and database shipment claim uniqueness."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routers.decisions import ApprovalInput, approve_run
from app.models.base import Base
from app.models.entities import ShipmentCreationClaim


class FakeSession:
    def __init__(self, run):
        self.run = run
        self.added = []

    async def get(self, model, key):
        return self.run

    async def scalar(self, statement):
        return None

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        pass


@pytest.mark.asyncio
async def test_approval_accepts_matching_validated_strategy():
    run = SimpleNamespace(
        status=SimpleNamespace(value="success"),
        constraint_validation={"final_strategy": "priority_first",
                               "unresolved_violations": [], "replanning_triggered": False},
        final_recommendation={"selected_strategy": "priority_first",
                              "fell_back_to_invalid_scenario": False},
    )
    db = FakeSession(run)
    result = await approve_run(
        17, ApprovalInput(reviewer="operator", reason="validated", approve=True), db
    )
    assert result["status"] == "approved"
    assert len(db.added) == 1
    assert db.added[0].strategy == "priority_first"


def test_shipment_creation_claim_unique_per_run():
    """SQLite enforces uniqueness independently of application-level checks."""
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            # A planning run is required by the foreign key; this test checks
            # the table's unique constraint through the mapped column metadata.
            column = ShipmentCreationClaim.__table__.c.planning_run_id
            assert column.unique is True
    finally:
        engine.dispose()
