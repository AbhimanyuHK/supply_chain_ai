"""Regression coverage for approval safety and database shipment claim uniqueness."""
from types import SimpleNamespace

import pytest

from app.api.routers.decisions import ApprovalInput, approve_run
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
    """The ORM declares a database-enforced unique planning run claim."""
    column = ShipmentCreationClaim.__table__.c.planning_run_id
    assert column.unique is True
