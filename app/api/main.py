"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.health import router as health_router
from app.api.routers.planning import router as planning_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="1.2.0",
        description="AI-powered Supply Chain Planning Platform.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(planning_router, prefix=settings.api_v1_prefix)
    # Health stays unprefixed (standard convention: infra/load-balancer probes
    # expect a stable, unversioned path). Future routers (forecast, inventory,
    # fleet, route, simulate, shipments - see docs/interfaces/rest-api.md for
    # why each is still deliberately not built) register under the prefix too.

    return app


app = create_app()
