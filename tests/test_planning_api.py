import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import app
from tests.test_agents_graph import _seed_minimal


@pytest.mark.asyncio
async def test_optimize_runs_workflow_and_persists_a_row(committed_db):
    # Same no-shortage seeding as test_run_planning_workflow_end_to_end_no_shortage -
    # needs no API key since zero shortages means zero LLM calls.
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/optimize",
            json={"planning_date": datetime.date.today().isoformat()},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["planning_run_id"] is not None
    assert len(body["trace"]) == 9
    assert body["errors"] == []
    assert body["supply_planning"]["candidate_plans"] == []


@pytest.mark.asyncio
async def test_list_planning_runs_includes_a_new_run(committed_db):
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        optimize_response = await client.post(
            "/api/v1/optimize",
            json={"planning_date": datetime.date.today().isoformat()},
        )
        run_id = optimize_response.json()["planning_run_id"]

        list_response = await client.get("/api/v1/planning-runs")

    assert list_response.status_code == 200
    ids = [row["id"] for row in list_response.json()]
    assert run_id in ids


@pytest.mark.asyncio
async def test_get_planning_run_matches_the_created_row(committed_db):
    await _seed_minimal(committed_db, with_demand_history=True, store_available_qty=50)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        optimize_response = await client.post(
            "/api/v1/optimize",
            json={"planning_date": datetime.date.today().isoformat()},
        )
        run_id = optimize_response.json()["planning_run_id"]

        get_response = await client.get(f"/api/v1/planning-runs/{run_id}")

    assert get_response.status_code == 200
    body = get_response.json()
    assert body["id"] == run_id
    assert body["status"] == "success"


@pytest.mark.asyncio
async def test_get_planning_run_404s_for_a_missing_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/planning-runs/999999")

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "not_found"
    assert body["details"] == {"run_id": 999999}
