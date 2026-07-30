import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import app


@pytest.mark.asyncio
async def test_health_reports_healthy_database():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "dependencies": {"database": "ok"}}


@pytest.mark.asyncio
async def test_health_reports_degraded_when_database_unreachable(monkeypatch):
    import app.api.routers.health as health_module

    async def _fake_db_down() -> bool:
        return False

    monkeypatch.setattr(health_module, "check_database_connection", _fake_db_down)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "dependencies": {"database": "unavailable"}}
