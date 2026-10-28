"""Safety regression tests for operator approval and event execution."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.routers.decisions import ApprovalInput, approve_run


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
async def test_approval_rejects_mismatched_recommendation():
    run = SimpleNamespace(
        status=SimpleNamespace(value="success"),
        constraint_validation={"final_strategy": "priority_first",
                               "unresolved_violations": [], "replanning_triggered": False},
        final_recommendation={"selected_strategy": "balanced",
                              "fell_back_to_invalid_scenario": False},
    )
    db = FakeSession(run)
    with pytest.raises(HTTPException) as exc:
        await approve_run(1, ApprovalInput(reviewer="operator", reason="reviewed", approve=True), db)
    assert exc.value.status_code == 409
    assert db.added == []


@pytest.mark.asyncio
async def test_approval_rejects_invalid_fallback():
    run = SimpleNamespace(
        status=SimpleNamespace(value="success"),
        constraint_validation={"final_strategy": "priority_first",
                               "unresolved_violations": [], "replanning_triggered": False},
        final_recommendation={"selected_strategy": "priority_first",
                              "fell_back_to_invalid_scenario": True},
    )
    db = FakeSession(run)
    with pytest.raises(HTTPException) as exc:
        await approve_run(1, ApprovalInput(reviewer="operator", reason="reviewed", approve=True), db)
    assert exc.value.status_code == 409
    assert db.added == []
