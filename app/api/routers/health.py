"""Liveness/readiness endpoint checking database connectivity."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.database.session import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    db_ok = await check_database_connection()

    body = {
        "status": "ok" if db_ok else "degraded",
        "dependencies": {"database": "ok" if db_ok else "unavailable"},
    }
    return JSONResponse(
        content=body,
        status_code=status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
